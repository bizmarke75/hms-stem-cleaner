# HMS Stem Cleaner & Headless VST3 Master Engine
**By 337 West Productions**

A standalone Windows utility built to clean, de-echo, sort, and master AI-generated music stems (such as Suno tracks split via MVSep/Demucs) using Spotify's `Pedalboard` C++ engine and free 64-bit VST3 plugins.

---

## ⚠️ IMPORTANT DISCLAIMER: OFFERED "AS-IS" (NO SUPPORT OR PROMISES)
> **Please Read Before Downloading:**
> I am an independent music creator, not a full-time software developer. I built this tool from scratch to solve stem bleed, metallic reverb tails, and slapback echo in my own studio workflow, and I am sharing it publicly because other AI music creators can benefit from it.
>
> **This software and its standalone `.exe` are provided strictly "AS-IS" without warranty or technical support.** I cannot promise bug fixes, custom feature requests, or troubleshooting for individual PC setups. Always keep backups of your original `.wav` files!

---

## Key Features
- **Automatic Stem Sorting & Renaming:** Routes messy MVSep/Demucs exports into `<Song_Name>\Vocals`, `Rhythm`, and `Music` folders.
- **Ghost Stem & Duplicate Rejection:** Automatically skips silent stems (`< -50 dB RMS`) and redundant composite stems that cause phase doubling.
- **Mid/Side Vocal Echo Suppression:** Carves center-channel vocal reverb bleed out of the `Music` bus while keeping wide stereo guitars intact.
- **Headless 64-Bit VST3 Processing:** Runs 10x faster than opening a DAW by driving C++ VST3 binaries directly in memory.
- **Live Mix Balance & Gate Levers:** Adjust `Vocals`, `Rhythm`, `Music`, and `Vocal Gate (dB)` sliders and re-render a 24-bit Master `.wav` in seconds.
- **Safety Checkpoint & Rollback Vault:** Creates non-destructive backups before moving or cleaning stems.

## Optional Free VST3 Plugins (Auto-Detected)
If installed in `C:\Program Files\Common Files\VST3`, the engine automatically loads and configures:
1. **TDR Nova** (Tokyo Dawn Labs - Dynamic EQ)
2. **MJUCjr** (Klanghelm - Variable-Mu Vocal Compressor)
3. **CHOWTapeModel** (Chowdhury DSP - Analog Tape Saturation)
*(Note: If you do not have these VST3s installed, the app will still run using its built-in Pedalboard EQ, Gate, Compressor, and Limiter chain!)*
