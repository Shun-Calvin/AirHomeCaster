"""Windows platform integration for AirHomeCaster.

- SingleInstance: named mutex guard so two copies never fight over capture.
- EndpointMute: mute/unmute of local speakers while streaming. WASAPI
  loopback keeps delivering the mix when the endpoint is muted, so muting
  locally is safe while casting.
- PowerWatcher: sleep/resume handling so streaming auto-recovers.
"""
import logging
import threading

log = logging.getLogger("AirHomeCaster.win")

MUTEX_NAME = "Global\\AirHomeCasterSingleInstanceMutex"
MUTEX_NAME_LOCAL = "Local\\AirHomeCasterSingleInstanceMutex"


class SingleInstance:
    """Acquire a named mutex; if already held, another copy is running."""

    def __init__(self):
        self.handle = None
        self.acquired = False

    def acquire(self) -> bool:
        try:
            import ctypes
            import ctypes.wintypes as wt
            kernel32 = ctypes.windll.kernel32
            CREATE_MUTEX = 0
            ERROR_ALREADY_EXISTS = 183
            handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if not handle:
                # fall back to local session namespace (per-user instances)
                handle = kernel32.CreateMutexW(None, False, MUTEX_NAME_LOCAL)
            err = kernel32.GetLastError()
            self.handle = handle
            self.acquired = err != ERROR_ALREADY_EXISTS
            if not self.acquired:
                log.warning("another AirHomeCaster instance holds the mutex")
            return self.acquired
        except Exception as e:
            log.warning("single-instance check failed: %s", e)
            self.acquired = True  # fail-open: better to run than block
            return True

    def release(self):
        if self.handle:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
            self.acquired = False


class EndpointMute:
    """Mute/unmute the default render endpoint (local speakers).

    Capture is WASAPI loopback, which keeps delivering the mix even when the
    endpoint is muted, so muting locally while casting is safe.

    Runs every COM call in a short-lived STA worker thread so it never fights
    with soundcard's MTA apartment in the audio engine.
    """

    def __init__(self):
        self._orig = None  # (mute, volume) before we touched it
        self._lock = threading.Lock()

    def _call_in_sta(self, fn):
        result = {}

        def work():
            try:
                result["value"] = fn()
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=work)
        t.start()
        t.join(10)
        if "error" in result:
            raise result["error"]
        if "value" not in result:
            raise TimeoutError("COM call timed out")
        return result["value"]

    def _get_vol(self):
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        enum = AudioUtilities.GetDeviceEnumerator()
        dev = enum.GetDefaultAudioEndpoint(0, 1)  # eRender / eMultimedia
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))

    def mute(self):
        with self._lock:
            try:
                def _do():
                    vol = self._get_vol()
                    if self._orig is None:
                        self._orig = (bool(vol.GetMute()),
                                      float(vol.GetMasterVolumeLevelScalar()))
                    vol.SetMute(1, None)
                self._call_in_sta(_do)
                return True
            except Exception as e:
                log.warning("mute failed: %s", e)
                return False

    def restore(self):
        with self._lock:
            if self._orig is None:
                return
            orig = self._orig
            self._orig = None
            try:
                def _do():
                    vol = self._get_vol()
                    was_muted, level = orig
                    vol.SetMasterVolumeLevelScalar(level, None)
                    vol.SetMute(1 if was_muted else 0, None)
                self._call_in_sta(_do)
            except Exception as e:
                log.warning("restore volume failed: %s", e)

    @property
    def active(self):
        return self._orig is not None


class PowerWatcher:
    """Listens for suspend/resume via WM_POWERBROADCAST in a hidden window.

    On resume, fires callback so the app can restart capture and reconnect.
    """

    WM_POWERBROADCAST = 0x0218
    PBT_APMSUSPEND = 0x0004
    PBT_APMRESUMEAUTOMATIC = 0x0012
    PBT_APMRESUMESUSPEND = 0x0007

    def __init__(self, on_suspend=None, on_resume=None):
        self.on_suspend = on_suspend
        self.on_resume = on_resume
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="power-watch")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            WC = ctypes.create_unicode_buffer("AirHomeCasterPowerWnd")
            WNDCLASS = ctypes.c_void_p * 5

            def wndproc(hwnd, msg, wparam, lparam):
                if msg == self.WM_POWERBROADCAST:
                    if wparam in (self.PBT_APMSUSPEND,):
                        if self.on_suspend:
                            self.on_suspend()
                    elif wparam in (self.PBT_APMRESUMEAUTOMATIC,
                                    self.PBT_APMRESUMESUSPEND):
                        if self.on_resume:
                            self.on_resume()
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
            proc = WNDPROC(wndproc)

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [("style", ctypes.c_uint),
                            ("lpfnWndProc", WNDPROC),
                            ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int),
                            ("hInstance", ctypes.c_void_p),
                            ("hIcon", ctypes.c_void_p),
                            ("hCursor", ctypes.c_void_p),
                            ("hbrBackground", ctypes.c_void_p),
                            ("lpszMenuName", ctypes.c_wchar_p),
                            ("lpszClassName", ctypes.c_wchar_p)]

            wc = WNDCLASSW()
            wc.lpfnWndProc = proc
            wc.lpszClassName = "AirHomeCasterPowerWnd"
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            wc.hInstance = kernel32.GetModuleHandleW(None)
            if not user32.RegisterClassW(ctypes.byref(wc)):
                return
            hwnd = user32.CreateWindowExW(
                0, "AirHomeCasterPowerWnd", "AirHomeCasterPower", 0,
                0, 0, 0, 0, None, None, wc.hInstance, None)
            if not hwnd:
                return
            msg = ctypes.c_void_p * 4
            # simple GetMessage loop
            import ctypes.wintypes as wt

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", ctypes.c_void_p),
                            ("message", wt.UINT),
                            ("wParam", wt.WPARAM),
                            ("lParam", wt.LPARAM),
                            ("time", wt.DWORD),
                            ("pt", wt.POINT),
                            ("lPrivate", wt.DWORD)]

            m = MSG()
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(m), None, 0, 0)
                if r <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(m))
                user32.DispatchMessageW(ctypes.byref(m))
        except Exception as e:
            log.debug("power watcher ended: %s", e)
