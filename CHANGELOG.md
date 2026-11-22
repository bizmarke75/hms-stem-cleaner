# Changelog — HMS Unified Studio Suite

## [1.4.1] - 2026-11-22
### Added
- Collapsible panel toggles (▾ / ▸) with persistent localStorage state across the Waveform Monitor, Stereo PCM Deck, Group A/B Mixer Racks, MVSep/Multi-Pass/Recipe Cards, and Telemetry Console.
- Live **Test APIs** header verifier wired through HMSWebDawBridge and /api/verify_keys (127.0.0.1:8765).
- Topmost native Windows JSON file picker (rowse_json_file).

### Fixed
- Upgraded Gemini models from deprecated gemini-2.5-* to the active 2026 Free-Tier chain (gemini-3.8-flash -> gemini-3.6-flash -> gemini-3.5-flash-lite -> gemini-3.1-flash-lite) with x-goog-api-key.
- Added frontend and backend guards blocking Gemini Tune and DSP runs when Source Song Dir is empty, ., or the HMS app folder.
- Installed HMS_DOM_ORDER_GUARD_V1_4_2 and enforced persistent %LOCALAPPDATA%\HMS Studio Suite\WebView2Cache (private_mode=False) to eliminate [WinError 2] temp-folder exit warnings.
- Upgraded uild_v1_4_windows_installer.py to 1.4.1 with PrivilegesRequired=admin, clean _internal upgrades, and pre-build UI-fix checks.

## [1.4.0] - 2026-11-20
- Admin Windows Installer (--onedir + Inno Setup 6), Real-Time Stereo PCM Waveform Engine, and MVSep Free-Tier Safe Sequential Multi-Pass Queue.
