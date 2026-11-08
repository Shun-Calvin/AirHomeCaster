"""RAOP (AirPlay v1 audio) sender built on pyatv 0.18 public internals.

Each device gets its own thread + asyncio loop. PCM frames are pushed into a
bounded queue by the AudioEngine and consumed as a custom AudioSource.
AirPlay carries big-endian s16 samples; readframes() byteswaps.
"""
import array
import asyncio
import io
import queue
import sys
import threading
import time

from pyatv.const import Protocol
from pyatv.core import MutableService
from pyatv.interface import MediaMetadata, Settings
from pyatv.protocols.airplay.utils import (
    AirPlayMajorVersion,
    get_protocol_version,
    pct_to_dbfs,
)
from pyatv.protocols.raop.protocols import StreamContext, airplayv1, airplayv2
from pyatv.protocols.raop.stream_client import RaopListener, StreamClient
from pyatv.protocols.raop import audio_source as audio_source_mod
from pyatv.support.http import http_connect
from pyatv.support.rtsp import RtspSession

import pyatv.protocols.raop.audio_source


class QueueAudioSource(audio_source_mod.AudioSource):
    """AudioSource that pulls s16le stereo 44100 Hz frames from a queue."""

    def __init__(self, sample_rate: int, channels: int, sample_size: int, src: "queue.Queue",
                 on_underrun=None):
        self._q = src
        self._buf = b""
        self._started = time.monotonic()
        self._closed = False
        self._on_underrun = on_underrun

    async def readframes(self, nframes: int) -> bytes:
        # Non-blocking: the RTP timeline must advance at real-time pace from
        # the very first packet — a blocked read stalls pyatv's pacing clock
        # and the later catch-up burst shifts playback seconds into the
        # future. Underruns emit instant silence instead.
        need = nframes * 4  # 2 ch * 2 bytes
        try:
            while True:
                chunk = self._q.get_nowait()
                if chunk:
                    self._buf += chunk
        except queue.Empty:
            if self._on_underrun and not self._closed:
                try:
                    self._on_underrun()
                except Exception:
                    pass
        if self._closed and not self._buf:
            return b""  # end stream -> pyatv pads remaining latency, then stops
        have = min(need, len(self._buf))
        out, self._buf = self._buf[:have], self._buf[have:]
        if len(out) < need:
            out += b"\x00" * (need - len(out))
        # AirPlay/RAOP carries big-endian s16 samples. pyatv's built-in sources
        # byteswap little-endian host data in _to_audio_samples(); mirror that.
        arr = array.array("h", out)
        if sys.byteorder == "little":
            arr.byteswap()
        return arr.tobytes()

    async def get_metadata(self):
        return MediaMetadata(title="AirHomeCaster", artist=None, album=None, duration=None)

    @property
    def sample_rate(self):
        return 44100

    @property
    def channels(self):
        return 2

    @property
    def sample_size(self):
        return 2

    @property
    def duration(self):
        return 0

    def close_source(self):
        self._closed = True


class _Listener(RaopListener):
    def __init__(self, sender):
        self.sender = sender

    def playing(self, playback_info):
        self.sender.connected = True
        self.sender.stats["playing_became_true"] = time.time()

    def stopped(self):
        # pyatv calls this when the send loop exits — normally OR on error.
        # Either way the stream is dead; surface it so the app can reconnect.
        self.sender.connected = False
        self.sender.stats["stopped_at"] = time.time()
        if self.sender.on_stream_died:
            try:
                self.sender.on_stream_died(self.sender)
            except Exception:
                pass


