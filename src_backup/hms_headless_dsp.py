# Save as: H:\suno projects\hms_headless_dsp.py
# Self-Test    : python.exe .\hms_headless_dsp.py
# Dry-Run CLI  : python.exe .\hms_headless_dsp.py --source "H:\suno projects\Sensory_Bleed"
# Live + Master: python.exe .\hms_headless_dsp.py --source "H:\suno projects\Sensory_Bleed" --live

import os
import re
import time
import wave
import shutil
import argparse
import traceback
import numpy as np
from pedalboard import (
    Pedalboard,
    HighpassFilter,
    LowpassFilter,
    PeakFilter,
    NoiseGate,
    Compressor,
    Limiter,
    Gain,
    load_plugin
)
from pedalboard.io import AudioFile


# ==============================================================================
# FUNCTION 1: VST3 BINARY & BUNDLE RESOLVER
# ==============================================================================
def resolve_vst3_binary_path(vst3_root=r"C:\Program Files\Common Files\VST3"):
    """
    Scans the Windows VST3 directory for CHOWTapeModel, TDR Nova, and MJUCjr.
    Automatically unwraps VST3 directory bundles (Contents\\x86_64-win\\*.vst3).
    """
    vst3_status = {
        "CHOWTapeModel.vst3": None,
        "TDR Nova.vst3": None,
        "MJUCjr.vst3": None
    }
    print(f"[RUN] Resolving loadable VST3 binaries in: {vst3_root}")

    if not os.path.exists(vst3_root):
        print(f"[ERROR] VST3 directory not found: {vst3_root}")
        return vst3_status

    try:
        for root, dirs, files in os.walk(vst3_root):
            if ".vst3" in root.lower():
                continue

            for item in dirs + files:
                for target_name in vst3_status.keys():
                    if item.lower() == target_name.lower() and vst3_status[target_name] is None:
                        candidate_path = os.path.join(root, item)

                        if os.path.isdir(candidate_path):
                            inner_bin = os.path.join(candidate_path, "Contents", "x86_64-win", item)
                            if os.path.exists(inner_bin):
                                vst3_status[target_name] = inner_bin
                                print(f"[SUCCESS] Resolved Bundle Binary: {target_name} -> {inner_bin}")
                            else:
                                print(f"[ERROR] Bundle folder missing x86_64-win binary: {inner_bin}")
                        else:
                            vst3_status[target_name] = candidate_path
                            print(f"[SUCCESS] Resolved Single Binary: {target_name} -> {candidate_path}")

        return vst3_status

    except Exception:
        print("[ERROR] Exception while scanning for VST3 binaries:")
        print(traceback.format_exc())
        return vst3_status


# ==============================================================================
# FUNCTION 2: SONG-BASED STEM TAGGER & BUS ROUTER
# ==============================================================================
def extract_clean_stem_tag(raw_filename, song_name, parent_folder_name=""):
    """
    Determines the HMS Bus ('Vocals', 'Rhythm', 'Music') from a raw filename
    and builds standardized filenames prefixed with the song directory name.
    """
    name_no_ext = os.path.splitext(raw_filename)[0]
    lower_name = name_no_ext.lower()
    lower_parent = parent_folder_name.lower()

    if any(k in lower_name for k in ["vocal", "vox", "lead", "backing", "choir", "acapella"]) or lower_parent == "vocals":
        bus_category = "Vocals"
        if "back" in lower_name:
            stem_role = "Backing_Vocals"
        elif "lead" in lower_name:
            stem_role = "Lead_Vocals"
        else:
            stem_role = "Vocals"
    elif any(k in lower_name for k in ["drum", "bass", "kick", "snare", "perc", "rhythm", "sub"]) or lower_parent == "rhythm":
        bus_category = "Rhythm"
        if "drum" in lower_name:
            stem_role = "Drums"
        elif "bass" in lower_name:
            stem_role = "Bass"
        else:
            stem_role = "Rhythm"
    else:
        bus_category = "Music"
        if "guitar" in lower_name or "gtr" in lower_name:
            stem_role = "Guitars"
        elif "synth" in lower_name or "keys" in lower_name or "piano" in lower_name:
            stem_role = "Synths"
        elif "other" in lower_name or "inst" in lower_name or "music" in lower_name:
            stem_role = "Music"
        else:
            cleaned_custom = re.sub(r"[^a-zA-Z0-9]+", "_", name_no_ext).strip("_")
            stem_role = cleaned_custom if cleaned_custom else "Music"

    renamed_filename = f"{song_name}_{stem_role}.wav"
    dsp_cleaned_filename = f"{song_name}_{stem_role}_CLEAN.wav"
    return bus_category, renamed_filename, dsp_cleaned_filename


