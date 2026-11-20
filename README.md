# HMS Unified Studio Suite (`v1.4.0`)
**By 337 West Productions** | Automated MVSep Cloud Stem Splitting, Headless 64-Bit VST3 Stem Cleanup & 24-Bit Master Mixdown

> **PROVIDED STRICTLY "AS-IS" (MIT LICENSE — NO WARRANTY OR SUPPORT)**  
> This studio utility is shared openly for fellow Suno, MVSep, and AI-assisted music creators. Always keep backups of your raw `.wav` stems.

---

## What This Suite Does
1. **Splits full songs into stems** directly inside the Web-DAW via MVSep Cloud (Single-Pass or Free-Tier Safe Sequential Multi-Pass).
2. **Cleans stem bleed, mud, harshness, and slapback echo** headlessly in 64-bit C++ memory using **TDR Nova**, **MJUCjr**, and **CHOWTapeModel** (with automatic native Pedalboard DSP fallback if any VST3 is not installed).
3. **Glues stems into Vocals, Rhythm, and Music buses** and renders a phase-tight **24-bit Master WAV** (`<Song_Name>_MASTER_MIX.wav`) with real-time stereo L/R PCM waveform auditing.

---

## Quick Start (Any Skill Level)

### Option A: Windows Installer (Recommended — No Python Required)
1. Download and run **`HMS_Studio_Suite_v1.4.0_Setup.exe`** from the **GitHub Releases** page.
2. Approve the Administrator prompt to install into `C:\Program Files\HMS Studio Suite` (or pick any drive/folder during setup).
3. *(Optional, Recommended)* Install the 3 free 64-bit `.vst3` plugins into `C:\Program Files\Common Files\VST3`:
   - **TDR Nova** (Dynamic EQ)
   - **Klanghelm MJUCjr** (Variable-Mu Vocal Compressor)
   - **CHOWTapeModel** (Analog Tape Saturation)
4. Launch **HMS Unified Studio Suite** from your Desktop or Start Menu.

### Option B: Run From Source (Python 3.11+ on Windows)
```powershell
pip install -r requirements.txt
python.exe hms_web_daw_launcher.py          # Native Windows Edge WebView2 Desktop UI
python.exe launch_chrome_web_daw.py         # Google Chrome Studio App Mode (:8765)
```

---

## 3-Step Workflow Inside the v1.4 Web-DAW UI
1. **Enter API Keys Once (Top API Vault):** Save your **MVSep API Token** (for cloud splitting) and optional **Gemini API Key** (for Cloud AI listening). Keys are stored outside the repo in `~/.mvsep_hms_config.json`.
2. **Split or Load Stems:**
   - **From a Full Song:** Use **Step 1: MVSep Cloud Stem Splitter**. Leave **Free-Tier Safe Mode** checked on a Registered Free account to block Premium Ensemble models & 24/32-bit formats and run the Multi-Pass Recipe strictly 1 job at a time.
   - **From Existing Stems:** Place one song's raw `.wav` stems in a dedicated folder named after the song, click **Browse**, click **0. AI Auto-Tune**, and run **2. Full Live Clean + Master**.
3. **Audition & 3-Second Re-Mix:**
   - Switch tracks in the **A/B Audition Deck** and inspect the **Real-Time Stereo PCM Waveform (L/R)**.
   - Adjust Group A Bus Faders (**Vocals**, **Rhythm**, **Music**) and click **3. Glue Buses & Render Master Only** to update your 24-bit Master in ~3 seconds without re-cleaning stems.
   - Switch **Mix Style Mode** to **Acoustic / Dynamic Rock** to keep centered acoustic guitars & solos untouched, or **Heavy Metal / Industrial** for full Mid/Side center vocal pocket carving.

---

## Core v1.4.0 Repository Layout
- `337_west_hms_unified_studio_web_daw_v1.4.html` / `hms_web_daw.html` — Dark-mode Web-DAW UI with Real-Time Stereo PCM Waveform, 9-Slider Hardware Rack, and MVSep Free-Tier Multi-Pass Recipe Card.
- `hms_web_daw_launcher.py` — Native Windows Edge WebView2 (`pywebview`) desktop launcher & JS bridge.
- `launch_chrome_web_daw.py` — Local HTTP/REST server (`127.0.0.1:8765`) & Google Chrome App Mode launcher.
- `hms_runtime_paths.py` — Frozen/non-portable path resolver routing writable vault, logs, presets, and `WebView2Cache` into `%LOCALAPPDATA%\HMS Studio Suite`.
- `hms_mvsep_multipass.py` — Registered Free-Tier validator, duplicate-stem isolator, and 1-concurrent-job sequential 4-pass MVSep queue runner.
- `hms_stem_cleaner_app.py` — Headless 64-bit VST3 & Pedalboard DSP engine, atomic WAV writer, and Rollback Vault.
- `hms_gemini_tuner.py` & `hms_ai_api_bridge.py` — Multimodal Gemini mix tuner & local REST bridge.
- `hms_mix_json_manager.py` — Per-song `<Song_Name>_MIX_SETTINGS.json` preset persistence.
- `fix_v1_4_html_and_rebuild.py` & `build_v1_4_windows_installer.py` — PyInstaller `--onedir` bundle compiler and Inno Setup 6 Admin installer builder.
- `DEV_LOG.md` — Complete engineering notebook, VST3 C++ parameter tables, and troubleshooting history.
