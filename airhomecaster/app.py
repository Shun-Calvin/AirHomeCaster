"""AirHomeCaster — stream Windows system audio to AirPlay devices."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import queue as queue_mod
from tkinter import ttk, messagebox, filedialog

import numpy as np
import pyatv
from pyatv.const import Protocol

from airhomecaster.audio_engine import AudioEngine, EQ_BANDS, list_output_devices
from airhomecaster.raop_sender import RaopSender
from airhomecaster.win_integration import SingleInstance, EndpointMute, PowerWatcher

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
APP_TITLE = "AirHomeCaster"
APP_VERSION = "2.1.0"

LATENCY_PROFILES = {
    "ultra": ("Ultra (20ms)", "極速 (20ms)", 20),
    "insane": ("Insane (15ms)", "瘋狂 (15ms)", 15),
    "low": ("Low (250ms)", "低延遲 (250ms)", 250),
    "balanced": ("Balanced (600ms)", "平衡 (600ms)", 600),
    "stable": ("Stable (1200ms)", "穩定優先 (1200ms)", 1200),
}

# ---- i18n ------------------------------------------------------------
I18N = {
    "en": {
        "app_sub": "Windows system audio → AirPlay",
        "scan": "Scan Devices", "scanning": "Scanning…",
        "start_stream": "Start Streaming", "stop_stream": "Stop Streaming",
        "master_vol": "Master Volume", "input": "Input",
        "capture_default": "System default output", "change": "Change…",
        "latency_mode": "Latency Mode", "volume": "Volume",
        "extra_lat": "Extra delay",
        "idle": "Idle", "connecting": "Connecting…", "connected": "Connected",
        "failed": "Failed", "lang_note": "Restart to apply language/theme",
        "devices_found": "{} device(s) found",
        "no_devices": "No AirPlay devices found\nMake sure the device is on the same network, then click Scan Devices",
        "ready": "Ready",
        "n_ready": "{} device(s) ready · press Start Streaming",
        "streaming_n": "Streaming → {} device(s)",
        "need_device": "Connect at least one device first (▶ on a card).",
        "stream_start": "▶ Streaming started", "stream_stop": "■ Streaming stopped",
        "conn_ok": "✓ {} connected", "conn_fail": "✗ {} connect failed: {}",
        "conn_to": "→ Connect {} ({}:{}), latency={}ms",
        "disc": "← {} disconnected",
        "auto_reconnect": "Auto-reconnect ({}/5)…",
        "eq_reset": "EQ reset",
        "eq_title": "Equalizer (dB −12…+12)", "reset": "Reset",
        "menu_devices": "Devices", "menu_audio": "Audio", "menu_help": "Help",
        "menu_rescan": "Rescan devices  (F5)", "menu_exit": "Exit",
        "menu_pick_capture": "Choose capture device…",
        "menu_reinit": "Re-initialize audio engine",
        "menu_settings": "Settings", "menu_about": "About",
        "settings_lang": "Language", "settings_theme": "Theme",
        "settings_autostart": "Start with Windows",
        "settings_min_tray": "Minimize to tray on close",
        "settings_idle": "Auto-disconnect when idle",
        "settings_idle_min": "minutes (0 = never)",
        "settings_autodb": "Auto dB mode (Music / Meeting / Movie)",
        "settings_oneshot": "One-click connect + stream",
        "settings_save": "Save", "settings_title": "Settings",
        "tray_show": "Show", "tray_exit": "Exit",
        "idle_kick": "Idle {} min → auto-disconnected",
        "db_detect": "Auto dB: {} → EQ preset applied",
        "db_music": "Music", "db_meeting": "Meeting", "db_movie": "Movie",
        "db_auto": "Auto dB", "db_off": "Off",
        "about_text": "AirHomeCaster v{}\n\nStream Windows system audio to AirPlay devices\n(HomePod / Apple TV / Sonos)\n\nMulti-device · 10-band EQ · Auto dB · Idle auto-disconnect",
        "apply": "Apply", "pick_capture_hint": "Choose the output device to capture (loopback)",
        "theme_light": "Light", "theme_dark": "Dark",
        "reinit": "Audio engine re-initialized",
        "capture_set": "Capture device: {}",
        "capture_default_log": "Capture device: system default",
        "latency_applied": "Latency mode: {} — reconnect devices to apply",
        "one_click_hint": "One-click: connected + streaming",
        "another_instance": "AirHomeCaster is already running\n\nCheck the system tray — a copy is already streaming audio.",
        "mute_while_stream": "Mute local speakers while streaming",
        "limiter": "Anti-clip limiter",
        "eq_export": "Export EQ preset…", "eq_import": "Import EQ preset…",
        "eq_saved": "EQ preset saved: {}",
        "eq_loaded": "EQ preset loaded: {}",
        "eq_load_fail": "Load failed: {}",
        "eq_file": "AirHomeCaster EQ preset (*.aceq)|*.aceq|JSON (*.json)|*.json",
        "sleep_suspended": "System suspending — streaming paused",
        "sleep_resume": "System resumed — reconnecting devices…",
        "resume_fail": "Reconnect after resume failed for {}",
        "stability_relax": "Unstable at this latency — switched to {}",
        "starving": "Audio buffer starving — device may drop out",
    },
    "zh": {
        "app_sub": "Windows 系統音訊 → AirPlay",
        "scan": "掃描裝置", "scanning": "掃描中…",
        "start_stream": "開始串流", "stop_stream": "停止串流",
        "master_vol": "主音量", "input": "輸入",
        "capture_default": "系統預設輸出", "change": "更改…",
        "latency_mode": "延遲模式", "volume": "音量",
        "extra_lat": "額外延遲",
        "idle": "閒置", "connecting": "連線中…", "connected": "已連線",
        "failed": "失敗", "lang_note": "重啟後套用語言/主題",
        "devices_found": "找到 {} 個裝置",
        "no_devices": "尚未找到 AirPlay 裝置\n請確認裝置在同一網段，然後按「掃描裝置」",
        "ready": "就緒",
        "n_ready": "{} 個裝置已就緒 · 按「開始串流」開始",
        "streaming_n": "串流中 → {} 個裝置",
        "need_device": "請先按裝置卡上的 ▶ 連接至少一個裝置。",
        "stream_start": "▶ 開始串流", "stream_stop": "■ 停止串流",
        "conn_ok": "✓ {} 已連線", "conn_fail": "✗ {} 連線失敗：{}",
        "conn_to": "→ 連線 {} ({}:{}), 延遲={}ms",
        "disc": "← {} 已斷線",
        "auto_reconnect": "自動重連 ({}/5)…",
        "eq_reset": "EQ 已重設",
        "eq_title": "等化器 (dB −12…+12)", "reset": "重設",
        "menu_devices": "裝置", "menu_audio": "音訊", "menu_help": "說明",
        "menu_rescan": "重新掃描裝置  (F5)", "menu_exit": "結束",
        "menu_pick_capture": "選擇擷取裝置…",
        "menu_reinit": "重新初始化音訊引擎",
        "menu_settings": "設定", "menu_about": "關於",
        "settings_lang": "語言", "settings_theme": "主題",
        "settings_autostart": "開機自動啟動",
        "settings_min_tray": "關閉時縮到系統匣",
        "settings_idle": "閒置自動斷線",
        "settings_idle_min": "分鐘（0 = 從不）",
        "settings_autodb": "自動 dB 模式（音樂/會議/電影）",
        "settings_oneshot": "一鍵連接+串流",
        "settings_save": "儲存", "settings_title": "設定",
        "tray_show": "顯示", "tray_exit": "結束",
        "idle_kick": "閒置 {} 分鐘 → 已自動斷線",
        "db_detect": "自動 dB：{} → 已套用 EQ 預設",
        "db_music": "音樂", "db_meeting": "會議", "db_movie": "電影",
        "db_auto": "自動 dB", "db_off": "關閉",
        "about_text": "AirHomeCaster v{}\n\n把 Windows 系統音訊串流到 AirPlay 裝置\n（HomePod / Apple TV / Sonos）\n\n多裝置同播 · 10-band EQ · 自動 dB · 閒置自動斷線",
        "apply": "套用", "pick_capture_hint": "選擇要擷取的輸出裝置（loopback）",
        "theme_light": "淺色", "theme_dark": "深色",
        "reinit": "音訊引擎已重新初始化",
        "capture_set": "擷取裝置：{}",
        "capture_default_log": "擷取裝置：系統預設",
        "latency_applied": "延遲模式：{} — 重連裝置後生效",
        "one_click_hint": "一鍵模式：已連接並開始串流",
        "another_instance": "AirHomeCaster 已在執行中\n\n請檢查系統匣 — 已有一份正在運作。",
        "mute_while_stream": "串流時靜音本機喇叭",
        "limiter": "削波保護（Limiter）",
        "eq_export": "匯出 EQ 設定…", "eq_import": "匯入 EQ 設定…",
        "eq_saved": "EQ 已儲存：{}",
        "eq_loaded": "EQ 已載入：{}",
        "eq_load_fail": "載入失敗：{}",
        "eq_file": "AirHomeCaster EQ 設定 (*.aceq)|*.aceq|JSON (*.json)|*.json",
        "sleep_suspended": "系統睡眠中 — 串流已暫停",
        "sleep_resume": "系統已喚醒 — 正在重連裝置…",
        "resume_fail": "喚醒後重連失敗：{}",
        "stability_relax": "此延遲不穩定 — 已切換至 {}",
        "starving": "音訊緩衝不足 — 裝置可能中斷",
    },
}

LIGHT_COLORS = {
    "bg": "#f4f5f7", "panel": "#ffffff", "card": "#ffffff",
    "card_active": "#e3efff", "accent": "#2563eb", "accent_ok": "#16a34a",
    "accent_warn": "#d97706", "accent_err": "#dc2626",
    "fg": "#111827", "fg_dim": "#6b7280", "entry_bg": "#e9ebef",
    "accent_fg": "#ffffff", "btn2": "#e5e7eb",
}
DARK_COLORS = {
    "bg": "#1e1f24", "panel": "#26272e", "card": "#2d2e36",
    "card_active": "#33415a", "accent": "#4a9eff", "accent_ok": "#3ddc84",
    "accent_warn": "#ffb340", "accent_err": "#ff5c5c",
    "fg": "#e8e9ec", "fg_dim": "#9a9ca6", "entry_bg": "#1a1b20",
    "accent_fg": "#0b1620", "btn2": "#3a3b44",
}

EQ_PRESETS = {
    "music":   [4, 3, 1, 0, -1, -1, 0, 2, 3, 4],
    "meeting": [-6, -5, -3, 0, 2, 3, 3, 2, 0, -2],
    "movie":   [5, 4, 2, 0, -1, -2, 0, 2, 4, 5],
}


def tr(lang, key):
    return I18N.get(lang, I18N["zh"]).get(key, key)


class DBClassifier:
    """Lightweight content classifier from spectral features.

    music: strong bass + wide spectrum + steady energy
    meeting/speech: energy concentrated 200Hz-4kHz, low bass, dynamic pauses
    movie: wide dynamic range, strong LFE bursts
    """

    LABELS = ("music", "meeting", "movie")

    def __init__(self):
        self.ring = []          # recent (bass_ratio, mid_ratio, hf_ratio, rms, peak_rms)
        self.last_label = None
        self.last_change = time.time()
        self.cooldown = 20.0    # don't flip faster than this

    def feed(self, pcm: np.ndarray, sr: int) -> str:
        try:
            spec = np.abs(np.fft.rfft(pcm[:, 0] if pcm.ndim > 1 else pcm, n=2048))
            freqs = np.fft.rfftfreq(2048, 1.0 / sr)
            total = spec.sum() + 1e-9
            bass = spec[(freqs >= 20) & (freqs < 250)].sum() / total
            mid = spec[(freqs >= 250) & (freqs < 4000)].sum() / total
            hf = spec[(freqs >= 4000)].sum() / total
            rms = float(np.sqrt((pcm ** 2).mean()))
            self.ring.append((bass, mid, hf, rms))
            if len(self.ring) > 150:      # ~3s of 20ms frames
                self.ring.pop(0)
            if len(self.ring) < 100 or time.time() - self.last_change < self.cooldown:
                return self.last_label or ""
            arr = np.array(self.ring)
            bass_m, mid_m, hf_m = arr[:, 0].mean(), arr[:, 1].mean(), arr[:, 2].mean()
            rms_m, rms_s = arr[:, 3].mean(), arr[:, 3].std()
            label = self._decide(bass_m, mid_m, hf_m, rms_m, rms_s)
            if label and label != self.last_label:
                self.last_label = label
                self.last_change = time.time()
                return label
        except Exception:
            pass
        return ""

    def _decide(self, bass, mid, hf, rms, rms_std):
        if rms < 0.01:
            return ""                      # silence: no decision
        # speech: mid-heavy, low bass, spiky dynamics (talk pauses)
        if mid > 0.55 and bass < 0.25 and rms_std > 0.02:
            return "meeting"
        # music: bass present + high hf content + steady energy
        if bass > 0.35 and hf > 0.18 and rms_std < 0.05:
            return "music"
        # movie: big dynamics swings, moderate everything
        if rms_std > 0.06:
            return "movie"
        return self.last_label or ""


class Autostart:
    """Windows startup entry via registry HKCU Run key."""

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "AirHomeCaster"
    FULL_KEY = "HKCU\\" + RUN_KEY

    @classmethod
    def _reg(cls, args):
        # reg.exe outputs in the console codepage; decode bytes with errors ignored
        p = subprocess.run(args, capture_output=True)
        out = (p.stdout or b"").decode(errors="ignore")
        err = (p.stderr or b"").decode(errors="ignore")
        return out + err

    @classmethod
    def is_enabled(cls):
        try:
            return cls.VALUE_NAME in cls._reg(
                ["reg", "query", cls.FULL_KEY, "/v", cls.VALUE_NAME])
        except Exception:
            return False

    @classmethod
    def set_enabled(cls, on):
        target = f'"{sys.executable}" "{os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch.py")}"'
        try:
            if on:
                cls._reg(
                    ["reg", "add", cls.FULL_KEY, "/v", cls.VALUE_NAME,
                     "/t", "REG_SZ", "/d", target, "/f"])
            else:
                cls._reg(
                    ["reg", "delete", cls.FULL_KEY, "/v",
                     cls.VALUE_NAME, "/f"])
        except Exception:
            pass


class Tray:
    """System tray icon via pystray, driven from its own thread."""

    def __init__(self, app):
        self.app = app
        self.icon = None

    def start(self):
        try:
            import pystray
            from PIL import Image, ImageDraw

            def make_image():
                logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         os.pardir, "logo_256.png")
                try:
                    img = Image.open(logo_path).convert("RGBA")
                    return img.resize((64, 64), Image.LANCZOS)
                except Exception:
                    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    d = ImageDraw.Draw(img)
                    d.ellipse((6, 6, 58, 58), fill=(74, 158, 255, 255))
                    d.polygon([(26, 20), (26, 44), (46, 32)],
                              fill=(255, 255, 255, 255))
                    return img

            menu = pystray.Menu(
                pystray.MenuItem(lambda item: tr(self.app.lang, "tray_show"),
                                 lambda item: self.app.tray_show(), default=True),
                pystray.MenuItem(lambda item: (
                    tr(self.app.lang, "start_stream") if not self.app.engine.running
                    else tr(self.app.lang, "stop_stream")),
                    lambda item: self.app.tray_toggle_stream()),
                pystray.MenuItem(lambda item: tr(self.app.lang, "tray_exit"),
                                 lambda item: self.app.tray_exit()))
            self.icon = pystray.Icon("AirHomeCaster", make_image(), "AirHomeCaster", menu)
            threading.Thread(target=self._run_icon, daemon=True).start()
        except Exception as e:
            print("tray unavailable:", e, file=sys.stderr)

    def _run_icon(self):
        try:
            self.icon.run()
        except Exception as e:
            print("tray run failed:", e, file=sys.stderr)
            self.icon = None   # disabled: on_close will really close

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None


class DeviceScanner:
    """mDNS scan for RAOP devices in background."""

    def __init__(self, callback):
        self.callback = callback
        self.devices = []
        self.scanning = False

    def scan(self):
        if self.scanning:
            return
        self.scanning = True

        def work():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                results = loop.run_until_complete(
                    pyatv.scan(loop, timeout=4, protocol=Protocol.RAOP))
                loop.close()
                devs = []
                for cfg in results:
                    svc = cfg.get_service(Protocol.RAOP)
                    if not svc:
                        continue
                    props = {str(k): str(v) for k, v in (svc.properties or {}).items()}
                    devs.append({
                        "name": cfg.name,
                        "host": str(cfg.address),
                        "port": int(svc.port),
                        "id": cfg.identifier,
                        "props": props,
                    })
                self.devices = devs
            except Exception as e:
                print("scan error:", e, file=sys.stderr)
            finally:
                self.scanning = False
                self.callback(self.devices)

        threading.Thread(target=work, daemon=True).start()


class DeviceCard(ttk.Frame):
    """One AirPlay device as a rich card row."""

    def __init__(self, parent, dev, app):
        super().__init__(parent, style="Card.TFrame")
        self.app = app
        self.dev = dev
        self.key = f"{dev['host']}:{dev['port']}"
        self.streaming = False

        left = ttk.Frame(self, style="Card.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=8)

        head = ttk.Frame(left, style="Card.TFrame")
        head.pack(fill="x")
        self.dot = tk.Canvas(head, width=10, height=10, highlightthickness=0,
                             bg=app.C["card"])
        self.dot.pack(side="left", padx=(0, 8))
        self.dot_dot = self.dot.create_oval(2, 2, 8, 8, fill=app.C["fg_dim"], outline="")
        self.name_lbl = ttk.Label(head, text=dev["name"], style="CardTitle.TLabel")
        self.name_lbl.pack(side="left")
        self.model_lbl = ttk.Label(head, text=self._model_text(), style="Dim.TLabel")
        self.model_lbl.pack(side="left", padx=(8, 0))

        info = ttk.Frame(left, style="Card.TFrame")
        info.pack(fill="x", pady=(3, 0))
        self.addr_lbl = ttk.Label(info, text=f"{dev['host']}:{dev['port']}",
                                  style="Dim.TLabel")
        self.addr_lbl.pack(side="left")
        self.state_lbl = ttk.Label(info, text=tr(app.lang, "idle"),
                                   style="State.TLabel")
        self.state_lbl.pack(side="right")

        ctl = ttk.Frame(left, style="Card.TFrame")
        ctl.pack(fill="x", pady=(6, 0))
        ttk.Label(ctl, text=tr(app.lang, "volume"), style="Dim.TLabel").pack(side="left")
        self.vol_var = tk.IntVar(value=50)
        self.vol_scale = ttk.Scale(ctl, from_=0, to=100, variable=self.vol_var,
                                   style="Slim.Horizontal.TScale", length=130,
                                   command=self._on_vol)
        self.vol_scale.pack(side="left", padx=(6, 6))
        self.vol_lbl = ttk.Label(ctl, text="50", style="Dim.TLabel", width=3)
        self.vol_lbl.pack(side="left")

        ttk.Label(ctl, text=tr(app.lang, "extra_lat"), style="Dim.TLabel").pack(
            side="left", padx=(14, 0))
        self.lat_var = tk.IntVar(value=0)
        self.lat_scale = ttk.Scale(ctl, from_=0, to=1000, variable=self.lat_var,
                                   style="Slim.Horizontal.TScale", length=110,
                                   command=self._on_lat)
        self.lat_scale.pack(side="left", padx=(6, 6))
        self.lat_lbl = ttk.Label(ctl, text="0ms", style="Dim.TLabel", width=6)
        self.lat_lbl.pack(side="left")

        right = ttk.Frame(self, style="Card.TFrame")
        right.pack(side="right", fill="y", padx=(6, 12), pady=8)
        self.toggle_btn = tk.Button(
            right, text="▶", font=("Segoe UI", 14, "bold"),
            width=3, relief="flat", cursor="hand2",
            bg=app.C["btn2"], fg=app.C["accent"],
            activebackground=app.C["card_active"], activeforeground=app.C["accent"],
            bd=0, command=self.toggle)
        self.toggle_btn.pack(expand=True, fill="both")

    def _model_text(self):
        am = self.dev.get("props", {}).get("am", "")
        return {"AudioAccessory5,1": "HomePod mini",
                "AudioAccessory1,1": "HomePod"}.get(am, am)

    def set_state(self, text, color):
        self.state_lbl.configure(text=text, foreground=color)

    def set_dot(self, color):
        self.dot.itemconfig(self.dot_dot, fill=color)

    def set_streaming(self, on):
        self.streaming = on
        if on:
            self.toggle_btn.configure(text="■", fg=self.app.C["accent_err"])
            self.configure(style="CardActive.TFrame")
            self.set_dot(self.app.C["accent_ok"])
        else:
            self.toggle_btn.configure(text="▶", fg=self.app.C["accent"])
            self.configure(style="Card.TFrame")
            self.set_dot(self.app.C["fg_dim"])

    def _on_vol(self, val):
        v = int(float(val))
        self.vol_lbl.configure(text=str(v))
        if self.key in self.app.senders:
            self.app.senders[self.key].set_volume(v)

    def _on_lat(self, val):
        v = int(float(val))
        self.lat_lbl.configure(text=f"{v}ms")

    def toggle(self):
        self.app.toggle_device(self)


class AirHomeCasterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_TITLE} {APP_VERSION}")
        # window icon: use the project logo when available
        try:
            from PIL import Image as _PILImage
            _logo = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 os.pardir, "logo_256.png")
            _img = _PILImage.open(_logo)
            root.iconphoto(True, tk.PhotoImage(
                master=root, file=os.path.abspath(_logo)))
        except Exception:
            pass
        # config-first bootstrap for lang/theme
        cfg = {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
        self.cfg = cfg
        self.lang = cfg.get("lang", "zh")
        self.theme = cfg.get("theme", "dark")
        self.C = DARK_COLORS if self.theme == "dark" else LIGHT_COLORS

        self.one_click = cfg.get("one_click", True)
        self.idle_minutes = int(cfg.get("idle_minutes", 10))
        self.autodb = bool(cfg.get("autodb", True))
        self.min_to_tray = bool(cfg.get("min_to_tray", True))

        self.engine = AudioEngine()
        self.senders = {}
        self.cards = {}
        self.scanner = DeviceScanner(self._on_scan_done)
        self.ui_queue = queue_mod.Queue()
        self.auto_restart = True
        self.latency_profile = tk.StringVar()
        self._reconnect_jobs = {}
        self._death_counts = {}          # per-device consecutive stream deaths
        self._last_underrun_check = 0.0
        self.classifier = DBClassifier()
        self.last_audio_ts = None
        self.idle_kicked = False
        self.tray = Tray(self)

        # ---- v2.1 Windows integration ----
        self.mute_while_stream = bool(cfg.get("mute_while_stream", False))
        self.limiter_on = bool(cfg.get("limiter", True))
        self.engine.enable_limiter(self.limiter_on)
        self.endpoint_mute = EndpointMute()
        self._single = SingleInstance()
        if not self._single.acquire():
            # another copy already owns the audio capture — refuse to start
            self.root.after(200, lambda: self._exit_for_duplicate())
            return
        self.power_watcher = PowerWatcher(
            on_suspend=self._on_system_suspend,
            on_resume=self._on_system_resume,
        )
        self.power_watcher.start()

        self._setup_style()
        self._build_menu()
        self._build_ui()
        self._build_eq(self.root)
        self._load_config_into_ui()
        self.refresh_devices()
        self._pump_ui_queue()
        self._tick_meter()
        self._tick_idle()
        self._tick_status()
        self._tick_watchdog()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tray.start()

    # ------------- helpers -------------
    def tr(self, key):
        return tr(self.lang, key)

    def _exit_for_duplicate(self):
        try:
            messagebox.showwarning(APP_TITLE, self.tr("another_instance"))
        except Exception:
            pass
        self.root.destroy()
        os._exit(0)

    def log_line(self, s):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{ts}] {s}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------- style -------------
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        C = self.C
        style.configure(".", background=C["bg"], foreground=C["fg"])
        style.configure("TFrame", background=C["bg"])
        style.configure("Card.TFrame", background=C["card"])
        style.configure("CardActive.TFrame", background=C["card_active"])
        style.configure("Panel.TFrame", background=C["panel"])
        style.configure("TLabel", background=C["bg"], foreground=C["fg"])
        style.configure("CardTitle.TLabel", background=C["card"], foreground=C["fg"],
                        font=("Segoe UI", 11, "bold"))
        style.configure("Dim.TLabel", background=C["card"], foreground=C["fg_dim"],
                        font=("Segoe UI", 9))
        style.configure("State.TLabel", background=C["card"], foreground=C["fg_dim"],
                        font=("Segoe UI", 9))
        style.configure("H1.TLabel", background=C["bg"], foreground=C["fg"],
                        font=("Segoe UI Semibold", 15))
        style.configure("H2.TLabel", background=C["bg"], foreground=C["fg_dim"],
                        font=("Segoe UI", 10))
        style.configure("PanelH2.TLabel", background=C["panel"], foreground=C["fg_dim"],
                        font=("Segoe UI", 10))
        style.configure("TButton", background=C["panel"], foreground=C["fg"],
                        borderwidth=0, padding=6)
        style.map("TButton", background=[("active", C["card_active"])])
        style.configure("Accent.TButton", background=C["accent"],
                        foreground=C["accent_fg"], borderwidth=0, padding=(10, 6))
        style.configure("Slim.Horizontal.TScale", background=C["card"],
                        troughcolor=C["entry_bg"], borderwidth=0)
        style.configure("Horizontal.TProgressbar", background=C["accent"],
                        troughcolor=C["entry_bg"], borderwidth=0, thickness=6)

    # ------------- menu -------------
    def _build_menu(self):
        C = self.C
        m = tk.Menu(self.root, bg=C["panel"], fg=C["fg"],
                    activebackground=C["card_active"], activeforeground=C["fg"])
        self.root.config(menu=m)
        m_dev = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["fg"])
        m_dev.add_command(label=self.tr("menu_rescan"), command=self.refresh_devices)
        m_dev.add_separator()
        m_dev.add_command(label=self.tr("menu_exit"), command=self.on_close)
        m.add_cascade(label=self.tr("menu_devices"), menu=m_dev)
        m_audio = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["fg"])
        m_audio.add_command(label=self.tr("menu_pick_capture"),
                            command=self.pick_capture_device)
        m_audio.add_command(label=self.tr("menu_reinit"), command=self.reinit_engine)
        m.add_cascade(label=self.tr("menu_audio"), menu=m_audio)
        m_set = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["fg"])
        m_set.add_command(label=self.tr("menu_settings"), command=self.open_settings)
        m.add_cascade(label=self.tr("menu_settings"), menu=m_set)
        m_help = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["fg"])
        m_help.add_command(label=self.tr("menu_about"), command=self._about)
        m.add_cascade(label=self.tr("menu_help"), menu=m_help)

    # ------------- UI -------------
    def _build_ui(self):
        C = self.C
        self.root.configure(bg=C["bg"])
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(12, 6))
        ttk.Label(header, text=APP_TITLE, style="H1.TLabel").pack(side="left")
        self.sub_lbl = ttk.Label(header, text=f"v{APP_VERSION} · {self.tr('app_sub')}",
                                 style="H2.TLabel")
        self.sub_lbl.pack(side="left", padx=(10, 0), pady=(3, 0))
        self.scan_btn = ttk.Button(header, text=self.tr("scan"),
                                   style="Accent.TButton", command=self.refresh_devices)
        self.scan_btn.pack(side="right")
        self.spin_lbl = ttk.Label(header, text="", style="H2.TLabel")
        self.spin_lbl.pack(side="right", padx=(0, 10))

        master = ttk.Frame(self.root, style="Panel.TFrame")
        master.pack(fill="x", padx=16, pady=4)
        inner = ttk.Frame(master, style="Panel.TFrame")
        inner.pack(fill="x", padx=12, pady=10)

        self.master_btn = tk.Button(
            inner, text=self.tr("start_stream"), font=("Segoe UI", 11, "bold"),
            relief="flat", cursor="hand2", bd=0, padx=18, pady=6,
            bg=C["accent"], fg=C["accent_fg"],
            activebackground=C["card_active"], activeforeground=C["accent_fg"],
            command=self.toggle_stream)
        self.master_btn.pack(side="left")

        self.master_vol_lbl = ttk.Label(inner, text=self.tr("master_vol"),
                                        style="PanelH2.TLabel")
        self.master_vol_lbl.pack(side="left", padx=(16, 6))
        self.master_vol = tk.DoubleVar(value=100.0)
        ttk.Scale(inner, from_=0, to=150, variable=self.master_vol, length=160,
                  command=self.on_master_vol).pack(side="left")
        self.vol_lbl = ttk.Label(inner, text="100%", style="PanelH2.TLabel", width=5)
        self.vol_lbl.pack(side="left")

        self.input_lbl = ttk.Label(inner, text=self.tr("input"),
                                   style="PanelH2.TLabel")
        self.input_lbl.pack(side="left", padx=(18, 6))
        self.meter = ttk.Progressbar(inner, mode="determinate", length=130, maximum=100)
        self.meter.pack(side="left")

        row2 = ttk.Frame(self.root, style="Panel.TFrame")
        row2.pack(fill="x", padx=16, pady=(0, 6))
        inner2 = ttk.Frame(row2, style="Panel.TFrame")
        inner2.pack(fill="x", padx=12, pady=(0, 10))
        self.capture_lbl = ttk.Label(inner2, text=self.tr("capture_default"),
                                     style="PanelH2.TLabel")
        self.capture_lbl.pack(side="left")
        ttk.Button(inner2, text=self.tr("change"),
                   command=self.pick_capture_device).pack(side="left", padx=(8, 0))

        self.db_lbl = ttk.Label(inner2, text="", style="PanelH2.TLabel")
        self.db_lbl.pack(side="left", padx=(18, 0))
        self.db_mode_var = tk.StringVar()
        self.db_cb = ttk.Combobox(inner2, textvariable=self.db_mode_var,
                                  state="readonly", width=10,
                                  values=self._db_mode_values())
        self.db_cb.pack(side="left", padx=(8, 0))
        self.db_cb.bind("<<ComboboxSelected>>", self.on_db_mode_change)

        self.lat_mode_lbl = ttk.Label(inner2, text=self.tr("latency_mode"),
                                      style="PanelH2.TLabel")
        self.lat_mode_lbl.pack(side="right")
        self.profile_cb = ttk.Combobox(inner2, textvariable=self.latency_profile,
                                       state="readonly", width=20,
                                       values=self._latency_values())
        self.profile_cb.pack(side="right", padx=(6, 0))
        self.profile_cb.bind("<<ComboboxSelected>>", self.on_profile_change)

        self.cards_frame = ttk.Frame(self.root)
        self.cards_frame.pack(fill="both", expand=True, padx=16, pady=6)
        self.empty_lbl = ttk.Label(self.cards_frame, text=self.tr("no_devices"),
                                   style="H2.TLabel", anchor="center")

        logf = ttk.Frame(self.root, style="Panel.TFrame")
        logf.pack(fill="x", padx=16, pady=(6, 0))
        self.log = tk.Text(logf, height=5, state="disabled", bd=0,
                           bg=C["entry_bg"], fg=C["fg_dim"],
                           font=("Consolas", 9), padx=8, pady=6)
        self.log.pack(fill="x")

        status = ttk.Frame(self.root)
        status.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value=self.tr("ready"))
        ttk.Label(status, textvariable=self.status_var, style="H2.TLabel").pack(
            side="left", padx=12, pady=4)

        self.root.bind("<F5>", lambda e: self.refresh_devices())
        self.root.bind("<space>", self._space_toggle)

    def _build_eq(self, parent):
        C = self.C
        self.eqf = ttk.LabelFrame(parent, text=self.tr("eq_title"), padding=8)
        self.eqf.pack(fill="x", padx=16, pady=4)
        self.eq_vars = []
        for i, f in enumerate(EQ_BANDS):
            col = ttk.Frame(self.eqf)
            col.grid(row=0, column=i, padx=3)
            v = tk.DoubleVar(value=0.0)
            self.eq_vars.append(v)
            ttk.Scale(col, from_=12, to=-12, variable=v, length=76,
                      command=lambda _x, idx=i: self.on_eq_change(idx)).pack()
            ttk.Label(col, text=f"{f}", style="H2.TLabel").pack()
        btns = ttk.Frame(self.eqf)
        btns.grid(row=0, column=10, padx=8, sticky="n")
        ttk.Button(btns, text=self.tr("reset"),
                   command=self.reset_eq).pack(fill="x")
        ttk.Button(btns, text=self.tr("eq_export"), width=14,
                   command=self.export_eq).pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text=self.tr("eq_import"), width=14,
                   command=self.import_eq).pack(fill="x", pady=(4, 0))

    # ------------- EQ preset export/import -------------
    def export_eq(self):
        from tkinter import filedialog as _fd
        path = _fd.asksaveasfilename(
            defaultextension=".aceq",
            filetypes=[("AirHomeCaster EQ preset", "*.aceq"), ("JSON", "*.json")])
        if not path:
            return
        try:
            data = {
                "type": "AirHomeCaster-eq",
                "version": 1,
                "bands": EQ_BANDS,
                "gains": [round(float(v.get()), 2) for v in self.eq_vars],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log_line(self.tr("eq_saved").format(os.path.basename(path)))
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def import_eq(self):
        from tkinter import filedialog as _fd
        path = _fd.askopenfilename(
            filetypes=[("AirHomeCaster EQ preset", "*.aceq"), ("JSON", "*.json"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            gains = data.get("gains") if isinstance(data, dict) else data
            if not isinstance(gains, list) or not gains:
                raise ValueError("no gains array")
            gains = [float(g) for g in gains[:len(self.eq_vars)]]
            while len(gains) < len(self.eq_vars):
                gains.append(0.0)
            gains = [max(-12.0, min(12.0, g)) for g in gains]
            for v, g in zip(self.eq_vars, gains):
                v.set(g)
            self.engine.set_eq_gains(gains)
            self.log_line(self.tr("eq_loaded").format(os.path.basename(path)))
        except Exception as e:
            messagebox.showerror(APP_TITLE, self.tr("eq_load_fail").format(e))

    # ------------- scan/cards -------------
    def set_status(self, s):
        self.status_var.set(s)

    def refresh_devices(self):
        self.set_status(self.tr("scanning"))
        self.spin_lbl.configure(text=self.tr("scanning"))
        self.scanner.scan()

    def _on_scan_done(self, devices):
        self.ui_queue.put(("scan", devices))

    def _apply_scan(self, devices):
        self.spin_lbl.configure(text="")
        keep = set()
        for d in devices:
            key = f"{d['host']}:{d['port']}"
            keep.add(key)
            if key not in self.cards:
                card = DeviceCard(self.cards_frame, d, self)
                card.pack(fill="x", pady=4)
                self.cards[key] = card
                if key in self.senders:
                    card.set_streaming(True)
            else:
                self.cards[key].dev = d
        for key in list(self.cards):
            if key not in keep:
                if key in self.senders:
                    self._stop_sender(key)
                self.cards[key].destroy()
                del self.cards[key]
        if not devices:
            self.empty_lbl.pack(fill="both", expand=True)
        else:
            self.empty_lbl.pack_forget()
        self.set_status(
            self.tr("devices_found").format(len(devices))
            + " · " + (self.engine.device_name or self.tr("capture_default")))

    def update_capture_label(self):
        self.capture_lbl.configure(
            text=(self.engine.device_name or self.tr("capture_default")))

    # ------------- streaming -------------
    def toggle_device(self, card):
        key = card.key
        if key in self.senders:
            self._stop_sender(key)
            card.set_streaming(False)
            card.set_state(self.tr("idle"), self.C["fg_dim"])
        else:
            self._start_sender(key, card, then_stream=self.one_click)

    def _start_sender(self, key, card, then_stream=False):
        d = card.dev
        profile_base = LATENCY_PROFILES[self._profile_key()][2]
        s = RaopSender(
            d["name"], d["host"], d["port"],
            volume=card.vol_var.get(),
            latency_ms=card.lat_var.get(),
            props=d.get("props"),
            base_latency_ms=profile_base,
        )
        s.on_stream_died = lambda snd, k=key: self._on_stream_died(k, snd)
        card.set_state(self.tr("connecting"), self.C["accent_warn"])
        self.log_line(self.tr("conn_to").format(d["name"], d["host"], d["port"], profile_base))
        self.senders[key] = s

        def worker():
            ok = s.start()
            self.ui_queue.put(("sender_started", key, ok, s, then_stream))

        threading.Thread(target=worker, daemon=True).start()

    def _sender_started(self, key, ok, s, then_stream=False):
        card = self.cards.get(key)
        if not card:
            if key in self.senders and self.senders[key] is s:
                del self.senders[key]
            return
        if ok:
            card.set_streaming(True)
            card.set_state(self.tr("connected"), self.C["accent_ok"])
            self.log_line(self.tr("conn_ok").format(s.name))
            # successful connect clears the instability counter only when the
            # stream has actually run for a while (checked in _tick_watchdog)
            jid = self._reconnect_jobs.pop(key, None)
            if jid:
                self.root.after_cancel(jid)
            self._schedule_status()
            if then_stream and not self.engine.running:
                self.toggle_stream()
                self.log_line(self.tr("one_click_hint"))
        else:
            card.set_state(
                f"{self.tr('failed')}: {(s.stats['last_error'] or '')[:32]}",
                self.C["accent_err"])
            self.log_line(self.tr("conn_fail").format(s.name, s.stats["last_error"]))
            if self.senders.get(key) is s:
                del self.senders[key]
            self._schedule_auto_reconnect(key, card, delay=3000, attempt=1)

    def _stop_sender(self, key):
        s = self.senders.pop(key, None)
        job = self._reconnect_jobs.pop(key, None)
        if job:
            self.root.after_cancel(job)
        if s:
            s._stop_requested = True   # don't treat this as a stream death
            try:
                s.stop()
            except Exception:
                pass
            self.log_line(self.tr("disc").format(s.name))
        self._schedule_status()

    # ------------- stream-death watchdog -------------
    def _on_stream_died(self, key, sender):
        """pyatv's send loop exited mid-stream (network hiccup, device reboot,
        underrun spiral). Queue an automatic reconnect on the UI thread."""
        if sender._stop_requested:
            return  # user intentionally stopped; nothing to do
        self.ui_queue.put(("stream_died", key, sender))

    def _apply_stream_died(self, key, sender):
        card = self.cards.get(key)
        if not card or self.senders.get(key) is not sender:
            return  # already replaced/stopped
        self.log_line(self.tr("conn_fail").format(
            sender.name, sender.stats.get("last_error") or "stream ended"))
        # how many deaths in a row at this latency? auto-relax if unstable
        self._death_counts[key] = self._death_counts.get(key, 0) + 1
        if self._death_counts[key] >= 2 and self._profile_key() in ("insane", "ultra"):
            self._relax_profile()
        # clean the dead sender out, then reconnect with backoff
        self.senders.pop(key, None)
        card.set_state(self.tr("connecting"), self.C["accent_warn"])
        delay = min(3000 * self._death_counts[key], 15000)
        self._schedule_auto_reconnect(key, card, delay=delay,
                                      attempt=self._death_counts[key])

    def _relax_profile(self):
        """15/20ms keeps dying -> step up to low latency and tell the user."""
        key = self._profile_key()
        if key == "insane":
            new = "ultra"
        elif key == "ultra":
            new = "low"
        else:
            return
        self.latency_profile.set(
            LATENCY_PROFILES[new][self._lang_idx()])
        self.log_line(self.tr("stability_relax").format(
            LATENCY_PROFILES[new][self._lang_idx()]))
        self.set_status(self.tr("stability_relax").format(
            LATENCY_PROFILES[new][self._lang_idx()]))
        self._save_config()

    def _schedule_status(self):
        n = len(self.senders)
        if n and not self.engine.running:
            self.set_status(self.tr("n_ready").format(n))
        elif n and self.engine.running:
            self.set_status(self.tr("streaming_n").format(n))
        else:
            self.set_status(self.tr("ready"))

    def _schedule_auto_reconnect(self, key, card, delay=4000, attempt=1):
        if not self.auto_restart or attempt > 5:
            return
        card.set_state(self.tr("auto_reconnect").format(attempt), self.C["accent_warn"])
        jid = self.root.after(delay, lambda: self._try_reconnect(key, card))
        self._reconnect_jobs[key] = jid

    def _try_reconnect(self, key, card):
        if key in self.senders:
            return
        self._start_sender(key, card, then_stream=False)

    def toggle_stream(self):
        if not self.senders:
            messagebox.showinfo(APP_TITLE, self.tr("need_device"))
            return
        if not self.engine.running:
            self.engine.set_eq_gains([v.get() for v in self.eq_vars])
            self.engine.gain = self.master_vol.get() / 100.0
            self.engine.add_subscriber(self._dispatch)
            self.engine.start()
            if self.mute_while_stream:
                self.endpoint_mute.mute()
            self.master_btn.configure(text=self.tr("stop_stream"),
                                      bg=self.C["accent_err"], fg="#ffffff")
            self.last_audio_ts = None
            self.idle_kicked = False
            self.log_line(self.tr("stream_start"))
        else:
            self.engine.stop()
            if self.endpoint_mute.active:
                self.endpoint_mute.restore()
            self.master_btn.configure(text=self.tr("start_stream"),
                                      bg=self.C["accent"], fg=self.C["accent_fg"])
            self.log_line(self.tr("stream_stop"))
        self._schedule_status()

    def _dispatch(self, ints):
        data = ints.tobytes()
        self.last_audio_ts = time.time()
        if self.autodb:
            label = self.classifier.feed(ints.astype(np.float32) / 32768.0, 44100)
            if label:
                self._apply_db_preset(label)
        for s in list(self.senders.values()):
            s.push_chunk(data)

    def _apply_db_preset(self, label, force=False):
        preset = EQ_PRESETS.get(label)
        if not preset:
            return
        if force:
            # manual selection: snap all bands at once
            for v, g in zip(self.eq_vars, preset):
                v.set(g)
            self.engine.set_eq_gains(list(preset))
        elif not self.autodb:
            return  # manual EQ mode: classifier stays off
        else:
            cur = [v.get() for v in self.eq_vars]
            if any(abs(a - b) > 0.5 for a, b in zip(cur, preset)):
                for v, g in zip(self.eq_vars, preset):
                    v.set(g)
                self.engine.set_eq_gains(list(preset))
        name_key = {"music": "db_music", "meeting": "db_meeting", "movie": "db_movie"}.get(label)
        if name_key:
            self.db_lbl.configure(text=f"dB: {self.tr(name_key)}")
            self.set_status(self.tr("db_detect").format(self.tr(name_key)))

    def on_master_vol(self, val):
        v = float(val)
        self.vol_lbl.configure(text=f"{v:.0f}%")
        self.engine.gain = v / 100.0

    def on_profile_change(self, event=None):
        key = self._profile_key()
        self.log_line(self.tr("latency_applied").format(
            LATENCY_PROFILES[key][0] if self.lang == "zh" else LATENCY_PROFILES[key][1]))
        self._save_config()

    # ------------- dB mode selector -------------
    DB_MODES = ("auto", "music", "meeting", "movie", "off")

    def _latency_values(self):
        return [LATENCY_PROFILES[k][self._lang_idx()] for k in
                ("insane", "ultra", "low", "balanced", "stable")]

    def _db_mode_values(self):
        return (self.tr("db_auto"),
                self.tr("db_music"),
                self.tr("db_meeting"),
                self.tr("db_movie"),
                self.tr("db_off"))

    def _db_mode_index(self):
        if self.autodb:
            return 0
        preset = getattr(self, "db_manual", None)
        if preset in ("music", "meeting", "movie"):
            return self.DB_MODES.index(preset)
        return 4  # off

    def on_db_mode_change(self, event=None):
        idx = self.db_cb.current()
        mode = self.DB_MODES[min(idx, len(self.DB_MODES) - 1)]
        self.autodb = (mode == "auto")
        if mode in ("music", "meeting", "movie"):
            self.db_manual = mode
            self._apply_db_preset(mode, force=True)
        elif mode == "off":
            self.db_manual = None
            self.db_lbl.configure(text="")
            self.engine.set_eq_gains([v.get() for v in self.eq_vars])
            self.set_status(self.tr("db_off"))
        self._save_config()

    def _profile_key(self):
        val = self.latency_profile.get()
        for k, (en, zh, _) in LATENCY_PROFILES.items():
            if val in (en, zh):
                return k
        return "ultra"

    # ------------- EQ -------------
    def on_eq_change(self, idx):
        if self.engine.running:
            self.engine.set_eq_gains([v.get() for v in self.eq_vars])

    def reset_eq(self):
        for v in self.eq_vars:
            v.set(0.0)
        self.engine.clear_eq()
        self.log_line(self.tr("eq_reset"))

    # ------------- capture device -------------
    def pick_capture_device(self):
        devs = list_output_devices()
        w = tk.Toplevel(self.root)
        w.title(self.tr("menu_pick_capture"))
        w.transient(self.root)
        w.grab_set()
        w.configure(bg=self.C["bg"])
        ttk.Label(w, text=self.tr("pick_capture_hint"), style="H2.TLabel").pack(
            padx=14, pady=(12, 8))
        lb = tk.Listbox(w, width=64, height=10, bd=0, highlightthickness=0,
                        bg=self.C["entry_bg"], fg=self.C["fg"],
                        selectbackground=self.C["accent"], font=("Segoe UI", 10))
        lb.pack(padx=14, pady=(0, 8))
        names = [self.tr("capture_default")] + [d["name"] for d in devs]
        for n in names:
            lb.insert("end", n)
        lb.selection_set(0)

        def ok():
            sel = lb.curselection()
            if sel and sel[0] > 0:
                self.engine.mic_id = devs[sel[0] - 1]["id"]
                self.log_line(self.tr("capture_set").format(devs[sel[0] - 1]["name"]))
            else:
                self.engine.mic_id = None
                self.log_line(self.tr("capture_default_log"))
            if self.engine.running:
                self.engine.stop()
                self.engine.start()
            self.update_capture_label()
            w.destroy()

        ttk.Button(w, text=self.tr("apply"), style="Accent.TButton",
                   command=ok).pack(pady=(0, 12))
        lb.bind("<Double-1>", lambda e: ok())
        lb.bind("<Return>", lambda e: ok())
        lb.focus_set()

    def reinit_engine(self):
        was = self.engine.running
        if was:
            self.engine.stop()
        self.engine = AudioEngine()
        self.engine.gain = self.master_vol.get() / 100.0
        self.engine.set_eq_gains([v.get() for v in self.eq_vars])
        if was:
            self.engine.add_subscriber(self._dispatch)
            self.engine.start()
        self.update_capture_label()
        self.log_line(self.tr("reinit"))

    # ------------- meters / timers -------------
    def _tick_meter(self):
        lvl = self.engine.level if self.engine.running else 0.0
        self.meter.configure(value=min(100.0, lvl * 140))
        self.root.after(80, self._tick_meter)

    def _tick_status(self):
        for key, s in list(self.senders.items()):
            card = self.cards.get(key)
            if card and s.connected:
                card.set_state(self.tr("connected"), self.C["accent_ok"])
        self.root.after(2000, self._tick_status)

    def _tick_watchdog(self):
        """Stability watchdog every 5s: underrun warnings + survival credit.

        A sender that stays connected 30s earns its death counter reset, so
        one flaky moment doesn't permanently demote the latency profile.
        """
        now = time.time()
        for key, s in list(self.senders.items()):
            # underrun pressure indicator (2+ starves in the last check window)
            u = s.stats.get("underruns", 0)
            last_u = s.stats.get("_u_last", 0)
            if u - last_u >= 3:
                card = self.cards.get(key)
                if card and s.connected:
                    card.set_state(self.tr("starving"), self.C["accent_warn"])
            s.stats["_u_last"] = u
            # survival credit
            died_at = s.stats.get("stopped_at", 0)
            if s.connected and now - s._ready_time > 30:
                if self._death_counts.get(key, 0) > 0:
                    self._death_counts[key] = 0
        self.root.after(5000, self._tick_watchdog)

    def _tick_idle(self):
        if (self.engine.running and self.idle_minutes > 0
                and self.last_audio_ts is not None
                and time.time() - self.last_audio_ts > self.idle_minutes * 60):
            if not self.idle_kicked:
                self.idle_kicked = True
                for key in list(self.senders):
                    self._stop_sender(key)
                self.toggle_stream()
                self.log_line(self.tr("idle_kick").format(self.idle_minutes))
                self.set_status(self.tr("idle_kick").format(self.idle_minutes))
        self.root.after(10000, self._tick_idle)

    # ------------- sleep/resume self-healing -------------
    def _on_system_suspend(self):
        # runs on the PowerWatcher message thread — queue for the UI thread
        try:
            self.ui_queue.put(("suspend",))
        except Exception:
            pass

    def _on_system_resume(self):
        try:
            self.ui_queue.put(("resume",))
        except Exception:
            pass

    def _apply_suspend(self):
        self.log_line(self.tr("sleep_suspended"))
        self._was_streaming = self.engine.running
        for key in list(self.senders):
            s = self.senders.pop(key, None)
            if s:
                try:
                    s.stop()
                except Exception:
                    pass
        if self.engine.running:
            self.engine.stop()
        if self.endpoint_mute.active:
            self.endpoint_mute.restore()

    def _apply_resume(self):
        self.log_line(self.tr("sleep_resume"))
        try:
            was = getattr(self, "_was_streaming", False)
            self.engine = AudioEngine()
            self.engine.gain = self.master_vol.get() / 100.0
            self.engine.set_eq_gains([v.get() for v in self.eq_vars])
            self.engine.enable_limiter(self.limiter_on)
            self.engine.add_subscriber(self._dispatch)
            for key, card in list(self.cards.items()):
                card.set_state(self.tr("connecting"), self.C["accent_warn"])
                self._start_sender(key, card, then_stream=False)
            if was or self.senders:
                self.engine.start()
                if self.mute_while_stream:
                    self.endpoint_mute.mute()
            self.update_capture_label()
        except Exception as e:
            self.log_line(self.tr("resume_fail").format(e))

    def _pump_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "scan":
                    self._apply_scan(item[1])
                elif kind == "sender_started":
                    _, key, ok, s, then_stream = item
                    self._sender_started(key, ok, s, then_stream)
                elif kind == "suspend":
                    self._apply_suspend()
                elif kind == "resume":
                    self._apply_resume()
                elif kind == "stream_died":
                    _, key, sender = item
                    self._apply_stream_died(key, sender)
        except queue_mod.Empty:
            pass
        self.root.after(100, self._pump_ui_queue)

    # ------------- settings -------------
    def open_settings(self):
        w = tk.Toplevel(self.root)
        w.title(self.tr("settings_title"))
        w.transient(self.root)
        w.grab_set()
        w.configure(bg=self.C["bg"])
        w.geometry("480x420")

        pad = {"padx": 16, "pady": 6}
        lang_var = tk.StringVar(value=self.lang)
        theme_var = tk.StringVar(value=self.theme)
        autostart_var = tk.BooleanVar(value=Autostart.is_enabled())
        tray_var = tk.BooleanVar(value=self.min_to_tray)
        idle_var = tk.IntVar(value=self.idle_minutes)
        autodb_var = tk.BooleanVar(value=self.autodb)
        oneclick_var = tk.BooleanVar(value=self.one_click)
        mute_var = tk.BooleanVar(value=self.mute_while_stream)
        limiter_var = tk.BooleanVar(value=self.limiter_on)

        ttk.Label(w, text=self.tr("settings_lang"), style="H2.TLabel").grid(
            row=0, column=0, sticky="w", **pad)
        lang_cb = ttk.Combobox(w, textvariable=lang_var, state="readonly",
                               values=["zh", "en"], width=12)
        lang_cb.grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(w, text=self.tr("settings_theme"), style="H2.TLabel").grid(
            row=1, column=0, sticky="w", **pad)
        theme_cb = ttk.Combobox(w, textvariable=theme_var, state="readonly",
                                values=["dark", "light"], width=12)
        theme_cb.grid(row=1, column=1, sticky="w", **pad)

        ttk.Checkbutton(w, text=self.tr("settings_autostart"), variable=autostart_var).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(w, text=self.tr("settings_min_tray"), variable=tray_var).grid(
            row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(w, text=self.tr("settings_oneshot"), variable=oneclick_var).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(w, text=self.tr("settings_autodb"), variable=autodb_var).grid(
            row=5, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(w, text=self.tr("mute_while_stream"), variable=mute_var).grid(
            row=6, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(w, text=self.tr("limiter"), variable=limiter_var).grid(
            row=7, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(w, text=self.tr("settings_idle"), style="H2.TLabel").grid(
            row=8, column=0, sticky="w", **pad)
        idle_row = ttk.Frame(w)
        idle_row.grid(row=8, column=1, sticky="w", **pad)
        ttk.Spinbox(idle_row, from_=0, to=120, textvariable=idle_var, width=5).pack(
            side="left")
        ttk.Label(idle_row, text=self.tr("settings_idle_min"), style="H2.TLabel").pack(
            side="left", padx=(4, 0))

        def save():
            lang_changed = lang_var.get() != self.lang
            theme_changed = theme_var.get() != self.theme
            self.lang = lang_var.get()
            self.theme = theme_var.get()
            self.C = DARK_COLORS if self.theme == "dark" else LIGHT_COLORS
            self.min_to_tray = tray_var.get()
            self.one_click = oneclick_var.get()
            self.autodb = autodb_var.get()
            self.idle_minutes = max(0, int(idle_var.get() or 0))
            mute_changed = mute_var.get() != self.mute_while_stream
            self.mute_while_stream = mute_var.get()
            new_limiter = limiter_var.get()
            limiter_changed = new_limiter != self.limiter_on
            self.limiter_on = new_limiter
            self.engine.enable_limiter(self.limiter_on)
            # apply mute immediately if streaming state conflicts
            if self.mute_while_stream and self.engine.running and not self.endpoint_mute.active:
                self.endpoint_mute.mute()
            elif not self.mute_while_stream and self.endpoint_mute.active:
                self.endpoint_mute.restore()
            Autostart.set_enabled(autostart_var.get())
            self._save_config()
            if theme_changed or lang_changed:
                messagebox.showinfo(APP_TITLE, self.tr("lang_note"))
                self.root.destroy()   # restart to apply cleanly
                os.execl(sys.executable, sys.executable,
                         os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch.py"))
            w.destroy()

        ttk.Button(w, text=self.tr("settings_save"), style="Accent.TButton",
                   command=save).grid(row=9, column=0, columnspan=2, pady=16)

    def _space_toggle(self, event):
        self.toggle_stream()

    def _about(self):
        messagebox.showinfo(APP_TITLE, self.tr("about_text").format(APP_VERSION))

    # ------------- tray -------------
    def tray_show(self):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(),
                                    self.root.focus_force()))

    def tray_toggle_stream(self):
        self.root.after(0, self.toggle_stream)

    def tray_exit(self):
        self.root.after(0, self.on_close)

    # ------------- config -------------
    def _load_config_into_ui(self):
        cfg = self.cfg
        self.master_vol.set(cfg.get("master_vol", 100.0))
        self.on_master_vol(self.master_vol.get())
        eq = cfg.get("eq", [0.0] * len(EQ_BANDS))
        for v, g in zip(self.eq_vars, eq):
            v.set(g)
        profile = cfg.get("latency_profile", "ultra")
        if profile in LATENCY_PROFILES:
            self.latency_profile.set(LATENCY_PROFILES[profile][self._lang_idx()])
        else:
            # config from an older version: map legacy ultra=60 to the new 20ms
            self.latency_profile.set(LATENCY_PROFILES["ultra"][self._lang_idx()])
        # dB mode selector initial state
        self.db_manual = cfg.get("db_manual")
        self.db_cb.configure(values=self._db_mode_values())
        self.db_cb.current(self._db_mode_index())
        mic_id = cfg.get("mic_id")
        if mic_id:
            self.engine.mic_id = mic_id
        self.update_capture_label()

    def _lang_idx(self):
        return 0 if self.lang == "en" else 1

    def _save_config(self):
        try:
            cfg = {
                "master_vol": self.master_vol.get(),
                "eq": [v.get() for v in self.eq_vars],
                "auto_restart": self.auto_restart,
                "latency_profile": self._profile_key(),
                "mic_id": self.engine.mic_id,
                "lang": self.lang,
                "theme": self.theme,
                "min_to_tray": self.min_to_tray,
                "one_click": self.one_click,
                "autodb": self.autodb,
                "idle_minutes": self.idle_minutes,
                "mute_while_stream": self.mute_while_stream,
                "limiter": self.limiter_on,
                "db_manual": getattr(self, "db_manual", None),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_close(self):
        if self.min_to_tray and self.tray.icon and self.tray.icon.visible:
            self.root.withdraw()
            return
        self._save_config()
        try:
            self.engine.stop()
        except Exception:
            pass
        if self.endpoint_mute.active:
            self.endpoint_mute.restore()
        for key in list(self.senders):
            self._stop_sender(key)
        try:
            self.tray.stop()
        except Exception:
        	pass
        try:
            self.power_watcher.stop()
        except Exception:
        	pass
        if self._single:
            self._single.release()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            pass  # clam keeps dark styling predictable
    except Exception:
        pass
    AirHomeCasterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
