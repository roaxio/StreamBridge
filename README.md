<h1 align="center">StreamBridge</h1>

<p align="center"><em>Turn your phone's camera and mic streams (e.g. EZ-Cam) into a real webcam and microphone on Windows, Linux, and macOS.</em></p>

<p align="center">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Platforms" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10--3.13-blue.svg">
</p>

<p align="center">
  <a href="#quick-overview"><strong>Overview</strong></a> ·
  <a href="#platform-requirements"><strong>Requirements</strong></a> ·
  <a href="#download"><strong>Download</strong></a> ·
  <a href="#running-from-source"><strong>Source Setup</strong></a> ·
  <a href="#features--usage"><strong>Usage</strong></a> ·
  <a href="#development"><strong>Development</strong></a> ·
  <a href="docs/ARCHITECTURE.md"><strong>Architecture</strong></a>
</p>

---

## Quick Overview

StreamBridge connects to video and audio streams broadcast by your mobile phone (such as EZ-Cam, IP Webcam, or RTSP apps) and outputs them directly to standard virtual devices. Apps like **Zoom, Microsoft Teams, Discord, OBS Studio**, or browser meetings recognize StreamBridge immediately as physical hardware.

```text
Video URL:  http://192.168.1.5:8080/video        (or just 192.168.1.5:8080/video)
Audio URL:  https://10.0.2.16:4747/audio.wav      ("Same phone" auto-fills from video)
Login:      optional (e.g. user / pass or https://user:pass@10.0.2.16:4747/video)
```

---

## Platform Requirements

StreamBridge uses standard virtual video/audio loopback devices. It **never installs drivers behind your back**; on first run, the built-in **Welcome / Setup check** detects installed devices and links directly to official driver installers:

