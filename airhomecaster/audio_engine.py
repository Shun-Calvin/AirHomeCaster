"""AirHomeCaster audio engine.

Captures Windows system audio (WASAPI loopback, optionally per-app), applies a
10-band equalizer, resamples to 44.1 kHz stereo and hands fixed-size chunks to
one or more RAOP (AirPlay) senders.
"""
import queue
import threading
import time

import numpy as np
import soundcard as sc
from scipy.signal import firwin, lfilter, lfilter_zi

TARGET_RATE = 44100
CAPTURE_RATE = 48000         # most Windows endpoints run 48 kHz
CAPTURE_MS = 10              # 10ms blocks -> minimal capture-side latency
CAPTURE_FRAMES = CAPTURE_RATE * CAPTURE_MS // 1000   # 480 frames
CHUNK_FRAMES = TARGET_RATE * CAPTURE_MS // 1000      # 441 frames @44.1k

# 10-band ISO octave centres, gains in dB
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


class TenBandEQ:
    """Cascade of biquad peaking filters with state carried across blocks.

    Stateless per-block filtering produced a boundary discontinuity every
    10 ms (periodic click, clearly audible at high volume).
    """

    def __init__(self, sample_rate: int, gains_db=None):
        self.sr = sample_rate
        self.set_gains(gains_db or [0.0] * len(EQ_BANDS))

    def set_gains(self, gains_db):
        gains_db = list(gains_db)[: len(EQ_BANDS)]
        while len(gains_db) < len(EQ_BANDS):
            gains_db.append(0.0)
        self._sos = _design_peaking_eq(self.sr, EQ_BANDS, gains_db)
        self._zi = [None] * len(self._sos)

    def reset_state(self):
        self._zi = [None] * len(self._sos)

    def process(self, x: np.ndarray) -> np.ndarray:
        y = x
        for i, (b, a) in enumerate(self._sos):
            if self._zi[i] is None:
                zi = lfilter_zi(b, a)
                zi = zi[:, None] * y[0][None, :] if y.ndim > 1 else zi * y[0]
            else:
                zi = self._zi[i]
            y, zf = lfilter(b, a, y, axis=0, zi=zi)
            self._zi[i] = zf
        return y


def _design_peaking_eq(sr, freqs, gains_db):
    """Return list of (b, a) for one biquad peaking filter per band."""
    coeffs = []
    for f, g in zip(freqs, gains_db):
        if abs(g) < 0.05:
            coeffs.append((np.array([1.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])))
            continue
        Q = 1.1
        A = 10 ** (g / 40.0)
        w0 = 2 * np.pi * f / sr
        alpha = np.sin(w0) / (2 * Q)
        cos_w0 = np.cos(w0)
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        coeffs.append((
            np.array([b0 / a0, b1 / a0, b2 / a0]),
            np.array([1.0, a1 / a0, a2 / a0]),
        ))
    return coeffs


