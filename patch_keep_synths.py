# Save as: C:\github\projects\hms-stem-cleaner\patch_keep_synths.py
# Run in PowerShell: python.exe .\patch_keep_synths.py

import os
import sys
import traceback

REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
APP_SCRIPT = os.path.join(REPO_DIR, "hms_stem_cleaner_app.py")


def patch_hms_other_synth_routing(app_script_path=APP_SCRIPT):
    """
    Patches hms_stem_cleaner_app.py so MVSep 6-stem 'other' files (synths, pads,
    electronic leads, industrial outros) are preserved alongside 'guitar' stems
    instead of being dropped as redundant composite '_Music_CLEAN.wav' files.
    """
    print("=" * 75)
    print(f"[RUN] Patching Synth / 'Other' Stem Retention in: {app_script_path}")
    print("=" * 75)

    if not os.path.isfile(app_script_path):
        print(f"[ERROR] File not found: {app_script_path}")
        return False

    try:
        with open(app_script_path, "r", encoding="utf-8") as f:
            code = f.read()

        changes_made = 0

        # 1. Route 'other' to 'Other_Synths' instead of generic 'Music'
        old_tag_block = (
            '        elif "other" in lower_name or "inst" in lower_name or "music" in lower_name:\n'
            '            stem_role = "Music"'
        )
        new_tag_block = (
            '        elif "other" in lower_name:\n'
            '            stem_role = "Other_Synths"\n'
            '        elif "inst" in lower_name or "music" in lower_name:\n'
            '            stem_role = "Music"'
        )

        if old_tag_block in code:
            code = code.replace(old_tag_block, new_tag_block, 1)
            changes_made += 1
            print("[SUCCESS] Updated extract_clean_stem_tag(): 'other' -> 'Other_Synths'.")
        elif 'stem_role = "Other_Synths"' in code:
            print("[INFO] extract_clean_stem_tag() already routes 'other' -> 'Other_Synths'.")

        # 2. Prevent filter_valid_bus_stems() from dropping '*_Music_CLEAN.wav'
        #    so existing 6-stem folders keep their synths/pads alongside Guitars
        old_filter_line = '        if bus_name == "Music" and len(valid_stems) > 1:'
        new_filter_line = '        if False and bus_name == "Music" and len(valid_stems) > 1:'

        if old_filter_line in code and new_filter_line not in code:
            code = code.replace(old_filter_line, new_filter_line, 1)
            changes_made += 1
            print("[SUCCESS] Updated filter_valid_bus_stems(): disabled dropping '*_Music_CLEAN.wav'.")
        elif new_filter_line in code:
            print("[INFO] filter_valid_bus_stems() already keeps '*_Music_CLEAN.wav' stems.")

        # Write updated file atomically via .tmp swap
        if changes_made > 0:
            temp_path = f"{app_script_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(code)
            os.replace(temp_path, app_script_path)
            print(f"[SUCCESS] Atomically saved {changes_made} update(s) to {app_script_path}")
        else:
            print("[INFO] No file changes needed; hms_stem_cleaner_app.py is already up to date.")

        return True

    except Exception:
        print("[ERROR] Failed patching hms_stem_cleaner_app.py:")
        print(traceback.format_exc())
        return False


def find_sensory_bleed_cleaned_dir():
    """
    Searches common project folders on H:\\ and C:\\ for the Sensory_Bleed folder
    that contains the rendered *_CLEAN.wav stems.
    """
    print("-" * 75)
    print("[RUN] Locating 'Sensory_Bleed' cleaned stems directory...")

    # Check fast candidate locations first before walking deeper directories
    candidate_roots = [
        r"H:\suno projects",
        r"C:\Users\racer\Desktop",
        r"C:\Users\racer\Downloads",
        r"C:\Users\racer\Music",
        r"H:\\",
    ]

    visited = set()
    for root_dir in candidate_roots:
        if not os.path.exists(root_dir):
            continue
        for curr_root, dirs, files in os.walk(root_dir):
            norm_curr = os.path.normcase(os.path.abspath(curr_root))
            if norm_curr in visited:
                continue
            visited.add(norm_curr)

            # Skip system/git/venv folders for speed
            dirs[:] = [
                d for d in dirs
                if d not in {"$RECYCLE.BIN", "System Volume Information", ".git", "build", "dist", "__pycache__"}
            ]

            if "sensory_bleed" in norm_curr:
                clean_wavs = [f for f in files if f.upper().endswith("_CLEAN.WAV")]
                if clean_wavs:
                    # Parent of the bus subfolder (Vocals / Rhythm / Music) is the song dir
                    parent_name = os.path.basename(curr_root).lower()
                    if parent_name in {"vocals", "rhythm", "music"}:
                        song_dir = os.path.dirname(curr_root)
                    else:
                        song_dir = curr_root
                    print(f"[SUCCESS] Found Sensory_Bleed cleaned stem folder: {song_dir}")
                    return song_dir

    print("[ERROR] Could not automatically locate a Sensory_Bleed folder containing *_CLEAN.wav files.")
    return None


def reglue_sensory_bleed_master(song_dir=None):
    """
    Imports the patched hms_stem_cleaner_app module and re-renders the
    Sensory_Bleed 24-bit Master Mix with both Guitars and Synths ('Other') active.
    """
    target_dir = song_dir or find_sensory_bleed_cleaned_dir()
    if not target_dir:
        return None

    try:
        sys.path.insert(0, REPO_DIR)
        import hms_stem_cleaner_app as hms

        print("=" * 75)
        print(f"[RUN] Re-gluing Buses & Master Mix (With Synths Restored) for: {target_dir}")
        print("=" * 75)

        # Heavy Metal / Industrial balance with full Music bus (Guitars + Synths)
        weights = {"Vocals": 1.04, "Rhythm": 1.00, "Music": 0.94}
        res = hms.render_master_mixdown(dest_song_dir=target_dir, bus_weights=weights)

        master_path = res.get("master_wav_path")
        if master_path and os.path.isfile(master_path):
            print("=" * 75)
            print(f"[SUCCESS] RESTORED SYNTHS MASTER MIX READY -> {master_path}")
            print("=" * 75)
            return master_path

        print("[ERROR] render_master_mixdown finished without returning a valid master_wav_path.")
        return None

    except Exception:
        print("[ERROR] Exception while re-gluing Sensory_Bleed master mix:")
        print(traceback.format_exc())
        return None


if __name__ == "__main__":
    custom_dir = sys.argv[1] if len(sys.argv) > 1 else None
    if patch_hms_other_synth_routing():
        reglue_sensory_bleed_master(custom_dir)