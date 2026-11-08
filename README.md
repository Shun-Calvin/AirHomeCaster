# AirHomeCaster

![AirHomeCaster](logo.png)

**AirHomeCaster** streams Windows system audio to AirPlay devices on your local
network — HomePod / HomePod mini, Apple TV, Sonos, AirPort Express and other
RAOP-compatible speakers. Multi-device casting, 10-band equalizer, ultra-low
latency, all in one lightweight Python app.

## Features

- **System-wide audio capture** via WASAPI loopback — whatever your PC plays,
  your AirPlay speakers play
- **Ultra-low latency**: down to 15–20 ms on a healthy LAN
- **Multi-device** — cast to several AirPlay speakers at once, each with its
  own volume and extra-delay control
- **10-band equalizer** with presets (Music / Meeting / Movie), manual mode,
  and preset export/import (`.aceq` files)
- **Auto dB mode** — classifies content (music / speech / movie) from the
  spectrum and applies a matching EQ automatically
- **Anti-clip limiter** — soft-knee limiting keeps boosted EQ and >100% master
  gain free of distortion
- **Mute local speakers while casting** — your PC stays silent while the
  speakers play (optional)
- **Sleep / resume self-healing** — reconnects automatically after suspend
- **Stream watchdog** — detects mid-stream dropouts and reconnects with
  backoff; if an ultra-low latency profile keeps failing, it relaxes
  automatically to keep the music playing
- **Single-instance guard** — a second copy politely refuses to start
- **Idle auto-disconnect** — configurable; frees the AirPlay device when you
  stop playing
- **System tray**, **Windows autostart**, **dark / light theme**,
  **English / 繁體中文** interface
- **One-click connect + stream**

## Requirements

- Windows 10 2004+ / Windows 11
- Python 3.9+ with tkinter (the standard python.org installer or Anaconda)
- All devices on the same local network

Python dependencies:

```
pip install pyatv soundcard scipy numpy pycaw comtypes pystray pillow
```

## Usage

1. Double-click `run.bat` (or `python launch.py`)
2. Click **Scan Devices** — your AirPlay speakers appear as cards
3. Press **▶** on a card: it connects and starts streaming in one click
4. Tune volume, per-device extra delay, latency profile and EQ from the main
   window

Latency profiles: 瘋狂 15 ms → 極速 20 ms → 低延遲 250 ms → 平衡 600 ms →
穩定 1200 ms. Start with 低延遲 (250 ms) and work your way down; on Wi-Fi the
15–20 ms profiles can drop out under jitter — the watchdog will warn you and
automatically relax to a stable profile if needed.

## How it works

AirHomeCaster captures the default render endpoint with WASAPI loopback,
applies EQ / gain / limiter, resamples 48 kHz → 44.1 kHz with a
phase-continuous streaming polyphase resampler, and sends PCM as AirPlay v1
(RAOP) using the [pyatv](https://github.com/postlund/pyatv) library's
protocol internals.

## Disclaimer

This software is provided **"AS IS", WITHOUT WARRANTY OF ANY KIND**, express
or implied. See [DISCLAIMER.md](DISCLAIMER.md) and the
[MIT License](LICENSE) for the full terms.

AirPlay, HomePod, Apple TV, AirPort Express and Sonos are trademarks of their
respective owners. AirHomeCaster is an independent open-source project and is
not affiliated with, endorsed by, or connected to Apple Inc. or Sonos Inc. in
any way. Users are responsible for complying with the terms of service of any
devices and networks they use this software with. Do not use AirHomeCaster to
capture or redistribute content in violation of any license, subscription
agreement or applicable law.

## License

MIT — see [LICENSE](LICENSE).
