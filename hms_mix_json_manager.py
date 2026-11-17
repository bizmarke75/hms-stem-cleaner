import json
import os
import time
import traceback

# Default 9-lever mixer and VST3 configuration
DEFAULT_MIX_PRESET = {
    "mix_style": "heavy",
    "vocal_gate_db": -33.0,
    "bus_weights": {
        "Vocals": 1.08,
        "Rhythm": 1.04,
        "Music": 0.90,
    },
    "vst_overrides": {
        "nova_music_pocket_db": -2.5,
        "mjuc_compress": 18.0,
        "mjuc_makeup": 1.5,
        "chow_rhythm_drive": 0.35,
        "master_ceiling_db": -0.3,
    },
}


def save_song_mix_json(
    song_dir,
    bus_weights=None,
    vocal_gate_db=-33.0,
    mix_style="heavy",
    vst_overrides=None,
    log_callback=print,
):
    """
    Atomically saves all active slider weights, vocal gate threshold, and VST3 lever
    overrides to <Song_Name>_MIX_SETTINGS.json inside song_dir.
    """
    log_callback("=" * 65)
    log_callback(f"[RUN] Saving Mix Settings JSON for folder: {song_dir}")

    if not song_dir or not os.path.isdir(song_dir):
        log_callback(f"[ERROR] Invalid or missing song directory: {song_dir}")
        return None

    try:
        # Derive clean song prefix from the target directory name
        song_name = os.path.basename(os.path.normpath(song_dir))
        json_filename = f"{song_name}_MIX_SETTINGS.json"
        target_json_path = os.path.join(song_dir, json_filename)

        # Merge caller arguments with safe defaults so no key is ever missing
        merged_weights = dict(DEFAULT_MIX_PRESET["bus_weights"])
        if isinstance(bus_weights, dict):
            for k in ("Vocals", "Rhythm", "Music"):
                if k in bus_weights:
                    merged_weights[k] = round(float(bus_weights[k]), 3)

        merged_vst = dict(DEFAULT_MIX_PRESET["vst_overrides"])
        if isinstance(vst_overrides, dict):
            for k, v in vst_overrides.items():
                if v is not None:
                    merged_vst[k] = round(float(v), 3)

        payload = {
            "song_name": song_name,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mix_style": str(mix_style or "heavy").strip().lower(),
            "vocal_gate_db": round(float(vocal_gate_db), 2),
            "bus_weights": merged_weights,
            "vst_overrides": merged_vst,
        }

        # Atomic write using a temporary file swap to prevent corrupted JSON files
        temp_path = target_json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(temp_path, target_json_path)

        log_callback(f"[SUCCESS] Auto-saved Mix Settings JSON -> {target_json_path}")
        return target_json_path

    except Exception:
        log_callback("[ERROR] Failed to save song mix JSON:")
        log_callback(traceback.format_exc())
        return None


def load_song_mix_json(json_or_song_path, log_callback=print):
    """
    Loads a <Song_Name>_MIX_SETTINGS.json preset from either a direct .json file path
    or by scanning a song directory for the most recent *_MIX_SETTINGS.json file.
    """
    log_callback("=" * 65)
    log_callback(f"[RUN] Loading Mix Settings JSON from: {json_or_song_path}")

    if not json_or_song_path or not os.path.exists(json_or_song_path):
        log_callback(f"[ERROR] Path does not exist: {json_or_song_path}")
        return None

    try:
        target_json = None
        if os.path.isfile(json_or_song_path) and json_or_song_path.lower().endswith(".json"):
            target_json = json_or_song_path
        elif os.path.isdir(json_or_song_path):
            # Look for *_MIX_SETTINGS.json inside the song folder
            candidates = [
                os.path.join(json_or_song_path, f)
                for f in os.listdir(json_or_song_path)
                if f.lower().endswith("_mix_settings.json")
            ]
            if candidates:
                target_json = max(candidates, key=os.path.getmtime)

        if not target_json or not os.path.isfile(target_json):
            log_callback("[ERROR] No *_MIX_SETTINGS.json file found at target path.")
            return None

        with open(target_json, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        # Validate and normalize all loaded fields against DEFAULT_MIX_PRESET
        loaded_weights = dict(DEFAULT_MIX_PRESET["bus_weights"])
        for k in ("Vocals", "Rhythm", "Music"):
            if k in raw_data.get("bus_weights", {}):
                loaded_weights[k] = round(float(raw_data["bus_weights"][k]), 3)

        loaded_vst = dict(DEFAULT_MIX_PRESET["vst_overrides"])
        for k, v in raw_data.get("vst_overrides", {}).items():
            if v is not None:
                loaded_vst[k] = round(float(v), 3)

        result = {
            "json_path": target_json,
            "song_name": raw_data.get("song_name", "Unknown"),
            "mix_style": str(raw_data.get("mix_style", "heavy")).strip().lower(),
            "vocal_gate_db": round(
                float(raw_data.get("vocal_gate_db", DEFAULT_MIX_PRESET["vocal_gate_db"])), 2
            ),
            "bus_weights": loaded_weights,
            "vst_overrides": loaded_vst,
        }

        log_callback(
            f"[SUCCESS] Loaded Mix JSON ({os.path.basename(target_json)}): "
            f"Weights={result['bus_weights']} | Gate={result['vocal_gate_db']} dB"
        )
        return result

    except Exception:
        log_callback("[ERROR] Failed to load song mix JSON:")
        log_callback(traceback.format_exc())
        return None


if __name__ == "__main__":
    # Isolated verification test driver
    import tempfile

    print("[INFO] Running isolated verification for hms_mix_json_manager.py...")
    with tempfile.TemporaryDirectory(prefix="End_of_the_Bloodline_Stems_") as tmp_dir:
        saved_path = save_song_mix_json(
            song_dir=tmp_dir,
            bus_weights={"Vocals": 1.08, "Rhythm": 1.04, "Music": 0.90},
            vocal_gate_db=-33.0,
            mix_style="heavy",
            vst_overrides={"nova_music_pocket_db": -2.8, "chow_rhythm_drive": 0.40},
        )
        loaded_dict = load_song_mix_json(tmp_dir)
        assert loaded_dict is not None, "Failed to load saved JSON!"
        assert loaded_dict["bus_weights"]["Music"] == 0.90, "Music weight mismatch!"
        print("[SUCCESS] Isolated JSON Save/Load verification passed 100%!")