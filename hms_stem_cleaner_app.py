# Save as: C:\github\projects\hms-stem-cleaner\hms_stem_cleaner_app.py
# Launch GUI   : python.exe C:\github\projects\hms-stem-cleaner\hms_stem_cleaner_app.py
# Self-Test    : python.exe C:\github\projects\hms-stem-cleaner\hms_stem_cleaner_app.py --test-layer2b

import os
import re
import sys
import json
import time
import wave
import shutil
import argparse
import threading
import traceback
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
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

DEFAULT_FL_PROJECTS_DIR = Path(r"C:\Users\racer\OneDrive\Documents\Image-Line\FL Studio\Projects")


# ==============================================================================
# LAYER 1A: PYINSTALLER-SAFE BASE DIRECTORY RESOLVER
# ==============================================================================
def get_app_base_dir():
    """
    Returns the directory containing the running .exe (when frozen by PyInstaller)
    or the directory containing this .py script (when running from Python).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ==============================================================================
# LAYER 1B: ATOMIC TEMP-FILE WAV WRITER (PREVENTS CORRUPTED RENDERS)
# ==============================================================================
def write_wav_atomic(target_wav_path, audio_buffer, samplerate, bit_depth=24):
    """
    Writes a stereo float32 NumPy buffer to a temporary staging file first,
    verifies non-zero byte integrity, and performs an OS-level atomic swap
    (os.replace) over target_wav_path so interrupted renders never corrupt files.
    """
    norm_target = os.path.normpath(target_wav_path)
    target_dir = os.path.dirname(norm_target)
    temp_wav_path = f"{norm_target}.tmp_{os.getpid()}.wav"

    print(f"[RUN] Atomic WAV Write staged -> {os.path.basename(norm_target)}")

    try:
        os.makedirs(target_dir, exist_ok=True)

        if audio_buffer.ndim == 1:
            audio_buffer = np.vstack([audio_buffer, audio_buffer])
        elif audio_buffer.shape[0] == 1:
            audio_buffer = np.vstack([audio_buffer, audio_buffer])
        elif audio_buffer.shape[0] > 2:
            audio_buffer = audio_buffer[:2, :]

        contiguous_buf = np.ascontiguousarray(audio_buffer, dtype=np.float32)

        with AudioFile(
            temp_wav_path,
            "w",
            samplerate=int(samplerate),
            num_channels=int(contiguous_buf.shape[0]),
            bit_depth=int(bit_depth)
        ) as af_temp:
            af_temp.write(contiguous_buf)

        if not os.path.exists(temp_wav_path) or os.path.getsize(temp_wav_path) <= 44:
            print(f"[ERROR] Staging WAV failed integrity check (<= 44 bytes): {temp_wav_path}")
            if os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)
            return False

        os.replace(temp_wav_path, norm_target)
        size_mb = round(os.path.getsize(norm_target) / (1024 * 1024), 2)
        print(f"[SUCCESS] Atomic WAV Committed ({size_mb} MB) -> {norm_target}")
        return True

    except Exception:
        print(f"[ERROR] Atomic WAV write failed for: {norm_target}")
        print(traceback.format_exc())
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except Exception:
                pass
        return False


# ==============================================================================
# LAYER 1C: PRE-FLIGHT SAFETY CHECKPOINT & ROLLBACK VAULT
# ==============================================================================
def create_song_checkpoint(song_dir, vault_root=None):
    """
    Creates a timestamped backup snapshot of all raw .wav stems in song_dir
    inside vault_root before any file moves or DSP overwrites happen.
    """
    if vault_root is None:
        vault_root = os.path.join(get_app_base_dir(), "_HMS_Rollback_Vault")

    norm_song_dir = os.path.normpath(song_dir)
    song_name = os.path.basename(norm_song_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir = os.path.join(os.path.normpath(vault_root), song_name, f"snapshot_{timestamp}")

    result = {
        "success": False,
        "song_name": song_name,
        "snapshot_dir": snapshot_dir,
        "file_count": 0
    }

    print("=" * 75)
    print(f"[RUN] Creating Pre-Flight Rollback Checkpoint for: {song_name}")
    print("=" * 75)

    if not os.path.exists(norm_song_dir):
        print(f"[ERROR] Source song folder does not exist: {norm_song_dir}")
        return result

    try:
        os.makedirs(snapshot_dir, exist_ok=True)
        backed_up_files = []

        for root, _, files in os.walk(norm_song_dir):
            rel_dir = os.path.relpath(root, norm_song_dir)
            target_sub = snapshot_dir if rel_dir == "." else os.path.join(snapshot_dir, rel_dir)

            for fname in sorted(files):
                upper_f = fname.upper()
                if upper_f.endswith(".WAV") and not any(
                    upper_f.endswith(tag) for tag in ["_CLEAN.WAV", "_GLUED.WAV", "_MASTER_MIX.WAV", "_NO_ECHO.WAV"]
                ):
                    os.makedirs(target_sub, exist_ok=True)
                    src_file = os.path.join(root, fname)
                    dst_file = os.path.join(target_sub, fname)
                    shutil.copy2(src_file, dst_file)
                    backed_up_files.append({
                        "relative_path": os.path.relpath(src_file, norm_song_dir),
                        "size_bytes": os.path.getsize(src_file)
                    })
                    print(f"[INFO]   + Vaulted raw stem: {fname}")

        manifest_path = os.path.join(snapshot_dir, "checkpoint_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump({
                "song_name": song_name,
                "original_song_dir": norm_song_dir,
                "timestamp": timestamp,
                "file_count": len(backed_up_files),
                "files": backed_up_files
            }, mf, indent=2)

        result["success"] = True
        result["file_count"] = len(backed_up_files)
        print(f"[SUCCESS] Checkpoint Locked ({len(backed_up_files)} stem(s)) -> {snapshot_dir}")
        return result

    except Exception:
        print(f"[ERROR] Failed creating safety checkpoint for {norm_song_dir}:")
        print(traceback.format_exc())
        return result


def restore_song_checkpoint(song_name, vault_root=None):
    """
    Restores the most recent safety checkpoint for song_name from vault_root
    back to its original directory byte-for-byte.
    """
    if vault_root is None:
        vault_root = os.path.join(get_app_base_dir(), "_HMS_Rollback_Vault")

    song_vault = os.path.join(os.path.normpath(vault_root), song_name)
    print("=" * 75)
    print(f"[RUN] Restoring Latest Rollback Checkpoint for: {song_name}")
    print("=" * 75)

    if not os.path.exists(song_vault):
        print(f"[ERROR] No rollback checkpoints found for '{song_name}' in: {song_vault}")
        return False

    try:
        snapshots = sorted([
            os.path.join(song_vault, d) for d in os.listdir(song_vault)
            if os.path.isdir(os.path.join(song_vault, d)) and d.startswith("snapshot_")
        ])
        if not snapshots:
            print(f"[ERROR] No snapshot folders inside: {song_vault}")
            return False

        latest_snap = snapshots[-1]
        manifest_path = os.path.join(latest_snap, "checkpoint_manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)

        orig_dir = manifest["original_song_dir"]
        restored = 0

        for item in manifest.get("files", []):
            rel_p = item["relative_path"]
            vault_src = os.path.join(latest_snap, rel_p)
            orig_dst = os.path.join(orig_dir, rel_p)
            if os.path.exists(vault_src):
                os.makedirs(os.path.dirname(orig_dst), exist_ok=True)
                shutil.copy2(vault_src, orig_dst)
                restored += 1
                print(f"[SUCCESS] Restored stem -> {orig_dst}")

        print(f"[SUCCESS] Rollback Complete! Restored {restored} file(s) from {latest_snap}")
        return True

    except Exception:
        print(f"[ERROR] Rollback recovery failed for '{song_name}':")
        print(traceback.format_exc())
        return False


# ==============================================================================
# LAYER 2A: VST3 BINARY RESOLVER, STEM TAGGER & VERIFIED C++ CONFIGURATORS
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
        print(f"[INFO] VST3 root folder not found (will use native Pedalboard DSP): {vst3_root}")
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


def load_vst3_safe(plugin_path, preset_path=None):
    """Safely loads a verified 64-bit VST3 binary path into Pedalboard."""
    if not plugin_path or not os.path.exists(plugin_path):
        print(f"[INFO] VST3 binary unavailable (skipping): {plugin_path}")
        return None

    try:
        print(f"[RUN] Loading VST3 binary: {os.path.basename(plugin_path)}...")
        plugin = load_plugin(plugin_path)
        print(f"[SUCCESS] Initialized VST3: {plugin.name}")

        if preset_path and os.path.exists(preset_path):
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
        return 0
    applied = 0
    levers = [
        ("wow_flutter_on_off", False),
        ("loss_on_off", False),
        ("flutter_depth", 0.0),
        ("wow_depth", 0.0),
        ("tape_on_off", True),
        ("tape_drive", float(drive)),
        ("tape_saturation", float(sat)),
        ("tone_on_off", True),
        ("tone_bass", float(bass)),
        ("tone_treble", float(treble)),
        ("dry_wet", float(dry_wet))
    ]
    for k, v in levers:
        if set_lever_exact(chow_plugin, k, v):
            applied += 1
    return applied


def configure_mjucjr(mjuc_plugin, compress_db=22.0, makeup_db=2.0, timing_mode="fast"):
    """Applies verified C++ parameter keys to Klanghelm MJUCjr.vst3."""
    if mjuc_plugin is None:
        return 0
    applied = 0
    for k, v in [("compress", float(compress_db)), ("makeup", float(makeup_db)), ("timing", str(timing_mode))]:
        if set_lever_exact(mjuc_plugin, k, v):
            applied += 1
    return applied


def configure_tdr_nova(nova_plugin, role="Vocals", pocket_gain_db=-2.5):
    """
    Applies verified C++ Dynamic EQ & Filter settings to TDR Nova.vst3
    tailored specifically for 'Vocals', 'Music', or 'Master'.
    """
    if nova_plugin is None:
        return 0
    applied = 0

    if role == "Vocals":
        levers = [
            ("hp_active", True), ("hp_frequency_hz", 95.0),
            ("band_1_active", True), ("band_1_frequency_hz", 360.0), ("band_1_q", 1.8),
            ("band_1_gain_db", -2.5), ("band_1_dyn", "On"), ("band_1_threshold_db", -20.0), ("band_1_ratio", 2.5),
            ("band_3_active", True), ("band_3_frequency_hz", 3200.0), ("band_3_q", 2.2),
            ("band_3_gain_db", 0.0), ("band_3_dyn", "On"), ("band_3_threshold_db", -18.0), ("band_3_ratio", 2.5),
            ("band_4_active", True), ("band_4_frequency_hz", 6500.0), ("band_4_q", 1.2),
            ("band_4_gain_db", 0.0), ("band_4_dyn", "On"), ("band_4_threshold_db", -22.0), ("band_4_ratio", 3.0)
        ]
    elif role == "Music":
        levers = [
            ("hp_active", True), ("hp_frequency_hz", 115.0),
            ("band_2_active", True), ("band_2_frequency_hz", 320.0), ("band_2_q", 1.4),
            ("band_2_gain_db", -1.5), ("band_2_dyn", "On"), ("band_2_threshold_db", -18.0), ("band_2_ratio", 2.2),
            ("band_3_active", True), ("band_3_frequency_hz", 2200.0), ("band_3_q", 1.2),
            ("band_3_gain_db", float(pocket_gain_db)), ("band_3_dyn", "On"), ("band_3_threshold_db", -18.0), ("band_3_ratio", 2.0)
        ]
    else:  # Master
        levers = [
            ("hp_active", True), ("hp_frequency_hz", 28.0),
            ("band_2_active", True), ("band_2_frequency_hz", 280.0), ("band_2_q", 1.2),
            ("band_2_gain_db", 0.0), ("band_2_dyn", "On"), ("band_2_threshold_db", -16.0), ("band_2_ratio", 1.6),
            ("wide_band_dyn", True), ("wide_band_threshold_db", -16.0), ("wide_band_ratio", 1.5)
        ]

    for k, v in levers:
        if set_lever_exact(nova_plugin, k, v):
            applied += 1
    return applied


# ==============================================================================
# LAYER 2B: DRY-RUN PLANNER, ANTI-ECHO DSP ENGINE, MASTER MIXER & AI AUTO-TUNER
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

    print("=" * 75)
    print(f"[RUN] Starting HMS Dry-Run Audit")
    print(f"[INFO] Source Directory : {norm_source}")
    print(f"[INFO] Detected Song    : {song_name}")
    print(f"[INFO] Dest Song Dir    : {dest_song_dir}")
    print(f"[INFO] Vocal Gate Level : {vocal_gate_db:.1f} dB")
    print("=" * 75)

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
                "MJUCjr(Variable-Mu)",
                "Compressor(2.0:1)",
                "Limiter(-1.0dB)"
            ],
            "Rhythm": [
                "HPF(30Hz)",
                "NoiseGate(-42dB)",
                "CHOWTape(LossOff/FlutterOff)",
                "Compressor(3.5:1)",
                "Limiter(-0.5dB)"
            ],
            "Music": [
                "HPF(115Hz)",
                "TDR Nova(DynEQ: 320Hz Mud + 2.2kHz VocalPocket)",
                "CHOWTape(LossOff/FlutterOff)",
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

        print(f"[SUCCESS] Dry-Run Audit Complete: {len(manifest['valid_stems'])} stem(s) mapped for '{song_name}'.")
        return manifest

    except Exception:
        print(f"[ERROR] Exception during dry-run scan of {norm_source}:")
        print(traceback.format_exc())
        return manifest


def build_hms_bus_chain(bus_category, vst3_status, preset_map=None, vocal_gate_db=-36.0, vst_overrides=None):
    """
    Builds the Anti-Echo Dry Studio DSP chain for 'Vocals', 'Rhythm', or 'Music'
    using verified C++ VST3 parameter bindings and optional AI overrides.
    """
    print(f"[RUN] Building Anti-Echo DSP chain for bus: [{bus_category}]")
    board = Pedalboard()
    preset_map = preset_map or {}
    vst_overrides = vst_overrides or {}

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
            else:
                board.append(PeakFilter(cutoff_frequency_hz=360.0, gain_db=-3.0, q=1.8))
                board.append(PeakFilter(cutoff_frequency_hz=4200.0, gain_db=-1.5, q=2.2))

            mjuc_inst = load_vst3_safe(mjuc_path, preset_map.get(("Vocals", "MJUCjr.vst3")))
            if mjuc_inst:
                comp_val = vst_overrides.get("mjuc_compress", 22.0)
                mkup_val = vst_overrides.get("mjuc_makeup", 2.0)
                configure_mjucjr(mjuc_inst, compress_db=comp_val, makeup_db=mkup_val, timing_mode="fast")
                board.append(mjuc_inst)

            board.append(Compressor(threshold_db=-14.0, ratio=2.0, attack_ms=8.0, release_ms=90.0))
            board.append(Limiter(threshold_db=-1.0, release_ms=50.0))

        elif bus_category == "Rhythm":
            board.append(HighpassFilter(cutoff_frequency_hz=30.0))
            board.append(NoiseGate(threshold_db=-42.0, ratio=2.0, attack_ms=1.0, release_ms=90.0))

            chow_inst = load_vst3_safe(chow_path, preset_map.get(("Rhythm", "CHOWTapeModel.vst3")))
            if chow_inst:
                r_drive = vst_overrides.get("chow_rhythm_drive", 0.38)
                configure_chow_tape(chow_inst, drive=r_drive, sat=0.45, dry_wet=45.0, bass=0.15, treble=0.10)
                board.append(chow_inst)

            board.append(Compressor(threshold_db=-14.0, ratio=3.5, attack_ms=15.0, release_ms=50.0))
            board.append(Limiter(threshold_db=-0.5, release_ms=40.0))

        elif bus_category == "Music":
            board.append(HighpassFilter(cutoff_frequency_hz=115.0))
            pocket_db = vst_overrides.get("nova_music_pocket_db", -2.5)

            nova_inst = load_vst3_safe(nova_path, preset_map.get(("Music", "TDR Nova.vst3")))
            if nova_inst:
                configure_tdr_nova(nova_inst, role="Music", pocket_gain_db=pocket_db)
                board.append(nova_inst)
            else:
                board.append(PeakFilter(cutoff_frequency_hz=2200.0, gain_db=float(pocket_db), q=1.2))

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


def filter_valid_bus_stems(bus_name, clean_wav_paths, min_rms_db=-50.0):
    """
    Rejects silent or ghost-echo residue stems (< -50 dB RMS) and drops
    redundant composite stems ('*_Music_CLEAN.wav' or '*_Vocals_CLEAN.wav')
    when specific stems ('Guitars', 'Lead_Vocals') are present.
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
    Decomposes the stereo Music buffer into Mid and Side, notches out center-channel
    vocal reverb bleed (420 Hz & 1.8 kHz), and attenuates Mid bleed by 2.5 dB.
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