# ==============================================================================
# FUNCTION 3: READ-ONLY DRY-RUN SCANNER & MANIFEST PLANNER
# ==============================================================================
def scan_and_plan_dry_run(source_dir, dest_root=None, vst3_root=r"C:\Program Files\Common Files\VST3", vocal_gate_db=-36.0):
    """
    Performs a read-only audit of source_dir, extracts the song name from the
    directory name, resolves VST3 binaries, and maps all stem target paths.
    """
    norm_source = os.path.normpath(source_dir)
    raw_dir_name = os.path.basename(norm_source)
    song_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", raw_dir_name).strip("_")

    if dest_root is None:
        parent_dir = os.path.dirname(norm_source)
        dest_song_dir = os.path.join(parent_dir, f"{song_name}_Cleaned")
    else:
        dest_song_dir = os.path.join(os.path.normpath(dest_root), song_name)

    print("=" * 70)
    print(f"[RUN] Starting HMS Dry-Run Audit")
    print(f"[INFO] Source Directory : {norm_source}")
    print(f"[INFO] Detected Song    : {song_name}")
    print(f"[INFO] Dest Song Dir    : {dest_song_dir}")
    print(f"[INFO] Vocal Gate Level : {vocal_gate_db:.1f} dB")
    print("=" * 70)

    manifest = {
        "source_dir_exists": False,
        "song_name": song_name,
        "source_dir": norm_source,
        "dest_song_dir": dest_song_dir,
        "vst3_status": resolve_vst3_binary_path(vst3_root),
        "valid_stems": []
    }

    try:
        if not os.path.exists(norm_source):
            print(f"[ERROR] Source stem directory does not exist: {norm_source}")
            return manifest
        manifest["source_dir_exists"] = True

        bus_blueprints = {
            "Vocals": [
                "HPF(95Hz)",
                f"NoiseGate({vocal_gate_db:.1f}dB)",
                "TDR Nova(DynEQ: 360Hz/3.2kHz/6.5kHz)",
                "MJUCjr(Comp:22dB/Fast/Makeup:2dB)",
                "Compressor(2.0:1)",
                "Limiter(-1.0dB)"
            ],
            "Rhythm": [
                "HPF(30Hz)",
                "NoiseGate(-42dB)",
                "CHOWTape(Drive:0.38/Sat:0.45/LossOff/FlutterOff)",
                "Compressor(3.5:1)",
                "Limiter(-0.5dB)"
            ],
            "Music": [
                "HPF(115Hz)",
                "TDR Nova(DynEQ: 320Hz Mud + 2.2kHz VocalPocket)",
                "CHOWTape(Drive:0.30/Sat:0.35/LossOff/FlutterOff)",
                "Compressor(2.0:1)",
                "Limiter(-1.0dB)"
            ]
        }

        used_filenames = {}

        for root, _, files in os.walk(norm_source):
            parent_folder = os.path.basename(root)
            for fname in sorted(files):
                upper_f = fname.upper()
                if upper_f.endswith(".WAV") and not any(
                    upper_f.endswith(tag) for tag in ["_CLEAN.WAV", "_GLUED.WAV", "_MASTER_MIX.WAV", "_NO_ECHO.WAV"]
                ):
                    in_wav = os.path.join(root, fname)
                    bus_cat, renamed_wav, cleaned_wav = extract_clean_stem_tag(fname, song_name, parent_folder)

                    if renamed_wav in used_filenames:
                        used_filenames[renamed_wav] += 1
                        idx = used_filenames[renamed_wav]
                        base_r, ext_r = os.path.splitext(renamed_wav)
                        renamed_wav = f"{base_r}_{idx}{ext_r}"
                        cleaned_wav = f"{base_r}_{idx}_CLEAN{ext_r}"
                    else:
                        used_filenames[renamed_wav] = 1

                    dest_bus_folder = os.path.join(dest_song_dir, bus_cat)
                    renamed_dest_path = os.path.join(dest_bus_folder, renamed_wav)
                    cleaned_dest_path = os.path.join(dest_bus_folder, cleaned_wav)
                    size_mb = round(os.path.getsize(in_wav) / (1024 * 1024), 2)

                    stem_entry = {
                        "song_name": song_name,
                        "bus": bus_cat,
                        "original_filename": fname,
                        "renamed_filename": renamed_wav,
                        "cleaned_filename": cleaned_wav,
                        "source_path": in_wav,
                        "dest_bus_folder": dest_bus_folder,
                        "renamed_dest_path": renamed_dest_path,
                        "cleaned_dest_path": cleaned_dest_path,
                        "size_mb": size_mb,
                        "planned_chain": bus_blueprints[bus_cat]
                    }
                    manifest["valid_stems"].append(stem_entry)

                    print(f"[DRY-RUN] [{bus_cat}] '{fname}' ({size_mb} MB)")
                    print(f"          Renamed Raw -> {renamed_dest_path}")
                    print(f"          Cleaned DSP -> {cleaned_dest_path}")
                    print(f"          FX Chain    -> {' -> '.join(bus_blueprints[bus_cat])}")

        print(f"[SUCCESS] Dry-Run Audit Complete: {len(manifest['valid_stems'])} stem(s) mapped for '{song_name}'.")
        return manifest

    except Exception:
        print(f"[ERROR] Exception during dry-run scan of {norm_source}:")
        print(traceback.format_exc())
        return manifest