class RaopSender:
    """Streams live PCM to one AirPlay (RAOP) device."""

    def __init__(self, name: str, host: str, port: int, volume: float = 50.0,
                 latency_ms: int = 0, password: str = None, props: dict = None,
                 base_latency_ms: int = 60):
        self.name = name
        self.host = host
        self.port = port
        self.props = props or {}
        self.base_latency_ms = base_latency_ms  # protocol buffer before playback
        self.volume = volume          # percent 0..100
        self.latency_ms = latency_ms
        self.password = password
        self.connected = False
        self.stats = {"sent_chunks": 0, "errors": 0, "last_error": "",
                      "underruns": 0, "stopped_at": 0.0}
        self.on_stream_died = None   # callback(sender) when stream loop exits
        self.q: "queue.Queue" = queue.Queue(maxsize=25)  # hard 0.5s latency bound

        self._thread = None
        self._loop = None
        self._stop_evt = None
        self._ready = threading.Event()
        self._source = None
        self._client = None
        self._ready_time = 0.0   # monotonic-ish wall time when connect finished
        self._pct = volume
        self._engine = None
        self._stop_requested = False   # user-initiated stop vs death

    # ---------- engine hookup ----------
    def attach_engine(self, engine):
        """Remember engine and wire its chunks into this sender's queue."""
        self._engine = engine
        engine.add_subscriber(self._on_chunk)

    def _on_chunk(self, ints):
        self.push_chunk(ints.tobytes())

    # ---------- lifecycle ----------
    def start(self) -> bool:
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"raop-{self.name}")
        self._thread.start()
        if not self._ready.wait(timeout=20):
            self.stats["last_error"] = "connect timeout"
            return False
        return self.connected

    def stop(self):
        self._stop_requested = True
        if self._stop_evt:
            self._stop_evt.set()
        try:
            self.q.put_nowait(b"")  # wake feeder
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=6)
        self.connected = False

    def push_chunk(self, pcm_s16le: bytes):
        """Called from audio thread; non-blocking."""
        try:
            self.q.put_nowait(pcm_s16le)
        except queue.Full:
            # drop oldest to keep realtime
            try:
                self.q.get_nowait()
                self.q.put_nowait(pcm_s16le)
            except Exception:
                pass

    def clear_queue(self):
        """Drop any buffered PCM (e.g. when master streaming restarts)."""
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def set_volume(self, pct: float):
        """Update live volume. Applied via RTSP SET_PARAMETER on active session."""
        self._pct = pct
        self.volume = pct
        if self._client and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._client.set_volume(pct_to_dbfs(pct)), self._loop)

    def _on_underrun(self):
        # called from the sender thread when the queue starved
        self.stats["underruns"] += 1

    # ---------- worker ----------
    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self.stats["last_error"] = str(e)
            self.stats["errors"] += 1
        finally:
            self.connected = False
            self.stats["stopped_at"] = time.time()
            self._ready.set()
            # _main returning means the send loop ended. If this wasn't a
            # user stop, notify the app so it can reconnect.
            if self.on_stream_died and not self._stop_requested:
                try:
                    self.on_stream_died(self)
                except Exception:
                    pass
            try:
                self._loop.close()
            except Exception:
                pass

    async def _main(self):
        loop = asyncio.get_event_loop()
        settings = Settings()
        context = StreamContext()
        context.sample_rate = 44100
        context.channels = 2
        context.bytes_per_channel = 2
        context.password = self.password
        total_ms = max(0, self.base_latency_ms) + max(0, self.latency_ms)
        context.latency = int(total_ms * 44.1)

        host = str(self.host)  # pyatv scan returns IPv4Address objects
        connection = await http_connect(host, self.port)
        rtsp = RtspSession(connection)

        service = MutableService(
            None,            # identifier
            Protocol.RAOP,
            self.port,
            {},              # properties
            None,            # credentials
            self.password,   # password
            True,            # enabled
        )
        # AirPlay v1 vs v2 from mdns features (same logic pyatv uses)
        version = get_protocol_version(service, AirPlayMajorVersion.AirPlayV1)
        protocol_class = (
            airplayv1.AirPlayV1
            if version == AirPlayMajorVersion.AirPlayV1
            else airplayv2.AirPlayV2
        )
        protocol = protocol_class(context, rtsp)
        client = StreamClient(rtsp, context, protocol, settings)
        client.listener = _Listener(self)

        # mdns TXT properties drive encryption/metadata negotiation; fall back
        # to rtsp info() when the caller didn't supply them
        props = dict(self.props or {})
        if not props:
            try:
                resp = await rtsp.info()
                if isinstance(resp, dict):
                    props = {str(k): str(v) for k, v in resp.items()}
            except Exception:
                props = {}
        await client.initialize(props)

        self._client = client
        self.connected = True
        self._ready.set()
        self._ready_time = time.time()

        src = QueueAudioSource(44100, 2, 2, self.q,
                               on_underrun=self._on_underrun)
        self._source = src
        try:
            await client.send_audio(
                src,
                MediaMetadata(title="AirHomeCaster", artist=None, album=None, duration=None),
                # applied by pyatv AFTER record/flush when the receiver accepts it
                volume=self.volume,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.stats["last_error"] = str(e)
            self.stats["errors"] += 1
        finally:
            self.connected = False
            try:
                await client.close()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