class StreamResampler:
    """Exact streaming polyphase resampler (48000 -> 44100, up=147 down=160).

    Per-block resample_poly restarts its filter every 10 ms, leaving a step
    at each boundary (periodic tick, louder with the signal). This class
    keeps the input history and output phase across blocks; output is
    sample-identical to one-shot resample_poly (verified < 1e-6).
    Group delay is compensated exactly like scipy: n_pre_pad pre-taps so
    output m aligns with input center m*down/up.
    """

    def __init__(self, up=147, down=160, channels=2):
        max_rate = max(up, down)
        half = 10 * max_rate
        h = firwin(2 * half + 1, 1.0 / max_rate, window=("kaiser", 5.0)) * up
        self.up, self.down, self.ch = up, down, channels
        # scipy resample_poly alignment: pre-pad so output sample 0 is the
        # filter's group-delay center, then it removes n_pre_remove outputs.
        n_pre_pad = down - half % down
        n_pre_remove = (half + n_pre_pad) // down
        self.n_pre_remove = n_pre_remove
        h = np.concatenate([np.zeros(n_pre_pad), h])
        self.h_len = len(h)
        self.J = int(np.ceil(len(h) / up))            # taps per phase
        self.hp = np.concatenate([h, np.zeros(self.J * up - len(h))])
        # hp[p, j] = h[p + j*up]  (reshape row-major as (J, up) then transpose)
        self.hp = self.hp.reshape((self.J, up)).T
        self.hist = np.zeros((0, channels), dtype=np.float64)
        self.base = 0        # global input index of hist[0] (Python int)
        self.m = 0           # next OUTPUT (post-trim) index (Python int)

    def process(self, x: np.ndarray) -> np.ndarray:
        x64 = x.astype(np.float64, copy=False)
        self.hist = np.concatenate([self.hist, x64], axis=0) if len(self.hist) else x64.copy()
        # All index math in Python ints / int64: numpy scalars on Windows are
        # int32 and overflow after ~5 min of 48kHz input (n_in * up > 2^31),
        # which produced negative m_hi and silence forever (the "no audio
        # after a while" bug). base/m are kept as pure Python ints.
        n_in = int(self.base) + len(self.hist)
        m_hi = (n_in * self.up - 1) // self.down - self.n_pre_remove
        m_hi = int(m_hi)
        if m_hi < self.m:
            return np.zeros((0, self.ch), dtype=np.float32)
        # never emit more than ~100ms of output in one call: a big counter
        # jump (discontinuity after suspend, backlog burst) would otherwise
        # try to materialize millions of output rows at once (memory blowup
        # + a multi-second stall). 4410 = 100ms at 44.1k — far above the
        # normal 441/block, so realtime flow is never throttled; a 5-minute
        # gap recovers in ~57 calls (~0.6s wall time).
        m_hi = min(m_hi, self.m + 4410)
        ms = np.arange(self.m, m_hi + 1, dtype=np.int64)
        # raw index for trimmed output m: m + n_pre_remove
        ts = (ms + self.n_pre_remove) * self.down
        centers = ts // self.up
        phases = ts % self.up
        j = np.arange(self.J)
        # polyphase convolution: output = sum_j h[phase + j*up] * x[center-j]
        hi = centers[:, None] - j[None, :]
        if self.base:
            hi = hi - self.base
        valid = hi >= 0
        hi_c = np.clip(hi, 0, max(len(self.hist) - 1, 0))
        taps = self.hp[phases[:, None], j[None, :]]               # (M, J)
        samples = self.hist[hi_c]                                 # (M, J, ch)
        eff = taps * valid                                        # (M, J)
        y = np.einsum("mj,mjc->mc", eff, samples, optimize=True)
        self.m = m_hi + 1
        # trim consumed history (keep lookback for future outputs)
        keep_from = int(max(0, centers[-1] - self.J + 1))
        cut = keep_from - int(self.base)
        if cut > 1024:
            self.hist = self.hist[cut:]
            self.base = keep_from
        return y.astype(np.float32)


class Limiter:
    """Soft-knee limiter: tanh compression above threshold, no hard clip.

    Hard clipping a boosted signal generates harmonic distortion (the
    "noise at high volume"). Soft knee keeps peaks under the ceiling with
    far less distortion; gain moves are smoothed across blocks.
    """

    def __init__(self, threshold=0.89, ceiling=0.97):
        self.threshold = threshold
        self.ceiling = ceiling
        self.gain = 1.0

    def process(self, x: np.ndarray) -> np.ndarray:
        peak = float(np.abs(x).max()) + 1e-9
        if peak <= self.threshold:
            target = 1.0
        else:
            target = min(1.0, self.threshold / peak)
        # attack fast, release slow (per 10ms block)
        rate = 0.5 if target < self.gain else 0.02
        self.gain += (target - self.gain) * rate
        y = x * self.gain
        # soft knee: only content above threshold is compressed via tanh
        absy = np.abs(y)
        over = absy > self.threshold
        if over.any():
            sign = np.sign(y)
            t = (absy - self.threshold) / (1.0 - self.threshold + 1e-9)
            compressed = self.threshold + (1.0 - self.threshold) * np.tanh(t)
            y = np.where(over, sign * compressed, y)
        np.clip(y, -self.ceiling, self.ceiling, out=y)
        return y