# ==============================================================================
# FUNCTION 4: VERIFIED C++ VST3 PARAMETER BINDING & BUS CONFIGURATORS
# ==============================================================================
def load_vst3_safe(plugin_path, preset_path=None):
    """Safely loads a verified 64-bit VST3 binary path into Pedalboard."""
    if not plugin_path or not os.path.exists(plugin_path):
        print(f"[INFO] VST3 path unavailable, skipping: {plugin_path}")
        return None

    try:
        print(f"[RUN] Loading VST3 binary: {os.path.basename(plugin_path)}...")
        plugin = load_plugin(plugin_path)
        print(f"[SUCCESS] Initialized VST3: {plugin.name}")

        if preset_path and os.path.exists(preset_path):
            print(f"[RUN] Applying preset: {os.path.basename(preset_path)}")
            with open(preset_path, "rb") as f:
                plugin.preset_data = f.read()
            print(f"[SUCCESS] Applied preset to {plugin.name}")

        return plugin

    except Exception:
        print(f"[ERROR] Failed to load VST3 at: {plugin_path}")
        print(traceback.format_exc())
        return None


def set_lever_exact(plugin, key, value):
    """
    Sets an exact verified C++ parameter key on a VST3 plugin, reads back the
    new state from the C++ host, and logs [SUCCESS] or [ERROR].
    """
    if plugin is None:
        return False
    if key not in plugin.parameters:
        print(f"[ERROR]   [{plugin.name}] Key '{key}' not found in plugin.parameters!")
        return False

    try:
        before = getattr(plugin, key)
        setattr(plugin, key, value)
        after = getattr(plugin, key)
        print(f"[SUCCESS] [{plugin.name:<13}] {key:<26}: {str(before):<10} -> {str(after)}")
        return True
    except Exception as e:
        print(f"[ERROR]   [{plugin.name:<13}] Failed setting '{key}' = {value}: {e}")
        return False


def configure_chow_tape(chow_plugin, drive=0.38, sat=0.45, dry_wet=45.0, bass=0.15, treble=0.10):
    """
    Applies verified C++ parameter keys to CHOWTapeModel.vst3.
    Disables playhead loss comb-filtering and wow/flutter pitch drift to keep buses 100% phase-locked.
    """
    if chow_plugin is None:
        return
    set_lever_exact(chow_plugin, "wow_flutter_on_off", False)
    set_lever_exact(chow_plugin, "loss_on_off", False)
    set_lever_exact(chow_plugin, "flutter_depth", 0.0)
    set_lever_exact(chow_plugin, "wow_depth", 0.0)
    set_lever_exact(chow_plugin, "tape_on_off", True)
    set_lever_exact(chow_plugin, "tape_drive", float(drive))
    set_lever_exact(chow_plugin, "tape_saturation", float(sat))
    set_lever_exact(chow_plugin, "tone_on_off", True)
    set_lever_exact(chow_plugin, "tone_bass", float(bass))
    set_lever_exact(chow_plugin, "tone_treble", float(treble))
    set_lever_exact(chow_plugin, "dry_wet", float(dry_wet))


def configure_mjucjr(mjuc_plugin, compress_db=22.0, makeup_db=2.0, timing_mode="fast"):
    """
    Applies verified C++ parameter keys to Klanghelm MJUCjr.vst3.
    """
    if mjuc_plugin is None:
        return
    set_lever_exact(mjuc_plugin, "compress", float(compress_db))
    set_lever_exact(mjuc_plugin, "makeup", float(makeup_db))
    set_lever_exact(mjuc_plugin, "timing", str(timing_mode))


