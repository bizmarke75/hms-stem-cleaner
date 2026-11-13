# HMS Stem Cleaner & Headless VST3 Master Engine — Engineering Notebook
**Owner:** Charles Pinkerton Sr. / 337 West Productions  
**Last Updated:** 2026-11-12 19:58  
**Repository Path:** `C:\github\projects\hms-stem-cleaner`  
**Original Workspace:** `H:\suno projects`

---

## 1. Project Overview & Philosophy
This utility automates the sorting, de-echoing, VST3 DSP cleanup, bus gluing, and 24-bit mastering of AI-generated music stems (Suno v5.5/v6 tracks split via MVSep / BS-RoFormer / Demucs).
- **Why Headless Pedalboard over Reaper/FL Studio:** Runs 64-bit C++ VST3 plugins in memory 10x–50x faster than a DAW GUI, with zero `ReaFIR` FFT pre-ringing and exact sample-locked buffer summing.
- **Release Policy:** Shared publicly on GitHub strictly **"AS-IS" (MIT License, No Warranty/Support)**.

---

## 2. Root-Cause Troubleshooting Log (Lessons Learned)

### Issue A: Metallic Slapback Echo on "The Wolves Were a Lie"
1. **Duplicate / Ghost Stems in `[Music]` Folder:** MVSep folders contained both 4-stem and 6-stem Demucs outputs (`4_Keyboard_CLEAN.wav` at `-56.3 dB`, `6_Woodwinds_CLEAN.wav` at `-180.0 dB`, and composite `Music_CLEAN.wav` at `-58.5 dB` alongside `Guitars_CLEAN.wav` at `-25.3 dB`). Summing them triggered multi-stem gain scaling and doubled ghost vocal reverb tails.
   - **Fix (`filter_valid_bus_stems`):** Auto-rejects any stem with RMS `< -50.0 dB` and drops generic `*_Music_CLEAN.wav` or `*_Vocals_CLEAN.wav` composites when specific stems (`Guitars`, `Lead_Vocals`) exist.
2. **Center-Channel Vocal Bleed Inside Guitars (`suppress_vocal_bleed_in_music`):** MVSep dumps leftover vocal reverb tails into the center (`Mid`) channel of the `Music`/`Guitars` stem.
   - **Fix:** Decompose `Music` into `Mid = 0.5*(L+R)` and `Side = 0.5*(L-R)`. Apply `135 Hz` HPF + `-4.0 dB @ 420 Hz` + `-3.5 dB @ 1800 Hz` strictly to `Mid`, scale `Mid * 0.75` and `Side * 1.10`, then recombine.
3. **CHOWTapeModel Playhead Comb-Filtering & Pitch Drift:** By default, `CHOWTapeModel.vst3` loads with `loss_on_off = True` (playhead gap comb filter) and `wow_flutter_on_off = True`, shifting phase between buses.
   - **Fix:** Explicitly set `wow_flutter_on_off = False` and `loss_on_off = False` on all buses.
4. **Baked-In Mono Suno Vocal Delay:** When Suno bakes a ~120ms mono slapback directly into the vocal stem, heavy compression (`MJUCjr` at `22 dB`) pulls up the `-22 dB` delay repeats between words.
   - **Fix (`hms_ai_controller.py`):** Measure 25th-percentile active vocal tail floor (`p25_tail_db`). If `> -34.0 dB`, automatically raise `NoiseGate` threshold to `-24.0 to -30.0 dB` and lower `MJUCjr` `compress` to `11.0 dB`.

---

## 3. Verified 64-Bit VST3 C++ Parameter Keys (Do Not Guess Names!)

### A. `CHOWTapeModel.vst3`
- **Binary Path (Unwrapped Bundle):** `C:\Program Files\Common Files\VST3\CHOWTapeModel.vst3\Contents\x86_64-win\CHOWTapeModel.vst3`
- **Verified Keys:**
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
- **Verified Keys:**
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
- **Verified Keys:**
  - `compress`: `22.0` for clean vocals / `11.0` for echo-heavy vocals (`0.0` to `48.0` dB)
  - `makeup`: `2.0` (`-12.0` to `36.0` dB) — **Note: No underscore!**
  - `timing`: `'fast'` (valid strings: `'fast'`, `'slow'`, `'auto'`)

---

## 4. Verified Mix Balance Slider Profiles
- **Heavy Nu-Metal / Industrial Wall (Default — Tuned on *"Sensory Bleed"*):**
  - `Vocals`: `1.18` | `Rhythm`: `0.92` | `Music`: `0.76` | `Vocal Gate`: `-36.0 dB`
- **Dynamic / Acoustic Intro-Outro Rock (Tuned on *"The Wolves Were a Lie"*):**
  - `Vocals`: `1.12` | `Rhythm`: `0.92` | `Music`: `0.82` | `Vocal Gate`: `-26.0 dB`

---

## 5. 4-Phase GitHub & Standalone EXE Roadmap
- [x] **Phase 1:** Bootstrap `C:\github\projects\hms-stem-cleaner` (`setup_github_repo.py` + `DEV_LOG.md` + `README.md` + `LICENSE` + `.gitignore`).
- [ ] **Phase 2:** Flatten `hms_headless_dsp.py`, `mvsep_gui_injector.py`, `hms_ai_controller.py`, and `hms_workspace_manager.py` into a single, zero-import master script (`hms_stem_cleaner_app.py`) with Atomic Temp-File Rendering and Rollback Vault buttons.
- [ ] **Phase 3:** Build standalone `HMS_Stem_Cleaner.exe` via PyInstaller (`build_standalone_exe.py`).
- [ ] **Phase 4:** Initialize Git repository, commit v1.0.0 release, and push to GitHub.

---

## 6. Quick Copy-Paste Prompt for Future AI Chat Sessions
> "We are working on the HMS Stem Cleaner & Headless VST3 Master Engine in `C:\github\projects\hms-stem-cleaner`. Please read the attached `DEV_LOG.md` for our verified VST3 C++ parameter keys, anti-echo DSP architecture, and current roadmap phase, and follow the `modular-python-builder` skill (one function at a time with `[RUN]`/`[SUCCESS]`/`[ERROR]` logs and isolated verification snippets)."