| Platform | Virtual Camera | Virtual Microphone | Required Driver / Setup (One-Time) |
| :--- | :--- | :--- | :--- |
| **Windows** | OBS Virtual Camera | CABLE Output | [OBS Studio 26+](https://obsproject.com/download) · [VB-CABLE](https://vb-audio.com/Cable/) |
| **Linux** | StreamBridge Camera | StreamBridge Microphone | `v4l2loopback` (package) · PipeWire / PulseAudio |
| **macOS** | OBS Virtual Camera | BlackHole 2ch | [OBS Studio 26+](https://obsproject.com/download) · [BlackHole 2ch](https://existential.audio/blackhole/) |

> [!TIP]
> **Use only what you need:** Camera-only streaming requires only the camera driver; microphone-only streaming requires only the audio driver.

---

## Download

Pre-built standalone releases (no Python installation required) are published on the [Releases](https://github.com/roaxio/StreamBridge/releases) page:

| OS / Architecture | Package | How to Launch |
| :--- | :--- | :--- |
| **Windows (x64)** | `StreamBridge-vX.Y.Z-windows-x64.zip` | Unzip and launch `StreamBridge.exe` |
| **macOS (arm64)** | `StreamBridge-vX.Y.Z-macos-arm64.zip` | Move to Applications and open `StreamBridge.app` |
| **Linux (x64)** | `StreamBridge-vX.Y.Z-linux-x64.tar.gz` | Extract and run `./start-streambridge.sh` |

### Verifying Release Integrity
Release assets include free cryptographic build provenance attestations from GitHub Actions:
```bash
# Verify GitHub build provenance attestation
gh attestation verify StreamBridge-vX.Y.Z-windows-x64.zip --repo roaxio/StreamBridge
```

> [!NOTE]
> **Unsigned Release Notice:**
> - **Windows SmartScreen:** Click *More info* → *Run anyway*.
> - **macOS Gatekeeper:** Right-click `StreamBridge.app` → *Open* → *Open*, or run:
>   ```bash
>   xattr -dr com.apple.quarantine StreamBridge.app
>   ```

---

## Running from Source

### Windows
1. **Camera:** Install [OBS Studio](https://obsproject.com/download). Launch OBS once, click *Start Virtual Camera*, then *Stop*. (OBS does not need to stay open after this and can be closed; StreamBridge connects directly to the registered virtual camera driver).
2. **Microphone:** Install [VB-CABLE](https://vb-audio.com/Cable/) as Administrator and reboot.
3. In meeting apps (Zoom, Discord, Teams), select:
   - Camera: **OBS Virtual Camera**
   - Microphone: **CABLE Output**

Run using the developer helper script:
```bat
scripts\windows\dev\run.bat
```
Or set up manually in a Python virtual environment:
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -e .
streambridge
```

---

### Linux
1. **Install prerequisites:**
   ```bash
   sudo apt install v4l2loopback-dkms pulseaudio-utils python3-venv python3-tk
   sudo modprobe v4l2loopback devices=1 exclusive_caps=1 card_label="StreamBridge Camera"
   ```
2. **Launch StreamBridge:**
   ```bash
   scripts/linux/dev/run.sh
   # or manually:
   python3 -m venv .venv && source .venv/bin/activate && pip install -e . && streambridge
   ```
3. In your apps, select **StreamBridge Camera** and **StreamBridge Microphone**.

---

### macOS
1. Install [OBS Studio](https://obsproject.com/download) and [BlackHole 2ch](https://existential.audio/blackhole/).
2. Run StreamBridge:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate && pip install -e . && streambridge
   ```
3. In your apps, select **OBS Virtual Camera** and **BlackHole 2ch**.

---

## Features & Usage

### Key Capabilities

| Capability | Highlights | Options & Controls |
| :--- | :--- | :--- |
| 🧪 **Pre-Flight Testing** | Probes stream URLs and checks resolution, codecs, and audio sample rates before launching virtual hardware. | One-click **Test** button or CLI `--test` |
| 🔀 **Independent Channels** | Stream camera-only, microphone-only, or both simultaneously. | Video URL, Audio URL, or both |
| 🔄 **Auto-Reconnect & Shielding** | Recovers from Wi-Fi dropouts with exponential backoff (0.5 s to 10 s). Outputs clean black frames during reconnects so meeting apps never freeze or crash. | Automatic retry loop (transparent to apps) |
| 📐 **Adaptive Video Sizing** | Preserves aspect ratio with zero distortion; reopens hardware cleanly on mid-stream orientation shifts. | `Auto` (clamped 160px–4K), `1080p`, `720p`, `480p`, or custom `WxH` |
| ⚡ **Low-Latency Audio** | Pull-driven jitter buffer prevents delay buildup and smoothly corrects clock drift. | • **Low** (~30 ms buffer, default)<br>• **Normal** (~60 ms buffer)<br>• **Stable** (~150 ms buffer) |
| 🔒 **Privacy & Security** | Passwords are masked across UI and logs. Enforces TLS on public endpoints while allowing self-signed certs on private LANs. | Optional OS keychain via *Remember password* |
| 🧹 **Clean Reset** | Complete zero-residue cleanup of configs, recent URL history, logs, and stored credentials. | Menu *Reset to defaults…* or CLI `--reset [--logs]` |

---

### Command Line Interface

StreamBridge can be run from the command line using either the pre-built standalone executable or from source inside an activated virtual environment:

- **Standalone Release (no Python required):**
  - **Windows:** `StreamBridge.exe [options]`
  - **Linux:** `./StreamBridge [options]`
  - **macOS:** `/Applications/StreamBridge.app/Contents/MacOS/StreamBridge [options]`
- **From Source (activate `.venv` first):**
  - **Windows:** Run `.venv\Scripts\activate` then `streambridge [options]` *(or use `scripts\windows\dev\run.bat [options]`)*
  - **Linux / macOS:** Run `source .venv/bin/activate` then `streambridge [options]` *(or use `scripts/linux/dev/run.sh [options]`)*

```bash
# Launch GUI (run with no flags)
streambridge

# Headless streaming with audio and video
streambridge --video http://192.168.1.5:8080/video --audio http://192.168.1.5:8080/audio.wav

# Common CLI Options
streambridge --video URL [--audio URL] [--size Auto|1080p|720p|480p|WxH] [--fps 30]
             [--audio-latency low|normal|stable] [--audio-output NAME]
             [--test] [--check] [--reset [--logs] [--yes]] [--version] [-v]
```

---

## Development

```bash
# Environment setup
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Linting & unit tests
ruff check .
pytest

# OS-specific validation scripts
scripts/windows/dev/check_all.bat   # Windows
scripts/linux/dev/check_all.sh       # Linux
scripts/macos/dev/check_all.sh       # macOS
```

### Standalone Packaging
- **Local Dev Builds:** `scripts/<os>/dev/build_<os>.*`
- **Release-Identical Builds:** `scripts/<os>/build_onefile_<os>.*`

---

## Documentation & Governance

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Security Policy](SECURITY.md)
- [License](LICENSE) (MIT)