def configure_tdr_nova(nova_plugin, role="Vocals"):
    """
    Applies verified C++ Dynamic EQ & Filter settings to TDR Nova.vst3
    tailored specifically for 'Vocals', 'Music', or 'Master'.
    """
    if nova_plugin is None:
        return

    if role == "Vocals":
        # 1. 95 Hz High-Pass Filter
        set_lever_exact(nova_plugin, "hp_active", True)
        set_lever_exact(nova_plugin, "hp_frequency_hz", 95.0)
        # 2. Band 1: Dynamic De-Box / De-Echo at 360 Hz
        set_lever_exact(nova_plugin, "band_1_active", True)
        set_lever_exact(nova_plugin, "band_1_frequency_hz", 360.0)
        set_lever_exact(nova_plugin, "band_1_q", 1.8)
        set_lever_exact(nova_plugin, "band_1_gain_db", -2.5)
        set_lever_exact(nova_plugin, "band_1_dyn", "On")
        set_lever_exact(nova_plugin, "band_1_threshold_db", -20.0)
        set_lever_exact(nova_plugin, "band_1_ratio", 2.5)
        # 3. Band 3: Dynamic Scream Bite Control at 3200 Hz (ducks only on loud peaks)
        set_lever_exact(nova_plugin, "band_3_active", True)
        set_lever_exact(nova_plugin, "band_3_frequency_hz", 3200.0)
        set_lever_exact(nova_plugin, "band_3_q", 2.2)
        set_lever_exact(nova_plugin, "band_3_gain_db", 0.0)
        set_lever_exact(nova_plugin, "band_3_dyn", "On")
        set_lever_exact(nova_plugin, "band_3_threshold_db", -18.0)
        set_lever_exact(nova_plugin, "band_3_ratio", 2.5)
        # 4. Band 4: Dynamic De-Esser / High-Sheen Tamer at 6500 Hz
        set_lever_exact(nova_plugin, "band_4_active", True)
        set_lever_exact(nova_plugin, "band_4_frequency_hz", 6500.0)
        set_lever_exact(nova_plugin, "band_4_q", 1.2)
        set_lever_exact(nova_plugin, "band_4_gain_db", 0.0)
        set_lever_exact(nova_plugin, "band_4_dyn", "On")
        set_lever_exact(nova_plugin, "band_4_threshold_db", -22.0)
        set_lever_exact(nova_plugin, "band_4_ratio", 3.0)

    elif role == "Music":
        # 1. 115 Hz High-Pass Filter to clear space for Kick & Bass
        set_lever_exact(nova_plugin, "hp_active", True)
        set_lever_exact(nova_plugin, "hp_frequency_hz", 115.0)
        # 2. Band 2: Dynamic Low-Mid Mud Control on Guitars/Synths at 320 Hz
        set_lever_exact(nova_plugin, "band_2_active", True)
        set_lever_exact(nova_plugin, "band_2_frequency_hz", 320.0)
        set_lever_exact(nova_plugin, "band_2_q", 1.4)
        set_lever_exact(nova_plugin, "band_2_gain_db", -1.5)
        set_lever_exact(nova_plugin, "band_2_dyn", "On")
        set_lever_exact(nova_plugin, "band_2_threshold_db", -18.0)
        set_lever_exact(nova_plugin, "band_2_ratio", 2.2)
        # 3. Band 3: Vocal Pocket Carve at 2200 Hz
        set_lever_exact(nova_plugin, "band_3_active", True)
        set_lever_exact(nova_plugin, "band_3_frequency_hz", 2200.0)
        set_lever_exact(nova_plugin, "band_3_q", 1.2)
        set_lever_exact(nova_plugin, "band_3_gain_db", -2.5)
        set_lever_exact(nova_plugin, "band_3_dyn", "On")
        set_lever_exact(nova_plugin, "band_3_threshold_db", -18.0)
        set_lever_exact(nova_plugin, "band_3_ratio", 2.0)

    elif role == "Master":
        # 1. 28 Hz Sub-Rumble High-Pass Filter
        set_lever_exact(nova_plugin, "hp_active", True)
        set_lever_exact(nova_plugin, "hp_frequency_hz", 28.0)
        # 2. Band 2: Gentle Dynamic Boxiness Control at 280 Hz
        set_lever_exact(nova_plugin, "band_2_active", True)
        set_lever_exact(nova_plugin, "band_2_frequency_hz", 280.0)
        set_lever_exact(nova_plugin, "band_2_q", 1.2)
        set_lever_exact(nova_plugin, "band_2_gain_db", 0.0)
        set_lever_exact(nova_plugin, "band_2_dyn", "On")
        set_lever_exact(nova_plugin, "band_2_threshold_db", -16.0)
        set_lever_exact(nova_plugin, "band_2_ratio", 1.6)
        # 3. Wideband Dynamic Glue across the full stereo master
        set_lever_exact(nova_plugin, "wide_band_dyn", True)
        set_lever_exact(nova_plugin, "wide_band_threshold_db", -16.0)
        set_lever_exact(nova_plugin, "wide_band_ratio", 1.5)


def build_hms_bus_chain(bus_category, vst3_status, preset_map=None, vocal_gate_db=-36.0):
    """
    Builds the Anti-Echo Dry Studio DSP chain for 'Vocals', 'Rhythm', or 'Music'
    using verified C++ VST3 parameter bindings.
    """
    print(f"[RUN] Building Anti-Echo DSP chain for bus: [{bus_category}]")
    board = Pedalboard()
    preset_map = preset_map or {}

    try:
        nova_path = vst3_status.get("TDR Nova.vst3")
        mjuc_path = vst3_status.get("MJUCjr.vst3")
        chow_path = vst3_status.get("CHOWTapeModel.vst3")

        if bus_category == "Vocals":
            board.append(HighpassFilter(cutoff_frequency_hz=95.0))
            print(f"[INFO]   Configuring Vocals NoiseGate Threshold = {float(vocal_gate_db):.1f} dB")
            board.append(NoiseGate(threshold_db=float(vocal_gate_db), ratio=2.5, attack_ms=2.0, release_ms=120.0))

            nova_inst = load_vst3_safe(nova_path, preset_map.get(("Vocals", "TDR Nova.vst3")))
            if nova_inst:
                configure_tdr_nova(nova_inst, role="Vocals")
                board.append(nova_inst)

            mjuc_inst = load_vst3_safe(mjuc_path, preset_map.get(("Vocals", "MJUCjr.vst3")))
            if mjuc_inst:
                configure_mjucjr(mjuc_inst, compress_db=22.0, makeup_db=2.0, timing_mode="fast")
                board.append(mjuc_inst)

            board.append(Compressor(threshold_db=-14.0, ratio=2.0, attack_ms=8.0, release_ms=90.0))
            board.append(Limiter(threshold_db=-1.0, release_ms=50.0))

        elif bus_category == "Rhythm":
            board.append(HighpassFilter(cutoff_frequency_hz=30.0))
            board.append(NoiseGate(threshold_db=-42.0, ratio=2.0, attack_ms=1.0, release_ms=90.0))

            chow_inst = load_vst3_safe(chow_path, preset_map.get(("Rhythm", "CHOWTapeModel.vst3")))
            if chow_inst:
                configure_chow_tape(chow_inst, drive=0.38, sat=0.45, dry_wet=45.0, bass=0.15, treble=0.10)
                board.append(chow_inst)

            board.append(Compressor(threshold_db=-14.0, ratio=3.5, attack_ms=15.0, release_ms=50.0))
            board.append(Limiter(threshold_db=-0.5, release_ms=40.0))

        elif bus_category == "Music":
            board.append(HighpassFilter(cutoff_frequency_hz=115.0))

            nova_inst = load_vst3_safe(nova_path, preset_map.get(("Music", "TDR Nova.vst3")))
            if nova_inst:
                configure_tdr_nova(nova_inst, role="Music")
                board.append(nova_inst)

            chow_inst = load_vst3_safe(chow_path, preset_map.get(("Music", "CHOWTapeModel.vst3")))
            if chow_inst:
                configure_chow_tape(chow_inst, drive=0.30, sat=0.35, dry_wet=35.0, bass=0.0, treble=0.08)
                board.append(chow_inst)

            board.append(Compressor(threshold_db=-15.0, ratio=2.0, attack_ms=20.0, release_ms=100.0))
            board.append(Limiter(threshold_db=-1.0, release_ms=50.0))

        print(f"[SUCCESS] [{bus_category}] Anti-Echo Chain ready ({len(board)} processors).")
        return board

    except Exception:
        print(f"[ERROR] Exception while assembling DSP chain for bus: {bus_category}")
        print(traceback.format_exc())
        return board


