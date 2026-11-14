# HMS Stem Cleaner & Headless VST3 Master Engine — Engineering Notebook
**Owner:** Charles Pinkerton Sr. / 337 West Productions
**Last Updated:** 2026-11-13 07:49
**Current Version:** `v1.0.0` (Standalone Win64 Release)
**Local Repository Path:** `C:\github\projects\hms-stem-cleaner`
**GitHub Remote URL:** `[https://github.com/bizmarke75/hms-stem-cleaner](https://github.com/bizmarke75/hms-stem-cleaner)`
**Original Workspace:** `H:\suno projects` (Diagnostic clutter archived to `_archive_diagnostics\`)

---

## 1. Project Overview & Philosophy
This utility automates the sorting, de-echoing, VST3 DSP cleanup, bus gluing, and 24-bit mastering of AI-generated music stems (Suno v5.5/v6 tracks split via MVSep / BS-RoFormer / Demucs).
- **Zero-Import Single-File Design:** All layers (Atomic WAV I/O, Rollback Vault, VST3 C++ Engine, AI Telemetry Auto-Tuner, and Tkinter GUI) are consolidated into a single file (`hms_stem_cleaner_app.py`) to eliminate cross-module `ImportError` desyncs.
- **Why Headless Pedalboard over Reaper/FL Studio:** Runs 64-bit C++ VST3 plugins in memory 10x-50x faster than a DAW GUI, with zero `ReaFIR` FFT pre-ringing and exact sample-locked buffer summing.
- **Release Policy:** Shared publicly on GitHub strictly **'AS-IS' (MIT License, No Warranty/Support)**.

---

## 2. Root-Cause Troubleshooting Log (Lessons Learned)

### Issue A: Metallic Slapback Echo on 'The Wolves Were a Lie'
1. **Duplicate / Ghost Stems in `[Music]` Folder:** MVSep folders contained both 4-stem and 6-stem Demucs outputs (`4_Keyboard_CLEAN.wav` at `-56.3 dB`, `6_Woodwinds_CLEAN.wav` at `-180.0 dB`, and composite `Music_CLEAN.wav` at `-58.5 dB` alongside `Guitars_CLEAN.wav` at `-25.3 dB`). Summing them triggered multi-stem gain scaling and doubled ghost vocal reverb tails.
   - **Fix (`filter_valid_bus_stems`):** Auto-rejects any stem with RMS `< -50.0 dB` and drops generic `*_Music_CLEAN.wav` or `*_Vocals_CLEAN.wav` composites when specific stems (`Guitars`, `Lead_Vocals`) exist.
2. **Center-Channel Vocal Bleed Inside Guitars (`suppress_vocal_bleed_in_music`):** MVSep dumps leftover vocal reverb tails into the center (`Mid`) channel of the `Music`/`Guitars` stem.
   - **Fix:** Decompose `Music` into `Mid = 0.5*(L+R)` and `Side = 0.5*(L-R)`. Apply `135 Hz` HPF + `-4.0 dB @ 420 Hz` + `-3.5 dB @ 1800 Hz` strictly to `Mid`, scale `Mid * 0.75` and `Side * 1.10`, then recombine.
3. **CHOWTapeModel Playhead Comb-Filtering & Pitch Drift:** By default, `CHOWTapeModel.vst3` loads with `loss_on_off = True` (playhead gap comb filter) and `wow_flutter_on_off = True`, shifting phase between buses.
   - **Fix:** Explicitly set `wow_flutter_on_off = False` and `loss_on_off = False` on all buses.
4. **Baked-In Mono Suno Vocal Delay:** When Suno bakes a ~120ms mono slapback directly into the vocal stem, heavy compression (`MJUCjr` at `22 dB`) pulls up the `-22 dB` delay repeats between words.
   - **Fix (`analyze_and_autotune_song`):** Measure 25th-percentile active vocal tail floor (`p25_tail_db`). If `> -34.0 dB`, automatically raise `NoiseGate` threshold to `-22.0 to -32.0 dB` and lower `MJUCjr` `compress` to `11.0 dB`.

### Issue B: Git Remote HTTP 400 Error on Initial Push
- **Cause:** Running `git remote add origin` with a bracketed placeholder URL caches the invalid URL in `.git/config`.
- **Fix:** Overwrite the cached remote URL via `git remote set-url origin [https://github.com/bizmarke75/hms-stem-cleaner.git](https://github.com/bizmarke75/hms-stem-cleaner.git)`.

### Issue C: Unterminated Triple-Quoted F-String in Notebook Generator
- **Cause:** Nested triple-backtick code blocks inside a Python triple-quoted f-string (`f"""`) can clip when copied across chat/browser buffers.
- **Fix:** Construct Markdown files using a list of standard single-line strings joined with `"\n".join(lines)`.

---

## 3. Verified 64-Bit VST3 C++ Parameter Keys (Do Not Guess Names!)

### A. `CHOWTapeModel.vst3`
- **Binary Path (Unwrapped Bundle):** `C:\Program Files\Common Files\VST3\CHOWTapeModel.vst3\Contents\x86_64-win\CHOWTapeModel.vst3`
- **Verified Keys (11 Levers):**
  - `wow_flutter_on_off`: `False` (bool) — **CRITICAL: Prevents phase drift**
  - `loss_on_off`: `False` (bool) — **CRITICAL: Disables playhead gap comb filter**
  - `flutter_depth`: `0.0` (`0.0` to `1.0`)
  - `wow_depth`: `0.0` (`0.0` to `1.0`)
  - `tape_on_off`: `True` (bool)
  - `tape_drive`: `0.38` on Rhythm / `0.30` on Music / `0.25` on Master (`0.0` to `1.0`)
  - `tape_saturation`: `0.45` on Rhythm / `0.35` on Music / `0.30` on Master (`0.0` to `1.0`)
  - `tone_on_off`: `True` (bool)
  - `tone_bass`: `0.15` (`-1.0` to `1.0`)
  - `tone_treble`: `0.10` (`-1.0` to `1.0`)
  - `dry_wet`: `45.0` on Rhythm / `35.0` on Music / `25.0` on Master (`0.0` to `100.0` %)

### B. `TDR Nova.vst3`
- **Binary Path:** `C:\Program Files\Common Files\VST3\TDR Nova.vst3`
- **Verified Keys (23 Vocal Levers / 16 Music Levers / 12 Master Levers):**
  - `hp_active`: `True` (bool), `hp_frequency_hz`: `95.0` (Vocals) / `115.0` (Music) / `28.0` (Master)
  - `band_X_active`: `True` (bool, where X = 1, 2, 3, 4)
  - `band_X_frequency_hz`: float (`10.0` to `40000.0` Hz)
  - `band_X_q`: float (`0.1` to `6.0`)
  - `band_X_gain_db`: float (`-18.0` to `18.0` dB)
  - `band_X_dyn`: `'On'` (valid strings: `'Off'`, `'On'`, `'Sticky'`)
  - `band_X_threshold_db`: float (`-50.0` to `0.0` dB)
  - `band_X_ratio`: float (`0.5` to `inf`)
  - `wide_band_dyn`: `True` (bool, Master Bus glue), `wide_band_threshold_db`: `-16.0`, `wide_band_ratio`: `1.5`

### C. `MJUCjr.vst3`
- **Binary Path:** `C:\Program Files\Common Files\VST3\MJUCjr.vst3`
- **Verified Keys (3 Levers):**
  - `compress`: `22.0` for clean vocals / `11.0` for echo-heavy vocals (`0.0` to `48.0` dB)
  - `makeup`: `2.0` (`-12.0` to `36.0` dB) — **Note: No underscore!**
  - `timing`: `'fast'` (valid strings: `'fast'`, `'slow'`, `'auto'`)

---

## 4. Verified Mix Balance Slider Profiles
- **Heavy Nu-Metal / Industrial Wall (Default — Tuned on 'Sensory Bleed'):**
  - `Vocals`: `1.18` | `Rhythm`: `0.92` | `Music`: `0.76` | `Vocal Gate`: `-36.0 dB`
- **Dynamic / Acoustic Intro-Outro Rock (Tuned on 'The Wolves Were a Lie'):**
  - `Vocals`: `1.10`-`1.12` | `Rhythm`: `0.92` | `Music`: `0.82` | `Vocal Gate`: `-24.0` to `-28.0 dB`

---

## 5. Single-File Architecture Map (`hms_stem_cleaner_app.py`)
1. **Layer 1A (`get_app_base_dir`):** PyInstaller-safe path resolver (`sys.frozen` check).
2. **Layer 1B (`write_wav_atomic`):** Writes to `.tmp_<PID>.wav` first, checks `> 44 bytes`, then executes atomic `os.replace()` so interrupted renders never corrupt existing `.wav` files.
3. **Layer 1C (`create_song_checkpoint` & `restore_song_checkpoint`):** Backs up raw source `.wav` stems to `_HMS_Rollback_Vault\<Song_Name>\snapshot_<Timestamp>\` before any move or DSP render.
4. **Layer 2A (`resolve_vst3_binary_path`, `set_lever_exact`, `configure_*`):** Unwraps VST3 bundle directories and binds verified C++ parameters.
5. **Layer 2B (`filter_valid_bus_stems`, `suppress_vocal_bleed_in_music`, `render_master_mixdown`, `analyze_and_autotune_song`, `execute_stem_cleanup`):** Core headless DSP & AI telemetry auto-tuning engine.
6. **Layer 3 (`HMSStudioSingleFileGUI`):** Unified Dark-Mode Tkinter GUI featuring Sliders + Buttons `0. AI AUTO-TUNE`, `1. DRY-RUN AUDIT`, `2. FULL LIVE CLEAN + MASTER`, `3. GLUE BUSES & MASTER ONLY`, and `4. ROLLBACK CHECKPOINT`.

---

## 6. Completed Roadmap & Key Maintenance Commands
- [x] **Phase 1:** Bootstrapped `C:\github\projects\hms-stem-cleaner` (`README.md`, `LICENSE`, `.gitignore`, `DEV_LOG.md`, `src_backup\`).
- [x] **Phase 2:** Flattened all modules into `hms_stem_cleaner_app.py` with atomic file writes and Rollback Vault.
- [x] **Phase 3:** Compiled standalone `dist\HMS_Stem_Cleaner.exe` via `build_standalone_exe.py`.
- [x] **Phase 4:** Committed `v1.0.0`, packaged `release_upload\HMS_Stem_Cleaner_v1.0.0_Win64_Standalone.zip`, and pushed to `[https://github.com/bizmarke75/hms-stem-cleaner](https://github.com/bizmarke75/hms-stem-cleaner)`.

### Common PowerShell Commands
- **Launch GUI from source:** `python.exe C:\github\projects\hms-stem-cleaner\hms_stem_cleaner_app.py`
- **Run Headless Self-Test:** `python.exe C:\github\projects\hms-stem-cleaner\hms_stem_cleaner_app.py --test-layer2b`
- **Rebuild Standalone EXE:** `python.exe C:\github\projects\hms-stem-cleaner\build_standalone_exe.py`
- **Update & Push DEV_LOG.md:** `python.exe C:\github\projects\hms-stem-cleaner\update_dev_notebook.py --push`

---

## 7. Quick Copy-Paste Prompt for Future AI Chat Sessions
> We are working on the HMS Stem Cleaner & Headless VST3 Master Engine (v1.0.0) at C:\github\projects\hms-stem-cleaner (GitHub: [https://github.com/bizmarke75/hms-stem-cleaner](https://github.com/bizmarke75/hms-stem-cleaner)). Please read the attached DEV_LOG.md for our single-file Layer 1-3 architecture (hms_stem_cleaner_app.py), verified VST3 C++ parameter keys, and anti-echo DSP math, and follow the modular-python-builder skill (one function at a time with [RUN]/[SUCCESS]/[ERROR] logs and isolated verification snippets).


---

# HMS Stem Cleaner & Headless VST3 Master Engine v1.1.0 (Provided As-Is)

**Release Date:** 2026-11-14  
**Studio:** 337 West Productions  
**License:** MIT (Provided strictly **AS-IS** with no warranty or technical support)

---

## What's New in v1.1.0

### 1. Mix Style Mode Switch (`Auto-Detect`, `Acoustic / Dynamic Rock`, `Heavy Metal / Industrial`)
* **Auto-Detect (Smart Telemetry):** Automatically inspects song folder keywords (`acoustic`, `solo`, `unplugged`) and measures Guitar/Music Mid-vs-Side stereo energy to select the optimal DSP profile.
* **Acoustic / Dynamic Rock Mode:** Bypasses Mid-channel center guitar carving (`suppress_vocal_bleed_in_music`) so centered acoustic guitars and centered guitar solos stay 100% intact, while setting a natural vocal balance (`Vocals=0.90`, `Rhythm=1.02`, `Music=0.98`, `MJUCjr Makeup=+0.5 dB`).
* **Heavy Metal / Industrial Mode:** Engages the full Mid/Side center vocal pocket (`350 Hz – 2.8 kHz`) and punchy bus weights for dense high-gain guitar and synth walls.

### 2. 6-Stem MVSep (`BS Roformer SW`) Synth & `Other` Stem Retention Fix
* Fixed an issue where MVSep 6-stem `other` files (synths, atmospheric pads, electronic arpeggios, and industrial outros) were tagged as generic `*_Music_CLEAN.wav` and skipped when `*_Guitars_CLEAN.wav` was present in the `[Music]` bus.
* `other` stems are now routed as dedicated `Other_Synths` stems and summed cleanly alongside `Guitars` during bus gluing and 24-bit Master Mixdown rendering.

### 3. MVSep GUI Bridge Upgrades (`mvsep_gui.py`)
* **Persistent User Config (`~/.mvsep_hms_config.json`):** Saves your MVSep API token and preferred HMS Mix Style Mode locally across restarts.
* **Lossless WAV -> FLAC Pre-Compression & 600s Socket Write Timeout:** Compresses large uncompressed `.wav` masters (>15 MB) into temporary lossless `.flac` files before upload and uses a single-float `600.0s` socket timeout so 45+ MB uploads never drop at 20 seconds on Windows SSL sockets.
