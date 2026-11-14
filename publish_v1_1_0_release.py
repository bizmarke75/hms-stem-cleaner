# Save as: C:\github\projects\hms-stem-cleaner\publish_v1_1_0_release.py
# Run in PowerShell: python.exe .\publish_v1_1_0_release.py

import os
import shutil
import subprocess
import traceback
import zipfile
from datetime import datetime

REPO_ROOT = r"C:\github\projects\hms-stem-cleaner"
REMOTE_URL = "https://github.com/bizmarke75/hms-stem-cleaner.git"
VERSION_TAG = "v1.1.0"


# ==============================================================================
# FUNCTION 1: WRITE V1.1.0 RELEASE NOTES & UPDATE DEV_LOG.MD
# ==============================================================================
def update_dev_log_and_release_notes(repo_root=REPO_ROOT):
    """
    Writes release_upload\\RELEASE_NOTES_v1.1.0.md and appends the v1.1.0
    engineering changelog to DEV_LOG.md.
    """
    print("=" * 75)
    print(f"[RUN] Generating {VERSION_TAG} Release Notes and updating DEV_LOG.md...")
    print("=" * 75)

    try:
        release_dir = os.path.join(repo_root, "release_upload")
        os.makedirs(release_dir, exist_ok=True)

        notes_path = os.path.join(release_dir, f"RELEASE_NOTES_{VERSION_TAG}.md")
        today_str = datetime.now().strftime("%Y-%m-%d")

        release_notes_md = f"""# HMS Stem Cleaner & Headless VST3 Master Engine {VERSION_TAG} (Provided As-Is)

**Release Date:** {today_str}  
**Studio:** 337 West Productions  
**License:** MIT (Provided strictly **AS-IS** with no warranty or technical support)

---

## What's New in {VERSION_TAG}

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
"""

        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(release_notes_md)
        print(f"[SUCCESS] Wrote release notes: {notes_path}")

        # Append to DEV_LOG.md if not already logged
        dev_log_path = os.path.join(repo_root, "DEV_LOG.md")
        existing_log = ""
        if os.path.isfile(dev_log_path):
            with open(dev_log_path, "r", encoding="utf-8") as f:
                existing_log = f.read()

        if VERSION_TAG not in existing_log:
            with open(dev_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n\n---\n\n{release_notes_md}")
            print(f"[SUCCESS] Appended {VERSION_TAG} entry to: {dev_log_path}")
        else:
            print(f"[INFO] DEV_LOG.md already contains an entry for {VERSION_TAG}.")

        return notes_path

    except Exception:
        print("[ERROR] Failed writing release notes or DEV_LOG.md:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 2: PACKAGE STANDALONE WINDOWS ZIP ARCHIVE
# ==============================================================================
def package_v1_1_0_standalone_zip(repo_root=REPO_ROOT):
    """
    Packages dist\\HMS_Stem_Cleaner.exe (and MVSep_Stem_Separator.exe if present)
    along with README.md, LICENSE, and RELEASE_NOTES_v1.1.0.md into a release ZIP.
    """
    print("-" * 75)
    print(f"[RUN] Packaging {VERSION_TAG} Standalone Windows ZIP Archive...")

    try:
        release_dir = os.path.join(repo_root, "release_upload")
        os.makedirs(release_dir, exist_ok=True)
        zip_path = os.path.join(
            release_dir, f"HMS_Stem_Cleaner_{VERSION_TAG}_Win64_Standalone.zip"
        )

        hms_exe = os.path.join(repo_root, "dist", "HMS_Stem_Cleaner.exe")
        if not os.path.isfile(hms_exe):
            print(f"[ERROR] HMS_Stem_Cleaner.exe not found at: {hms_exe}")
            print("        Run 'python.exe .\\upgrade_and_build_all.py' first!")
            return None

        # Also copy mvsep_gui.py or MVSep_Stem_Separator.exe if found in common locations
        optional_files = [
            os.path.join(repo_root, "README.md"),
            os.path.join(repo_root, "LICENSE"),
            os.path.join(repo_root, "DEV_LOG.md"),
            os.path.join(release_dir, f"RELEASE_NOTES_{VERSION_TAG}.md"),
            os.path.join(repo_root, "dist", "MVSep_Stem_Separator.exe"),
        ]

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(hms_exe, arcname="HMS_Stem_Cleaner.exe")
            print(f"[INFO] + Added to ZIP: HMS_Stem_Cleaner.exe")

            for item in optional_files:
                if os.path.isfile(item):
                    arcname = os.path.basename(item)
                    zf.write(item, arcname=arcname)
                    print(f"[INFO] + Added to ZIP: {arcname}")

        zip_size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        print(f"[SUCCESS] Created Release Archive ({zip_size_mb} MB): {zip_path}")
        return zip_path

    except Exception:
        print("[ERROR] Failed packaging standalone release ZIP:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 3: GIT STAGE, COMMIT, TAG V1.1.0, AND PUSH TO GITHUB
# ==============================================================================
def commit_and_push_v1_1_0(repo_root=REPO_ROOT, remote_url=REMOTE_URL):
    """
    Stages all modified Python scripts and documentation, commits v1.1.0,
    tags v1.1.0, and pushes main + v1.1.0 to GitHub.
    """
    print("-" * 75)
    print(f"[RUN] Committing, tagging ({VERSION_TAG}), and pushing to: {remote_url}")

    try:
        # Ensure remote 'origin' points to bizmarke75/hms-stem-cleaner
        subprocess.run(
            ["git", "remote", "set-url", "origin", remote_url],
            cwd=repo_root,
            check=False,
        )

        # Stage all tracked and new repo scripts/docs (respecting .gitignore)
        subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)

        # Check if there are staged changes to commit
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )

        commit_msg = (
            f"Release {VERSION_TAG}: Mix Style Mode Switch (Acoustic vs Heavy), "
            "6-Stem Synth Retention & MVSep Upload Fixes"
        )

        if status_proc.stdout.strip():
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=repo_root,
                check=True,
            )
            print(f"[SUCCESS] Created Git commit: {commit_msg}")
        else:
            print("[INFO] Working tree already clean; proceeding to tag and push.")

        # Create or update annotated tag v1.1.0
        subprocess.run(
            ["git", "tag", "-f", "-a", VERSION_TAG, "-m", commit_msg],
            cwd=repo_root,
            check=True,
        )
        print(f"[SUCCESS] Tagged commit as: {VERSION_TAG}")

        # Push main branch and v1.1.0 tag to origin
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_root, check=True)
        subprocess.run(["git", "push", "-f", "origin", VERSION_TAG], cwd=repo_root, check=True)

        print("=" * 75)
        print(f"[SUCCESS] Pushed main branch and {VERSION_TAG} tag to GitHub!")
        print("=" * 75)
        return True

    except Exception:
        print("[ERROR] Git commit/push encountered an issue:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    notes_file = update_dev_log_and_release_notes()
    zip_file = package_v1_1_0_standalone_zip()
    if notes_file and zip_file:
        commit_and_push_v1_1_0()