# ==============================================================================
# FUNCTION 5: GHOST STEM FILTER & MID/SIDE VOCAL BLEED SUPPRESSOR
# ==============================================================================
def filter_valid_bus_stems(bus_name, clean_wav_paths, min_rms_db=-50.0):
    """
    Inspects candidate *_CLEAN.wav files in a bus folder and:
    1. Rejects silent or ghost-echo residue stems whose RMS is below min_rms_db (-50 dB).
    2. Prevents summing a generic '*_Music_CLEAN.wav' composite stem if dedicated
       instrument stems (like '*_Guitars_CLEAN.wav' or '*_Synths_CLEAN.wav') exist.
    3. Prevents summing duplicate full '*_Vocals_CLEAN.wav' on top of '*_Lead_Vocals_CLEAN.wav'.
    """
    valid_stems = []
    print(f"[RUN] Auditing {len(clean_wav_paths)} candidate stem(s) in [{bus_name}] (Min RMS: {min_rms_db} dB)...")

    for path in clean_wav_paths:
        fname = os.path.basename(path)
        try:
            with AudioFile(path) as af:
                buf = af.read(af.frames)
            rms_val = np.sqrt(np.mean(buf.astype(np.float64) ** 2))
            rms_db = round(float(20 * np.log10(rms_val + 1e-9)), 2)

            if rms_db < min_rms_db:
                print(f"[INFO]   - SKIPPING Ghost/Silent Stem '{fname}' (RMS: {rms_db} dB < {min_rms_db} dB)")
                continue

            print(f"[SUCCESS] + KEEPING Active Stem '{fname}' (RMS: {rms_db} dB)")
            valid_stems.append(path)
        except Exception:
            print(f"[ERROR] Failed reading stem '{fname}':")
            print(traceback.format_exc())

    if bus_name == "Music" and len(valid_stems) > 1:
        specific_stems = [
            p for p in valid_stems
            if not re.search(r"_MUSIC(_\d+)?_CLEAN\.WAV$", os.path.basename(p).upper())
        ]
        if specific_stems and len(specific_stems) < len(valid_stems):
            print("[INFO]   - Dropping redundant composite '*_Music_CLEAN.wav' to prevent double-summing echo!")
            valid_stems = specific_stems

    if bus_name == "Vocals" and len(valid_stems) > 1:
        has_lead = any("LEAD_VOCALS" in os.path.basename(p).upper() for p in valid_stems)
        if has_lead:
            filtered_vox = [
                p for p in valid_stems
                if not re.search(r"_VOCALS(_\d+)?_CLEAN\.WAV$", os.path.basename(p).upper())
            ]
            if filtered_vox:
                print("[INFO]   - Dropping redundant composite '*_Vocals_CLEAN.wav' because Lead_Vocals is present!")
                valid_stems = filtered_vox

    return valid_stems


def suppress_vocal_bleed_in_music(music_buf, vocals_buf, sr):
    """
    Eliminates ghost vocal slapback echo hiding inside the Music/Guitars bus:
    Decomposes the stereo Music buffer into Mid (Center) and Side (Stereo Width),
    notches out vocal reverb boxiness (420 Hz & 1.8 kHz) strictly on the Mid channel,
    and attenuates center bleed by 2.5 dB while preserving wide stereo guitars.
    """
    print("[RUN] Applying Mid/Side Ghost-Vocal Echo Suppression to [Music] bus...")
    try:
        mid = 0.5 * (music_buf[0] + music_buf[1])
        side = 0.5 * (music_buf[0] - music_buf[1])

        mid_2d = np.ascontiguousarray(np.vstack([mid, mid]), dtype=np.float32)
        de_echo_eq = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=135.0),
            PeakFilter(cutoff_frequency_hz=420.0, gain_db=-4.0, q=1.4),
            PeakFilter(cutoff_frequency_hz=1800.0, gain_db=-3.5, q=1.2)
        ])
        mid_cleaned = de_echo_eq(mid_2d, sr)[0]

        mid_final = mid_cleaned * 0.75
        side_final = side * 1.10

        left_out = mid_final + side_final
        right_out = mid_final - side_final
        result = np.ascontiguousarray(np.vstack([left_out, right_out]), dtype=np.float32)
        print("[SUCCESS] Mid/Side Ghost-Vocal Echo Suppression applied to [Music] bus.")
        return result
    except Exception:
        print("[ERROR] Failed applying Mid/Side echo suppression, returning original buffer:")
        print(traceback.format_exc())
        return music_buf


