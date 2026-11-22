# Changelog — HMS Unified Studio Suite

All notable changes to **337 West Productions — HMS Unified Studio Suite** are documented in this file.

---

## [1.4.1] - 2026-11-21
### Fixed
- Stopped 60 FPS `<canvas>` GPU texture reallocation in `337_west_hms_unified_studio_web_daw_v1.4.html` and added WebView2 GPU compositing fallback in `hms_web_daw_launcher.py`.
- Routed **Load JSON** and **Load Recipe JSON** through a topmost native Python file dialog (`browse_json_file`) so Edge WebView2 never dims or locks behind a hidden modal picker.
- Restored full v1.4 bridge method parity (`get_keys_status`, `save_keys`, `generate_recipe`, `execute_stem_cleanup`, `start_mvsep_single_pass`, `run_single_pass`, `run_all_passes`) before `__main__`.
- Fixed `log_callback` keyword typo in `hms_ai_api_bridge.py`.
### Added
- End-to-end **Generate Recipe (Gemini)** builder writing `<Song>.hms_recipe.json` with verified 4-pass Free-Tier Safe fallback (tested on *C.R.E.A.M. (Blues)*).
- Dedicated repository `CHANGELOG.md` and `release_v1_4_1_suite.py` release automation.

## [1.4.0] - 2026-11-20
### Added
- Non-portable Admin Windows Installer (`HMS_Studio_Suite_v1.4.0_Setup.exe`) via PyInstaller `--onedir` + Inno Setup 6 with `%LOCALAPPDATA%\HMS Studio Suite` writable data routing (`hms_runtime_paths.py`).
- Real-Time Stereo PCM Waveform & Oscilloscope Engine (v1.4.3) with Pure-JS 8/16/24/32-bit & `WAVE_FORMAT_EXTENSIBLE` WAV parsing.
- MVSep Registered Free-Tier Safe Mode & 1-concurrent-job Sequential Multi-Pass Runner (`hms_mvsep_multipass.py`).

## [1.3.0] - 2026-11-17
### Added
- Dark-mode Web-DAW Frontend (`hms_web_daw.html`), native Windows Edge WebView2 launcher (`hms_web_daw_launcher.py`), and Google Chrome Studio Server (`launch_chrome_web_daw.py`).

## [1.2.0] - 2026-11-17
### Added
- Unified 2-Tab Studio GUI (`hms_unified_studio_app.py`), 9-Slider VST3 Mixer, and automatic `<Song_Name>_MIX_SETTINGS.json` persistence (`hms_mix_json_manager.py`).

## [1.1.0] - 2026-11-14
### Added
- Mix Style Mode Switch (`Auto-Detect`, `Acoustic / Dynamic Rock`, `Heavy Metal / Industrial`), 6-stem `Other_Synths` retention fix, and lossless WAV-to-FLAC MVSep pre-compression.

## [1.0.0] - 2026-11-12
### Added
- Initial standalone Win64 release of HMS Stem Cleaner & Headless 64-Bit VST3 Master Engine (`hms_stem_cleaner_app.py`) with Atomic WAV Writer and Rollback Vault.