def render_master_mixdown(dest_song_dir, song_name=None, vst3_status=None, bus_weights=None):
    """
    Filters out sub-50dB ghost stems, applies Mid/Side vocal-bleed suppression,
    atomically writes 24-bit *_GLUED.wav bus stems, and renders <Song_Name>_MASTER_MIX.wav.
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

    print("=" * 75)
    print(f"[RUN] Starting Headless Bus Glue & Master Mixdown for: {song_name}")
    print(f"[INFO] Target Song Dir : {norm_dest}")
    print(f"[INFO] Mix Weights     : Vocals={bus_weights.get('Vocals', 1.18):.2f} | "
          f"Rhythm={bus_weights.get('Rhythm', 0.92):.2f} | Music={bus_weights.get('Music', 0.76):.2f}")
    print("=" * 75)

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
            if write_wav_atomic(glued_path, b_buf, samplerate=target_sr, bit_depth=24):
                result["glued_bus_paths"].append(glued_path)

        print(f"[RUN] Summing {len(bus_buffers)} buses into Master Stereo Mix ({global_max_frames} frames)...")
        master_raw = np.zeros((2, global_max_frames), dtype=np.float32)
        for bus_name, b_buf in bus_buffers.items():
            weight = float(bus_weights.get(bus_name, 1.0))
            master_raw += (b_buf * weight * 0.707)

        master_raw = np.ascontiguousarray(master_raw, dtype=np.float32)

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
        master_finished = np.ascontiguousarray(master_chain(master_raw, target_sr), dtype=np.float32)

        master_wav_path = os.path.join(norm_dest, f"{song_name}_MASTER_MIX.wav")
        if write_wav_atomic(master_wav_path, master_finished, samplerate=target_sr, bit_depth=24):
            result["master_wav_path"] = master_wav_path

        peak_db = round(float(20 * np.log10(np.max(np.abs(master_finished)) + 1e-9)), 2)
        elapsed = round(time.time() - t0, 2)
        result["peak_db"] = peak_db

        print("=" * 75)
        print(f"[SUCCESS] MASTER MIX RENDERED in {elapsed}s! (Peak: {peak_db} dBFS)")
        print(f"          Master File : {master_wav_path}")
        print("=" * 75)
        return result

    except Exception:
        print(f"[ERROR] Failed rendering Master Mixdown in {norm_dest}:")
        print(traceback.format_exc())
        return result


def analyze_and_autotune_song(source_dir):
    """
    Scans raw .wav stems in source_dir, measures 25th-percentile vocal decay floor
    and guitar-to-vocal RMS differential, and returns auto-tuned GUI slider weights
    and VST3 parameter overrides.
    """
    norm_source = os.path.normpath(source_dir)
    song_name = os.path.basename(norm_source)
    print("=" * 75)
    print(f"[RUN] Running AI / Acoustic Telemetry Auto-Tuner on: {song_name}")
    print("=" * 75)

    profile = {
        "bus_weights": {"Vocals": 1.18, "Rhythm": 0.92, "Music": 0.76},
        "vocal_gate_db": -36.0,
        "vst_overrides": {
            "mjuc_compress": 22.0,
            "mjuc_makeup": 2.0,
            "chow_rhythm_drive": 0.38,
            "nova_music_pocket_db": -2.5
        },
        "ai_notes": []
    }

    if not os.path.exists(norm_source):
        print(f"[ERROR] Source folder not found for auto-tune: {norm_source}")
        return profile

    try:
        buses = {}
        for root, _, files in os.walk(norm_source):
            parent_folder = os.path.basename(root)
            for fname in sorted(files):
                upper_f = fname.upper()
                if upper_f.endswith(".WAV") and not any(
                    upper_f.endswith(t) for t in ["_CLEAN.WAV", "_GLUED.WAV", "_MASTER_MIX.WAV", "_NO_ECHO.WAV"]
                ):
                    wav_path = os.path.join(root, fname)
                    bus_cat, _, _ = extract_clean_stem_tag(fname, song_name, parent_folder)

                    with AudioFile(wav_path) as af:
                        sr = int(af.samplerate)
                        buf = af.read(af.frames)

                    if buf.ndim == 1 or buf.shape[0] == 1:
                        buf = np.vstack([buf, buf])
                    elif buf.shape[0] > 2:
                        buf = buf[:2, :]

                    rms_db = round(float(20 * np.log10(np.sqrt(np.mean(buf.astype(np.float64) ** 2)) + 1e-9)), 2)
                    if rms_db < -50.0:
                        continue

                    win_size = max(1, int(sr * 0.05))
                    mono = 0.5 * (buf[0] + buf[1])
                    n_wins = len(mono) // win_size
                    p25_tail_db, p85_body_db, spread_db = -48.0, rms_db, 15.0
                    if n_wins > 10:
                        framed = mono[:n_wins * win_size].reshape(n_wins, win_size)
                        win_rms_db = 20 * np.log10(np.sqrt(np.mean(framed ** 2, axis=1)) + 1e-9)
                        active = win_rms_db[win_rms_db > -55.0]
                        if len(active) > 5:
                            p25_tail_db = round(float(np.percentile(active, 25)), 2)
                            p85_body_db = round(float(np.percentile(active, 85)), 2)
                            spread_db = round(p85_body_db - p25_tail_db, 2)

                    prev = buses.get(bus_cat)
                    if prev is None or rms_db > prev["rms_db"]:
                        buses[bus_cat] = {
                            "rms_db": rms_db,
                            "p25_tail_db": p25_tail_db,
                            "spread_db": spread_db
                        }

        vox = buses.get("Vocals")
        mus = buses.get("Music")

        if vox:
            tail_db = vox["p25_tail_db"]
            if tail_db > -34.0 or vox["spread_db"] < 11.5:
                smart_gate = round(max(-32.0, min(-22.0, tail_db + 2.5)), 1)
                profile["vocal_gate_db"] = smart_gate
                profile["vst_overrides"]["mjuc_compress"] = 11.0
                profile["vst_overrides"]["mjuc_makeup"] = 1.0
                msg = f"High vocal echo tail ({tail_db} dB) -> Set Gate={smart_gate} dB, MJUCjr=11.0 dB"
            else:
                smart_gate = round(max(-40.0, min(-30.0, tail_db + 1.5)), 1)
                profile["vocal_gate_db"] = smart_gate
                profile["vst_overrides"]["mjuc_compress"] = 22.0
                msg = f"Clean vocal tail ({tail_db} dB) -> Set Gate={smart_gate} dB, MJUCjr=22.0 dB"
            profile["ai_notes"].append(msg)
            print(f"[SUCCESS] [AUTO-TUNE] {msg}")

        if vox and mus:
            diff = mus["rms_db"] - vox["rms_db"]
            if diff > 2.0:
                profile["bus_weights"] = {"Vocals": 1.22, "Rhythm": 0.92, "Music": 0.74}
                profile["vst_overrides"]["nova_music_pocket_db"] = -3.8
            elif diff < -2.0:
                profile["bus_weights"] = {"Vocals": 1.10, "Rhythm": 0.92, "Music": 0.82}
                profile["vst_overrides"]["nova_music_pocket_db"] = -2.2
            else:
                profile["bus_weights"] = {"Vocals": 1.18, "Rhythm": 0.92, "Music": 0.76}
                profile["vst_overrides"]["nova_music_pocket_db"] = -3.0
            print(f"[SUCCESS] [AUTO-TUNE] Bus Weights -> {profile['bus_weights']}")

        return profile

    except Exception:
        print("[ERROR] Auto-tune analysis failed:")
        print(traceback.format_exc())
        return profile


def execute_stem_cleanup(
    source_dir,
    dest_root=None,
    dry_run=True,
    move_source_files=False,
    render_master=True,
    preset_map=None,
    vst3_root=r"C:\Program Files\Common Files\VST3",
    vocal_gate_db=-36.0,
    bus_weights=None,
    vst_overrides=None
):
    """
    Executes the complete HMS stem cleanup workflow:
    1. Runs Dry-Run audit.
    2. Creates a pre-flight safety checkpoint in _HMS_Rollback_Vault.
    3. Processes stems through verified VST3 chains and commits via write_wav_atomic().
    4. Glues buses and renders the 24-bit Master Mix.
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

    create_song_checkpoint(source_dir)

    print("=" * 75)
    print(f"[RUN] Starting LIVE Headless DSP Cleanup for Song: {manifest['song_name']}")
    print("=" * 75)

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
                    bus,
                    manifest["vst3_status"],
                    preset_map=preset_map,
                    vocal_gate_db=vocal_gate_db,
                    vst_overrides=vst_overrides
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
            effected_audio = np.ascontiguousarray(chain(audio_data, sr), dtype=np.float32)

            if write_wav_atomic(cleaned_path, effected_audio, samplerate=sr, bit_depth=24):
                elapsed = round(time.time() - t0, 2)
                peak_db = 20 * np.log10(np.max(np.abs(effected_audio)) + 1e-9)
                print(f"[SUCCESS] Wrote 24-bit CLEAN stem in {elapsed}s (Peak: {peak_db:.2f} dBFS) -> {cleaned_path}")
                summary["processed_count"] += 1
                summary["rendered_files"].append(cleaned_path)
            else:
                summary["failed_count"] += 1

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
    print("=" * 75)
    print(f"[SUCCESS] HMS Live Cleanup & Master Render Finished in {total_elapsed}s!")
    print(f"          Cleaned Stems : {summary['processed_count']} | Failed: {summary['failed_count']}")
    print(f"          Glued Buses   : {len(summary['glued_bus_files'])}")
    print(f"          Master Mix    : {summary['master_wav_path']}")
    print("=" * 75)
    return summary