# ==============================================================================
# FUNCTION 6: GLUED BUS SUMMING & MASTER MIXDOWN RENDERER
# ==============================================================================
def render_master_mixdown(dest_song_dir, song_name=None, vst3_status=None, bus_weights=None):
    """
    Filters out sub-50dB ghost stems and duplicate composites via filter_valid_bus_stems(),
    applies Mid/Side ghost-vocal bleed suppression to the Music bus, writes 24-bit
    *_GLUED.wav bus stems, and renders <Song_Name>_MASTER_MIX.wav.
    """
    t0 = time.time()
    norm_dest = os.path.normpath(dest_song_dir)
    if not song_name:
        song_name = os.path.basename(norm_dest)

    if vst3_status is None:
        vst3_status = resolve_vst3_binary_path()

    if bus_weights is None:
        bus_weights = {
            "Vocals": 1.18,
            "Rhythm": 0.92,
            "Music":  0.76
        }

    print("=" * 70)
    print(f"[RUN] Starting Headless Bus Glue & Master Mixdown for: {song_name}")
    print(f"[INFO] Target Song Dir : {norm_dest}")
    print(f"[INFO] Mix Weights     : Vocals={bus_weights.get('Vocals', 1.18):.2f} | "
          f"Rhythm={bus_weights.get('Rhythm', 0.92):.2f} | Music={bus_weights.get('Music', 0.76):.2f}")
    print("=" * 70)

    result = {
        "master_wav_path": None,
        "glued_bus_paths": [],
        "peak_db": None
    }

    try:
        if not os.path.exists(norm_dest):
            print(f"[ERROR] Destination song directory does not exist: {norm_dest}")
            return result

        bus_file_map = {}
        global_max_frames = 0
        target_sr = None

        for bus_name in ["Vocals", "Rhythm", "Music"]:
            bus_dir = os.path.join(norm_dest, bus_name)
            if not os.path.exists(bus_dir):
                continue

            all_wavs = sorted([f for f in os.listdir(bus_dir) if f.lower().endswith(".wav")])
            clean_wavs = [os.path.join(bus_dir, f) for f in all_wavs if f.upper().endswith("_CLEAN.WAV")]

            if not clean_wavs and all_wavs:
                print(f"[INFO] No *_CLEAN.wav found in [{bus_name}], falling back to {len(all_wavs)} sorted .wav file(s).")
                clean_wavs = [os.path.join(bus_dir, f) for f in all_wavs]

            if not clean_wavs:
                continue

            kept_wavs = filter_valid_bus_stems(bus_name, clean_wavs, min_rms_db=-50.0)
            if not kept_wavs:
                print(f"[INFO] No active stems above -50 dB threshold in [{bus_name}].")
                continue

            bus_file_map[bus_name] = kept_wavs

            for wav_path in kept_wavs:
                with AudioFile(wav_path) as af:
                    if target_sr is None:
                        target_sr = int(af.samplerate)
                    if af.frames > global_max_frames:
                        global_max_frames = int(af.frames)

        if not bus_file_map or global_max_frames == 0 or target_sr is None:
            print(f"[ERROR] No valid WAV stems found inside {norm_dest}\\Vocals, Rhythm, or Music!")
            return result

        bus_buffers = {}

        for bus_name, file_list in bus_file_map.items():
            print(f"[RUN] Gluing {len(file_list)} active stem(s) for [{bus_name}] bus...")
            bus_sum = np.zeros((2, global_max_frames), dtype=np.float32)

            for wav_path in file_list:
                with AudioFile(wav_path) as af:
                    buf = af.read(af.frames)

                if buf.ndim == 1 or buf.shape[0] == 1:
                    buf = np.vstack([buf, buf])
                elif buf.shape[0] > 2:
                    buf = buf[:2, :]

                n_frames = min(buf.shape[1], global_max_frames)
                bus_sum[:, :n_frames] += buf[:, :n_frames].astype(np.float32)

            if len(file_list) > 1:
                bus_sum *= 0.75

            bus_buffers[bus_name] = np.ascontiguousarray(bus_sum, dtype=np.float32)

        if "Music" in bus_buffers and "Vocals" in bus_buffers:
            bus_buffers["Music"] = suppress_vocal_bleed_in_music(
                bus_buffers["Music"], bus_buffers["Vocals"], target_sr
            )

        if "Vocals" in bus_buffers:
            print("[RUN] Applying post-glue tail gate (-30.0 dB) to [Vocals] bus...")
            vox_tightener = Pedalboard([
                NoiseGate(threshold_db=-30.0, ratio=3.0, attack_ms=1.5, release_ms=85.0)
            ])
            bus_buffers["Vocals"] = np.ascontiguousarray(
                vox_tightener(bus_buffers["Vocals"], target_sr), dtype=np.float32
            )

        for bus_name, b_buf in bus_buffers.items():
            glued_path = os.path.join(norm_dest, f"{song_name}_{bus_name}_GLUED.wav")
            with AudioFile(glued_path, "w", samplerate=target_sr, num_channels=2, bit_depth=24) as af_glue:
                af_glue.write(b_buf)
            result["glued_bus_paths"].append(glued_path)
            print(f"[SUCCESS] Wrote Glued Bus Stem -> {glued_path}")

        print(f"[RUN] Summing {len(bus_buffers)} buses into Master Stereo Mix ({global_max_frames} frames)...")
        master_raw = np.zeros((2, global_max_frames), dtype=np.float32)
        for bus_name, b_buf in bus_buffers.items():
            weight = float(bus_weights.get(bus_name, 1.0))
            master_raw += (b_buf * weight * 0.707)

        master_raw = np.ascontiguousarray(master_raw, dtype=np.float32)

        # Master Bus Finishing Chain with Verified TDR Nova & CHOWTapeModel Levers
        print("[RUN] Building Master Bus Finishing Chain...")
        master_chain = Pedalboard([HighpassFilter(cutoff_frequency_hz=28.0)])

        nova_master = load_vst3_safe(vst3_status.get("TDR Nova.vst3"))
        if nova_master:
            configure_tdr_nova(nova_master, role="Master")
            master_chain.append(nova_master)

        chow_master = load_vst3_safe(vst3_status.get("CHOWTapeModel.vst3"))
        if chow_master:
            configure_chow_tape(chow_master, drive=0.25, sat=0.30, dry_wet=25.0, bass=0.05, treble=0.05)
            master_chain.append(chow_master)

        master_chain.append(Compressor(threshold_db=-12.0, ratio=2.0, attack_ms=25.0, release_ms=120.0))
        master_chain.append(Gain(gain_db=1.0))
        master_chain.append(Limiter(threshold_db=-0.3, release_ms=40.0))

        print("[RUN] Rendering Master Stereo Buffer through Master Bus Chain...")
        master_finished = master_chain(master_raw, target_sr)
        master_finished = np.ascontiguousarray(master_finished, dtype=np.float32)

        master_wav_path = os.path.join(norm_dest, f"{song_name}_MASTER_MIX.wav")
        with AudioFile(master_wav_path, "w", samplerate=target_sr, num_channels=2, bit_depth=24) as af_master:
            af_master.write(master_finished)

        peak_db = round(float(20 * np.log10(np.max(np.abs(master_finished)) + 1e-9)), 2)
        elapsed = round(time.time() - t0, 2)

        result["master_wav_path"] = master_wav_path
        result["peak_db"] = peak_db

        print("=" * 70)
        print(f"[SUCCESS] MASTER MIX RENDERED in {elapsed}s! (Peak: {peak_db} dBFS)")
        print(f"          Master File : {master_wav_path}")
        print("=" * 70)
        return result

    except Exception:
        print(f"[ERROR] Failed rendering Master Mixdown in {norm_dest}:")
        print(traceback.format_exc())
        return result