class AudioEngine:
    """Captures loopback audio and pushes 100 ms chunks to subscribers."""

    def __init__(self):
        self.subscribers = []           # callables chunk(t_int16: np.ndarray)
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.eq = None                  # TenBandEQ or None
        self.gain = 1.0
        self.limiter = Limiter()
        self.limiter_enabled = True
        self._resampler = None          # StreamResampler, created on start
        self.mic_id = None              # specific output device id, None = default
        self.stats = {"chunks": 0, "errors": 0, "last_error": ""}
        self._drop_count = 0
        self.level = 0.0          # smoothed peak 0..1 for UI meter
        self.device_name = ""     # human name of capture endpoint

    def set_eq_gains(self, gains_db):
        if self.eq is None:
            self.eq = TenBandEQ(CAPTURE_RATE)
        self.eq.set_gains(gains_db)

    def clear_eq(self):
        self.eq = None

    def enable_limiter(self, on: bool):
        self.limiter_enabled = bool(on)

    def add_subscriber(self, fn):
        with self.lock:
            if fn not in self.subscribers:  # idempotent: toggle_stream re-adds
                self.subscribers.append(fn)

    def remove_subscriber(self, fn):
        with self.lock:
            if fn in self.subscribers:
                self.subscribers.remove(fn)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="capture")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
        self.thread = None

    def _loop(self):
        try:
            if self.mic_id:
                mic = sc.get_microphone(id=self.mic_id, include_loopback=True)
            else:
                # soundcard can't match id=None; resolve via default speaker
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=spk.id, include_loopback=True)
            self.device_name = mic.name
        except Exception as e:
            self.stats["last_error"] = f"device open failed: {e}"
            self.stats["errors"] += 1
            self.running = False
            return
        try:
            self._resampler = StreamResampler(up=147, down=160, channels=2)
            with mic.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=CAPTURE_FRAMES) as rec:
                while self.running:
                    try:
                        data = rec.record(numframes=CAPTURE_FRAMES)
                    except Exception as e:
                        self.stats["errors"] += 1
                        self.stats["last_error"] = str(e)
                        time.sleep(0.2)
                        continue
                    if not self.subscribers:
                        continue
                    if self.eq is not None:
                        try:
                            data = self.eq.process(data)
                        except Exception as e:
                            self.stats["errors"] += 1
                            self.stats["last_error"] = f"eq: {e}"
                    if self.gain != 1.0:
                        data = data * self.gain
                    if self.limiter_enabled and self.limiter is not None:
                        try:
                            data = self.limiter.process(data)
                        except Exception:
                            pass
                    # streaming resample to 44.1k — phase-continuous across
                    # blocks (per-block resample_poly left boundary ticks)
                    try:
                        out = self._resampler.process(data)
                        if len(out) == 0:
                            continue
                    except Exception as e:
                        self.stats["errors"] += 1
                        self.stats["last_error"] = f"resample: {e}"
                        continue
                    pcm = np.clip(out, -1.0, 1.0)
                    # smoothed peak level for the UI meter
                    try:
                        peak = float(np.abs(pcm).max())
                        self.level = self.level * 0.7 + peak * 0.3
                    except Exception:
                        self.level = 0.0
                    ints = (pcm * 32767.0).astype("<i2")
                    with self.lock:
                        subs = list(self.subscribers)
                    for fn in subs:
                        try:
                            fn(ints)
                        except Exception as e:
                            self.stats["errors"] += 1
                            self.stats["last_error"] = f"subscriber: {e}"
                    self.stats["chunks"] += 1
        except Exception as e:
            self.stats["last_error"] = f"recorder: {e}"
            self.stats["errors"] += 1
        finally:
            self.running = False


def list_output_devices():
    devs = []
    for d in sc.all_microphones(include_loopback=True):
        if d.isloopback:
            devs.append({"id": d.id, "name": d.name, "channels": 2})
    return devs