# ==============================================================================
# LAYER 3: UNIFIED TKINTER GUI WITH AI AUTO-TUNE & ROLLBACK BUTTONS
# ==============================================================================
class StatusBoxRedirector:
    """Streams print() logs into the Tkinter console while preserving stdout."""
    def __init__(self, text_widget, orig_stdout):
        self.text_widget = text_widget
        self.orig_stdout = orig_stdout

    def write(self, message):
        if self.orig_stdout:
            self.orig_stdout.write(message)
            self.orig_stdout.flush()
        if self.text_widget and message:
            self.text_widget.after(0, self._append, message)

    def _append(self, message):
        try:
            tag = "INFO"
            if "[ERROR]" in message:
                tag = "ERROR"
            elif "[SUCCESS]" in message:
                tag = "SUCCESS"
            elif "[DRY-RUN]" in message:
                tag = "DRYRUN"
            elif "[RUN]" in message:
                tag = "RUN"

            self.text_widget.insert(tk.END, message, tag)
            self.text_widget.see(tk.END)
        except Exception:
            pass

    def flush(self):
        if self.orig_stdout:
            self.orig_stdout.flush()


class HMSStudioSingleFileGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("337 West Productions - HMS Stem Cleaner & Headless VST3 Master Engine (v1.0)")
        self.root.geometry("920x780")
        self.root.configure(bg="#1e1e1e")

        default_out = str(DEFAULT_FL_PROJECTS_DIR) if DEFAULT_FL_PROJECTS_DIR.exists() else os.path.join(get_app_base_dir(), "HMS_Cleaned_Output")

        self.active_source_var = tk.StringVar(value="")
        self.dest_root_var = tk.StringVar(value=default_out)
        self.move_files_var = tk.BooleanVar(value=False)

        # Mix Balance & Gate Sliders
        self.vocals_weight_var = tk.DoubleVar(value=1.18)
        self.rhythm_weight_var = tk.DoubleVar(value=0.92)
        self.music_weight_var = tk.DoubleVar(value=0.76)
        self.vocal_gate_db_var = tk.DoubleVar(value=-36.0)
        self.vst_overrides = {}

        title_label = tk.Label(
            root,
            text="337 West - HMS Stem Sorter, Anti-Echo Cleaner & Headless VST3 Master Engine",
            fg="#00ff00",
            bg="#1e1e1e",
            font=("Arial", 13, "bold")
        )
        title_label.pack(pady=(10, 2))

        desc_label = tk.Label(
            root,
            text="Provided 'AS-IS' | Routes stems to <Dest>\\<Song_Name>\\<Vocals|Rhythm|Music>, cleans via C++ VST3s, and renders 24-bit Master.",
            fg="#cccccc",
            bg="#1e1e1e",
            font=("Arial", 9)
        )
        desc_label.pack(pady=(0, 6))

        # --- SECTION 1: DIRECTORY PATHS ---
        path_frame = tk.LabelFrame(
            root,
            text=" Active Directories ",
            bg="#1e1e1e",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        path_frame.pack(fill="x", padx=14, pady=4)

        tk.Label(path_frame, text="Source Song Dir:", bg="#1e1e1e", fg="#ffffff", font=("Consolas", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(path_frame, textvariable=self.active_source_var, width=78, bg="#111111", fg="#00ff00", insertbackground="#ffffff", font=("Consolas", 9)).grid(row=0, column=1, padx=6, pady=3)
        tk.Button(path_frame, text="Browse", command=self.browse_source_only, bg="#333333", fg="#ffffff", font=("Arial", 8)).grid(row=0, column=2)

        tk.Label(path_frame, text="Dest Root Dir  :", bg="#1e1e1e", fg="#ffffff", font=("Consolas", 9)).grid(row=1, column=0, sticky="w")
        tk.Entry(path_frame, textvariable=self.dest_root_var, width=78, bg="#111111", fg="#00ff00", insertbackground="#ffffff", font=("Consolas", 9)).grid(row=1, column=1, padx=6, pady=3)
        tk.Button(path_frame, text="Browse", command=self.browse_dest_only, bg="#333333", fg="#ffffff", font=("Arial", 8)).grid(row=1, column=2)

        # --- SECTION 2: QUICK FILE / FOLDER SORTER (NO DSP) ---
        sort_frame = tk.LabelFrame(
            root,
            text=" Quick File Rename & Subfolder Sort Only (No VST3 Render) ",
            bg="#1e1e1e",
            fg="#aaaaaa",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        sort_frame.pack(fill="x", padx=14, pady=4)

        tk.Button(
            sort_frame,
            text="Select Multiple WAV Files (Quick Sort)",
            command=self.select_files,
            bg="#333333",
            fg="#ffffff",
            font=("Arial", 9),
            width=42
        ).pack(side="left", padx=8, pady=4)

        tk.Button(
            sort_frame,
            text="Select Entire Folder (Quick Sort)",
            command=self.select_folder,
            bg="#333333",
            fg="#ffffff",
            font=("Arial", 9),
            width=42
        ).pack(side="left", padx=8, pady=4)

        # --- SECTION 3: LIVE MIX BALANCE & VOCAL GATE SLIDERS ---
        slider_frame = tk.LabelFrame(
            root,
            text=" Live Mix Balance & Anti-Echo Gate Levers (Manual or AI Auto-Tuned) ",
            bg="#1e1e1e",
            fg="#00d4ff",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        slider_frame.pack(fill="x", padx=14, pady=4)

        tk.Label(slider_frame, text="Vocals Level (Green):", bg="#1e1e1e", fg="#00ff66", font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(2, 6))
        tk.Scale(
            slider_frame, variable=self.vocals_weight_var, from_=0.50, to=1.60, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#00ff66", highlightthickness=0, troughcolor="#111111"
        ).grid(row=0, column=1, padx=4, pady=2)

        tk.Label(slider_frame, text="Rhythm Level (Red):", bg="#1e1e1e", fg="#ff5555", font=("Consolas", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(14, 6))
        tk.Scale(
            slider_frame, variable=self.rhythm_weight_var, from_=0.50, to=1.50, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#ff5555", highlightthickness=0, troughcolor="#111111"
        ).grid(row=0, column=3, padx=4, pady=2)

        tk.Label(slider_frame, text="Music Level (Blue)  :", bg="#1e1e1e", fg="#5bc0de", font=("Consolas", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(2, 6))
        tk.Scale(
            slider_frame, variable=self.music_weight_var, from_=0.40, to=1.40, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#5bc0de", highlightthickness=0, troughcolor="#111111"
        ).grid(row=1, column=1, padx=4, pady=2)

        tk.Label(slider_frame, text="Vocal Gate (dB)   :", bg="#1e1e1e", fg="#f0ad4e", font=("Consolas", 9, "bold")).grid(row=1, column=2, sticky="w", padx=(14, 6))
        tk.Scale(
            slider_frame, variable=self.vocal_gate_db_var, from_=-60.0, to=-18.0, resolution=1.0,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#f0ad4e", highlightthickness=0, troughcolor="#111111"
        ).grid(row=1, column=3, padx=4, pady=2)

        side_btn_col = tk.Frame(slider_frame, bg="#1e1e1e")
        side_btn_col.grid(row=0, column=4, rowspan=2, padx=(12, 2))

        self.btn_autotune = tk.Button(
            side_btn_col,
            text="0. AI AUTO-TUNE",
            command=self.run_ai_autotune,
            bg="#6f42c1",
            fg="#ffffff",
            activebackground="#8558d6",
            font=("Consolas", 8, "bold"),
            width=16,
            pady=3
        )
        self.btn_autotune.pack(pady=(0, 4))

        tk.Button(
            side_btn_col,
            text="Reset Defaults",
            command=self.reset_slider_defaults,
            bg="#333333",
            fg="#ffffff",
            font=("Consolas", 8),
            width=16,
            pady=2
        ).pack()

        # --- SECTION 4: HEADLESS VST3 CLEANUP, MASTERING & ROLLBACK ---
        dsp_frame = tk.LabelFrame(
            root,
            text=" Headless VST3 Cleanup, Atomic Master Mixdown & Rollback Vault ",
            bg="#1e1e1e",
            fg="#00ff00",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=8
        )
        dsp_frame.pack(fill="x", padx=14, pady=4)

        top_ctrl = tk.Frame(dsp_frame, bg="#1e1e1e")
        top_ctrl.pack(fill="x", pady=(0, 6))

        tk.Checkbutton(
            top_ctrl,
            text="Move Raw Stems (instead of Copy — Auto-Backed Up in Rollback Vault)",
            variable=self.move_files_var,
            bg="#1e1e1e",
            fg="#dddddd",
            selectcolor="#111111",
            activebackground="#1e1e1e",
            activeforeground="#ffffff",
            font=("Consolas", 9)
        ).pack(side="left", padx=4)

        btn_row = tk.Frame(dsp_frame, bg="#1e1e1e")
        btn_row.pack(fill="x")

        self.btn_dry_run = tk.Button(
            btn_row,
            text="1. DRY-RUN AUDIT",
            command=lambda: self.run_headless_dsp(dry_run=True),
            bg="#2d5a88",
            fg="#ffffff",
            activebackground="#3d7ab8",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=5
        )
        self.btn_dry_run.pack(side="left", padx=4)

        self.btn_live_clean = tk.Button(
            btn_row,
            text="2. FULL LIVE CLEAN + MASTER (24-BIT)",
            command=lambda: self.run_headless_dsp(dry_run=False),
            bg="#1f7a3f",
            fg="#ffffff",
            activebackground="#2ca356",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=5
        )
        self.btn_live_clean.pack(side="left", padx=4)

        self.btn_master_only = tk.Button(
            btn_row,
            text="3. GLUE BUSES & MASTER ONLY",
            command=self.run_master_only,
            bg="#8a4b0f",
            fg="#ffffff",
            activebackground="#b86514",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=5
        )
        self.btn_master_only.pack(side="left", padx=4)

        self.btn_rollback = tk.Button(
            btn_row,
            text="4. ROLLBACK CHECKPOINT",
            command=self.run_rollback_recovery,
            bg="#8b1e1e",
            fg="#ffffff",
            activebackground="#b32626",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=5
        )
        self.btn_rollback.pack(side="left", padx=4)

        # --- SECTION 5: STATUS DISPLAY BOX ---
        self.status_box = tk.Text(
            root,
            height=15,
            width=106,
            bg="#111111",
            fg="#00ff00",
            font=("Consolas", 9)
        )
        self.status_box.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        self.status_box.tag_config("INFO", foreground="#cccccc")
        self.status_box.tag_config("RUN", foreground="#5bc0de")
        self.status_box.tag_config("DRYRUN", foreground="#f0ad4e")
        self.status_box.tag_config("SUCCESS", foreground="#00ff00")
        self.status_box.tag_config("ERROR", foreground="#ff5555")

        sys.stdout = StatusBoxRedirector(self.status_box, sys.__stdout__)

        self.log_status(
            f"[INFO] HMS Single-File Engine Ready! Base Dir: {get_app_base_dir()}\n"
            "[INFO] Sliders pre-tuned to Vocals=1.18, Rhythm=0.92, Music=0.76, Gate=-36.0 dB.\n"
        )

    def _set_buttons_state(self, state: str):
        for btn in (self.btn_autotune, self.btn_dry_run, self.btn_live_clean, self.btn_master_only, self.btn_rollback):
            btn.configure(state=state)

    def reset_slider_defaults(self):
        self.vocals_weight_var.set(1.18)
        self.rhythm_weight_var.set(0.92)
        self.music_weight_var.set(0.76)
        self.vocal_gate_db_var.set(-36.0)
        self.vst_overrides = {}
        self.log_status("[INFO] Reset sliders to defaults: Vocals=1.18, Rhythm=0.92, Music=0.76, Gate=-36.0 dB\n")

    def get_current_bus_weights(self) -> dict:
        return {
            "Vocals": round(float(self.vocals_weight_var.get()), 2),
            "Rhythm": round(float(self.rhythm_weight_var.get()), 2),
            "Music":  round(float(self.music_weight_var.get()), 2)
        }

    def browse_source_only(self):
        folder = filedialog.askdirectory(title="Select Source Song Stem Folder")
        if folder:
            self.active_source_var.set(folder)
            self.log_status(f"[INFO] Active Source Song Folder set to: {folder}\n")

    def browse_dest_only(self):
        folder = filedialog.askdirectory(title="Select Destination Root Folder")
        if folder:
            self.dest_root_var.set(folder)
            self.log_status(f"[INFO] Destination Root Folder set to: {folder}\n")

    def sanitize_song_name(self, raw_folder_name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", raw_folder_name).strip("_")
        return cleaned if cleaned else "Untitled_Song"

    def clean_filename(self, filename: str, song_name: str = "") -> str:
        name, ext = os.path.splitext(filename)
        name = re.sub(r"\s*\[.*?\]", "", name)
        name = re.sub(r"\s*\(.*?\)", lambda m: "_" + m.group(0).strip(" ()"), name)
        name = re.sub(r"^[0-9]+_[a-fA-F0-9]+_", "", name)
        name = re.sub(r"_[a-fA-F0-9]{8,}", "", name)
        name = re.sub(r"__+", "_", name).strip("_-_ ")
        if song_name and not name.lower().startswith(song_name.lower()):
            name = f"{song_name}_{name}"
        return f"{name}{ext}"

    def determine_subfolder(self, filename: str) -> str:
        lower_name = filename.lower()
        if any(k in lower_name for k in ["vocal", "vocals", "vox", "acapella", "lead", "backing"]):
            return "Vocals"
        elif any(k in lower_name for k in ["drum", "drums", "rhythm", "bass", "percussion", "kick", "snare"]):
            return "Rhythm"
        else:
            return "Music"

    def process_file_path(self, file_path_str):
        file_path = Path(file_path_str)
        if file_path.suffix.lower() == ".wav":
            original_name = file_path.name
            song_name = self.sanitize_song_name(file_path.parent.name)
            cleaned_name = self.clean_filename(original_name, song_name)

            subfolder_name = self.determine_subfolder(original_name)
            dest_root = Path(self.dest_root_var.get().strip() or os.path.join(get_app_base_dir(), "HMS_Cleaned_Output"))
            target_dir = dest_root / song_name / subfolder_name

            target_dir.mkdir(parents=True, exist_ok=True)
            dest_path = target_dir / cleaned_name

            try:
                if self.move_files_var.get():
                    shutil.move(str(file_path), str(dest_path))
                    self.log_status(f"[SUCCESS] [{song_name}/{subfolder_name}] Moved: {cleaned_name}\n")
                else:
                    shutil.copy2(file_path, dest_path)
                    self.log_status(f"[SUCCESS] [{song_name}/{subfolder_name}] Copied: {cleaned_name}\n")
            except Exception as e:
                self.log_status(f"[ERROR] Failed on {original_name}: {e}\n")

    def select_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select MVSep Stems",
            filetypes=[("WAV Audio Files", "*.wav")]
        )
        if file_paths:
            first_parent = str(Path(file_paths[0]).parent)
            self.active_source_var.set(first_parent)
            create_song_checkpoint(first_parent)
            self.log_status(f"[RUN] --- Quick-Sorting {len(file_paths)} selected files ---\n")
            for fp in file_paths:
                self.process_file_path(fp)
            messagebox.showinfo("Success", "Stems renamed and sorted into <Song_Name>\\<Bus> subfolders!")

    def select_folder(self):
        folder_path = filedialog.askdirectory(title="Select MVSep Export Folder")
        if folder_path:
            self.active_source_var.set(folder_path)
            create_song_checkpoint(folder_path)
            folder = Path(folder_path)
            wav_files = list(folder.glob("*.wav"))
            self.log_status(f"[RUN] --- Quick-Sorting folder: {folder.name} ({len(wav_files)} files) ---\n")
            for fp in wav_files:
                self.process_file_path(str(fp))
            messagebox.showinfo("Success", f"Stems sorted into {folder.name}\\Vocals, Rhythm, and Music subfolders!")

    def run_ai_autotune(self):
        source_dir = self.active_source_var.get().strip()
        if not source_dir:
            picked = filedialog.askdirectory(title="Select Song Folder to AI Auto-Tune")
            if not picked:
                return
            source_dir = picked
            self.active_source_var.set(source_dir)

        self._set_buttons_state("disabled")

        def _worker():
            try:
                profile = analyze_and_autotune_song(source_dir)
                bw = profile["bus_weights"]
                gate = profile["vocal_gate_db"]
                self.vst_overrides = profile.get("vst_overrides", {})

                def _apply_ui():
                    self.vocals_weight_var.set(bw["Vocals"])
                    self.rhythm_weight_var.set(bw["Rhythm"])
                    self.music_weight_var.set(bw["Music"])
                    self.vocal_gate_db_var.set(gate)
                    messagebox.showinfo(
                        "AI Auto-Tune Complete",
                        f"Sliders & VST3 Overrides Updated:\n\n"
                        f"Vocals Weight : {bw['Vocals']}\n"
                        f"Rhythm Weight : {bw['Rhythm']}\n"
                        f"Music Weight  : {bw['Music']}\n"
                        f"Vocal Gate    : {gate} dB\n"
                        f"MJUCjr Comp   : {self.vst_overrides.get('mjuc_compress', 22.0)} dB"
                    )

                self.root.after(0, _apply_ui)
            except Exception:
                print("[ERROR] Unhandled exception in AI Auto-Tuner:")
                print(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_buttons_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def run_headless_dsp(self, dry_run=True):
        source_dir = self.active_source_var.get().strip()
        dest_root = self.dest_root_var.get().strip() or os.path.join(get_app_base_dir(), "HMS_Cleaned_Output")
        move_files = self.move_files_var.get()
        vocal_gate = float(self.vocal_gate_db_var.get())
        weights = self.get_current_bus_weights()

        if not source_dir:
            picked = filedialog.askdirectory(title="Select Song Folder for Headless VST3 Cleanup")
            if not picked:
                return
            source_dir = picked
            self.active_source_var.set(source_dir)

        if not os.path.exists(source_dir):
            messagebox.showerror("Error", f"Source folder does not exist:\n{source_dir}")
            return

        self._set_buttons_state("disabled")

        def _worker():
            try:
                summary = execute_stem_cleanup(
                    source_dir=source_dir,
                    dest_root=dest_root,
                    dry_run=dry_run,
                    move_source_files=move_files,
                    render_master=True,
                    vocal_gate_db=vocal_gate,
                    bus_weights=weights,
                    vst_overrides=self.vst_overrides
                )
                if not dry_run and summary.get("processed_count", 0) > 0:
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "HMS VST3 Cleanup & Master Complete",
                            f"Song: {summary['song_name']}\n"
                            f"Cleaned 24-Bit Stems: {summary['processed_count']}\n"
                            f"Mix Weights: V={weights['Vocals']} | R={weights['Rhythm']} | M={weights['Music']}\n"
                            f"Master File:\n{summary.get('master_wav_path')}"
                        )
                    )
            except Exception:
                print("[ERROR] Unhandled exception in Headless VST3 Worker:")
                print(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_buttons_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def run_master_only(self):
        dest_root = self.dest_root_var.get().strip() or os.path.join(get_app_base_dir(), "HMS_Cleaned_Output")
        source_dir = self.active_source_var.get().strip()
        weights = self.get_current_bus_weights()

        candidate_song_dir = None
        if source_dir:
            song_name = self.sanitize_song_name(os.path.basename(os.path.normpath(source_dir)))
            possible_path = os.path.join(dest_root, song_name)
            if os.path.exists(possible_path):
                candidate_song_dir = possible_path

        if not candidate_song_dir:
            init_dir = dest_root if os.path.exists(dest_root) else get_app_base_dir()
            picked = filedialog.askdirectory(
                initialdir=init_dir,
                title="Select Processed Song Folder (Containing Vocals / Rhythm / Music)"
            )
            if not picked:
                return
            candidate_song_dir = picked

        self._set_buttons_state("disabled")

        def _worker():
            try:
                res = render_master_mixdown(
                    dest_song_dir=candidate_song_dir,
                    bus_weights=weights
                )
                if res.get("master_wav_path"):
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Master Mixdown Complete",
                            f"Mix Weights: V={weights['Vocals']} | R={weights['Rhythm']} | M={weights['Music']}\n"
                            f"Peak Level: {res.get('peak_db')} dBFS\n"
                            f"Master File:\n{res.get('master_wav_path')}"
                        )
                    )
            except Exception:
                print("[ERROR] Unhandled exception in Master Mixdown Worker:")
                print(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_buttons_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def run_rollback_recovery(self):
        vault_root = os.path.join(get_app_base_dir(), "_HMS_Rollback_Vault")
        source_dir = self.active_source_var.get().strip()
        song_name = None

        if source_dir:
            song_name = os.path.basename(os.path.normpath(source_dir))
            if not os.path.exists(os.path.join(vault_root, song_name)):
                song_name = None

        if not song_name:
            if not os.path.exists(vault_root):
                messagebox.showinfo("Rollback Vault", f"No checkpoints exist yet in:\n{vault_root}")
                return
            picked = filedialog.askdirectory(
                initialdir=vault_root,
                title="Select Song Folder Inside _HMS_Rollback_Vault to Restore"
            )
            if not picked:
                return
            song_name = os.path.basename(os.path.normpath(picked))

        ok = restore_song_checkpoint(song_name, vault_root=vault_root)
        if ok:
            messagebox.showinfo("Rollback Complete", f"Restored latest checkpoint for '{song_name}'!")
        else:
            messagebox.showerror("Rollback Failed", f"Could not restore checkpoint for '{song_name}'. Check console log.")

    def log_status(self, message):
        self.status_box.insert(tk.END, message)
        self.status_box.see(tk.END)


# ==============================================================================
# ISOLATED VERIFICATION DRIVERS (CLI FLAGS)
# ==============================================================================
def _create_dummy_wav(filepath, freq_hz=220.0, duration_sec=1.2, sr=44100, gain=0.25):
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    signal = (gain * np.sin(2 * np.pi * freq_hz * t) * 32767).astype(np.int16)
    stereo_interleaved = np.column_stack((signal, signal)).ravel()
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo_interleaved.tobytes())


def _verify_layer2b_full_dsp_pipeline():
    print("=== HMS Single-File App: Full Headless DSP Verification ===")
    base_dir = get_app_base_dir()
    test_raw_dir = os.path.join(base_dir, "_layer2b_raw_in", "Test_Track")
    test_out_root = os.path.join(base_dir, "_layer2b_clean_out")
    os.makedirs(test_raw_dir, exist_ok=True)

    _create_dummy_wav(os.path.join(test_raw_dir, "01_Test_(Vocals).wav"), freq_hz=440.0, gain=0.25)
    _create_dummy_wav(os.path.join(test_raw_dir, "02_Test_(Drums).wav"), freq_hz=90.0, gain=0.25)
    _create_dummy_wav(os.path.join(test_raw_dir, "03_Test_(Guitars).wav"), freq_hz=330.0, gain=0.25)
    _create_dummy_wav(os.path.join(test_raw_dir, "04_Test_(Woodwinds).wav"), freq_hz=600.0, gain=0.000001)

    profile = analyze_and_autotune_song(test_raw_dir)
    res = execute_stem_cleanup(
        source_dir=test_raw_dir,
        dest_root=test_out_root,
        dry_run=False,
        move_source_files=False,
        render_master=True,
        vocal_gate_db=profile["vocal_gate_db"],
        bus_weights=profile["bus_weights"],
        vst_overrides=profile["vst_overrides"]
    )
    assert res["master_wav_path"] and os.path.exists(res["master_wav_path"])

    shutil.rmtree(os.path.join(base_dir, "_layer2b_raw_in"), ignore_errors=True)
    shutil.rmtree(test_out_root, ignore_errors=True)
    shutil.rmtree(os.path.join(base_dir, "_HMS_Rollback_Vault", "Test_Track"), ignore_errors=True)
    print("[SUCCESS] FULL HEADLESS ENGINE VERIFICATION PASSED 100%!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS Stem Cleaner Single-File Application")
    parser.add_argument("--source", type=str, default=None, help="Run headless CLI cleanup on source folder")
    parser.add_argument("--dest", type=str, default=None, help="Destination root folder for CLI mode")
    parser.add_argument("--live", action="store_true", help="Execute live render in CLI mode")
    parser.add_argument("--test-layer2b", action="store_true", help="Run full headless verification self-test")
    args = parser.parse_args()

    if args.test_layer2b:
        _verify_layer2b_full_dsp_pipeline()
    elif args.source:
        execute_stem_cleanup(
            source_dir=args.source,
            dest_root=args.dest,
            dry_run=(not args.live),
            render_master=True
        )
    else:
        root_win = tk.Tk()
        app_gui = HMSStudioSingleFileGUI(root_win)
        root_win.mainloop()