# ==============================================================================
# FUNCTION 7: MASTER EXECUTION ENGINE (DRY-RUN + CLEANUP + MASTER RENDER)
# ==============================================================================
def execute_stem_cleanup(
    source_dir,
    dest_root=None,
    dry_run=True,
    move_source_files=False,
    render_master=True,
    preset_map=None,
    vst3_root=r"C:\Program Files\Common Files\VST3",
    vocal_gate_db=-36.0,
    bus_weights=None
):
    """
    Executes the complete HMS stem cleanup workflow using dynamic vocal_gate_db
    and bus_weights passed from the GUI sliders or CLI.
    """
    start_time = time.time()
    manifest = scan_and_plan_dry_run(source_dir, dest_root, vst3_root, vocal_gate_db=vocal_gate_db)

    summary = {
        "dry_run": dry_run,
        "song_name": manifest["song_name"],
        "dest_song_dir": manifest["dest_song_dir"],
        "queued_count": len(manifest["valid_stems"]),
        "processed_count": 0,
        "failed_count": 0,
        "rendered_files": [],
        "glued_bus_files": [],
        "master_wav_path": None
    }

    if dry_run:
        print(f"[INFO] Dry-Run mode active (dry_run=True). No files moved or rendered.")
        return summary

    if not manifest["valid_stems"]:
        print(f"[ERROR] No valid .wav stems found to process in: {source_dir}")
        return summary

    print("=" * 70)
    print(f"[RUN] Starting LIVE Headless DSP Cleanup for Song: {manifest['song_name']}")
    print("=" * 70)

    bus_chains = {}

    for item in manifest["valid_stems"]:
        bus = item["bus"]
        src_path = item["source_path"]
        dest_bus_dir = item["dest_bus_folder"]
        renamed_path = item["renamed_dest_path"]
        cleaned_path = item["cleaned_dest_path"]

        try:
            os.makedirs(dest_bus_dir, exist_ok=True)

            if os.path.abspath(src_path) != os.path.abspath(renamed_path):
                if move_source_files:
                    print(f"[RUN] Moving raw stem -> {renamed_path}")
                    shutil.move(src_path, renamed_path)
                else:
                    print(f"[RUN] Copying raw stem -> {renamed_path}")
                    shutil.copy2(src_path, renamed_path)

            if bus not in bus_chains:
                bus_chains[bus] = build_hms_bus_chain(
                    bus, manifest["vst3_status"], preset_map, vocal_gate_db=vocal_gate_db
                )
            chain = bus_chains[bus]

            t0 = time.time()
            with AudioFile(renamed_path) as af_in:
                audio_data = af_in.read(af_in.frames)
                sr = int(af_in.samplerate)
                num_channels = af_in.num_channels

            if audio_data.ndim == 1 or audio_data.shape[0] == 1:
                audio_data = np.vstack([audio_data, audio_data])
            elif audio_data.shape[0] > 2:
                audio_data = audio_data[:2, :]
            audio_data = np.ascontiguousarray(audio_data, dtype=np.float32)

            chain.reset()
            print(f"[RUN] Processing [{bus}] '{item['renamed_filename']}' ({sr} Hz, {num_channels} ch)...")
            effected_audio = chain(audio_data, sr)
            effected_audio = np.ascontiguousarray(effected_audio, dtype=np.float32)

            with AudioFile(cleaned_path, "w", samplerate=sr, num_channels=effected_audio.shape[0], bit_depth=24) as af_out:
                af_out.write(effected_audio)

            elapsed = round(time.time() - t0, 2)
            peak_db = 20 * np.log10(np.max(np.abs(effected_audio)) + 1e-9)
            print(f"[SUCCESS] Wrote 24-bit CLEAN stem in {elapsed}s (Peak: {peak_db:.2f} dBFS) -> {cleaned_path}")

            summary["processed_count"] += 1
            summary["rendered_files"].append(cleaned_path)

        except Exception:
            summary["failed_count"] += 1
            print(f"[ERROR] Failed processing stem: {src_path}")
            print(traceback.format_exc())

    if render_master and summary["processed_count"] > 0:
        master_res = render_master_mixdown(
            dest_song_dir=manifest["dest_song_dir"],
            song_name=manifest["song_name"],
            vst3_status=manifest["vst3_status"],
            bus_weights=bus_weights
        )
        summary["glued_bus_files"] = master_res.get("glued_bus_paths", [])
        summary["master_wav_path"] = master_res.get("master_wav_path")

    total_elapsed = round(time.time() - start_time, 2)
    print("=" * 70)
    print(f"[SUCCESS] HMS Live Cleanup & Master Render Finished in {total_elapsed}s!")
    print(f"          Cleaned Stems : {summary['processed_count']} | Failed: {summary['failed_count']}")
    print(f"          Glued Buses   : {len(summary['glued_bus_files'])}")
    print(f"          Master Mix    : {summary['master_wav_path']}")
    print("=" * 70)
    return summary


# ==============================================================================
# HELPER FOR VERIFICATION: GENERATE VALID STEREO WAV TEST FILES
# ==============================================================================
def _create_dummy_wav(filepath, freq_hz=220.0, duration_sec=1.5, sr=44100):
    """Writes a valid 16-bit stereo PCM WAV file for standalone pipeline testing."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    signal = (0.25 * np.sin(2 * np.pi * freq_hz * t) * 32767).astype(np.int16)
    stereo_interleaved = np.column_stack((signal, signal)).ravel()
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo_interleaved.tobytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS Standalone Headless Stem Cleanup & Master Mixdown Module")
    parser.add_argument("--source", type=str, default=None, help="Source song folder containing raw stems")
    parser.add_argument("--dest", type=str, default=None, help="Destination root folder")
    parser.add_argument("--live", action="store_true", help="Execute live file copy/move, VST3 stem cleanup, and Master Mixdown")
    parser.add_argument("--move", action="store_true", help="Move raw stems instead of copying them during --live run")
    parser.add_argument("--no-master", action="store_true", help="Skip rendering the glued buses and final Master Mix WAV")
    args = parser.parse_args()

    if args.source:
        execute_stem_cleanup(
            source_dir=args.source,
            dest_root=args.dest,
            dry_run=(not args.live),
            move_source_files=args.move,
            render_master=(not args.no_master)
        )
    else:
        print("=== HMS Headless DSP: Full End-to-End Self-Test (Dry-Run + Live + Master Mix) ===")
        test_song_dir = os.path.join(os.getcwd(), "hms_raw_input", "Sensory_Bleed")
        test_dest_root = os.path.join(os.getcwd(), "HMS_Cleaned_Output")
        os.makedirs(test_song_dir, exist_ok=True)

        test_stems = [
            ("84920_sensory_bleed_(Vocals).wav", 440.0),
            ("84920_sensory_bleed_(Drums).wav", 90.0),
            ("84920_sensory_bleed_(Bass).wav", 55.0),
            ("84920_sensory_bleed_(Other).wav", 330.0)
        ]
        for fname, freq in test_stems:
            _create_dummy_wav(os.path.join(test_song_dir, fname), freq_hz=freq)

        print("\n--- PHASE 1: DRY-RUN VERIFICATION ---")
        execute_stem_cleanup(source_dir=test_song_dir, dest_root=test_dest_root, dry_run=True)

        print("\n--- PHASE 2: LIVE CLEANUP + GLUED BUSES + MASTER MIX VERIFICATION ---")
        execute_stem_cleanup(
            source_dir=test_song_dir,
            dest_root=test_dest_root,
            dry_run=False,
            move_source_files=False,
            render_master=True
        )