# Save as: C:\github\projects\hms-stem-cleaner\release_v1_2_0_suite.py
# Preview Archive Only : python.exe C:\github\projects\hms-stem-cleaner\release_v1_2_0_suite.py --dry-run
# Full Archive + Build + Git Push v1.2.0 : python.exe C:\github\projects\hms-stem-cleaner\release_v1_2_0_suite.py

import argparse
import os
import shutil
import subprocess
import sys
import traceback
import zipfile
from datetime import datetime

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
MVSEP_REPO_DIR = r"C:\github\projects\mvsep-api-gui"
REMOTE_URL = "https://github.com/bizmarke75/hms-stem-cleaner.git"
VERSION_TAG = "v1.2.0"

# Strict whitelist of core production files to keep in the root of HMS_REPO_DIR
HMS_CORE_WHITELIST = {
    "hms_unified_studio_app.py",
    "hms_stem_cleaner_app.py",
    "hms_mix_json_manager.py",
    "hms_gemini_tuner.py",
    "hms_ai_api_bridge.py",
    "mvsep_gui.py",
    "release_v1_2_0_suite.py",
    "readme.md",
    "dev_log.md",
    "license",
    "requirements.txt",
    ".gitignore",
}

# Strict whitelist of core production files to keep in the root of MVSEP_REPO_DIR
MVSEP_CORE_WHITELIST = {
    "mvsep_gui.py",
    "hms_ai_api_bridge.py",
    "hms_gemini_tuner.py",
    "hms_mix_json_manager.py",
    "readme.md",
    "license",
    "requirements.txt",
    ".gitignore",
}

# Protected directories that must stay in place
PROTECTED_DIRS = {
    ".git",
    "assets",
    "dist",
    "build",
    "release_upload",
    "src_backup",
    "_archive_diagnostics",
    "_hms_rollback_vault",
    "__pycache__",
}


# ==============================================================================
# FUNCTION 1: DECLUTTER & ARCHIVE OLD SCRIPTS IN BOTH REPOSITORIES
# ==============================================================================
def archive_old_repo_clutter(hms_repo=HMS_REPO_DIR, mvsep_repo=MVSEP_REPO_DIR, dry_run=False):
    """
    Scans both C:\\github\\projects\\hms-stem-cleaner and C:\\github\\projects\\mvsep-api-gui,
    keeping only core production files and moving old patchers, test drivers,
    one-off builders, and temp files into _archive_diagnostics\\.
    """
    summary = {"kept": [], "archived": []}

    for repo_path, whitelist in ((hms_repo, HMS_CORE_WHITELIST), (mvsep_repo, MVSEP_CORE_WHITELIST)):
        if not os.path.isdir(repo_path):
            print(f"[INFO] Skipping missing repo path: {repo_path}")
            continue

        archive_dir = os.path.join(repo_path, "_archive_diagnostics")
        os.makedirs(archive_dir, exist_ok=True)

        print("=" * 75)
        print(f"[RUN] Decluttering Repository: {repo_path} (dry_run={dry_run})")
        print("=" * 75)

        try:
            for item in sorted(os.listdir(repo_path)):
                item_path = os.path.join(repo_path, item)
                lower_name = item.lower()

                # Skip protected directories
                if os.path.isdir(item_path):
                    if lower_name in PROTECTED_DIRS:
                        continue
                    # Move old temporary test folders into _archive_diagnostics
                    if lower_name.startswith(("_layer", "hms_raw_input", "test_")):
                        dst = os.path.join(archive_dir, item)
                        if not dry_run:
                            if os.path.exists(dst):
                                shutil.rmtree(dst)
                            shutil.move(item_path, dst)
                        print(f"[SUCCESS] Archived old test folder -> _archive_diagnostics\\{item}")
                        summary["archived"].append(item_path)
                    continue

                # Keep core production files
                if lower_name in whitelist:
                    print(f"[INFO] [KEEP CORE] {item}")
                    summary["kept"].append(item_path)
                    continue

                # Archive old .py patchers/builders/tests, .spec files, .tmp files, or stray .json/.txt logs
                if lower_name.endswith((".py", ".spec", ".tmp", ".bak", ".log")):
                    dst = os.path.join(archive_dir, item)
                    if dry_run:
                        print(f"[INFO] [DRY-RUN ARCHIVE] {item} -> _archive_diagnostics\\{item}")
                    else:
                        if os.path.exists(dst):
                            os.remove(dst)
                        shutil.move(item_path, dst)
                        print(f"[SUCCESS] [MOVED TO ARCHIVE] {item} -> _archive_diagnostics\\{item}")
                    summary["archived"].append(item_path)

        except Exception:
            print(f"[ERROR] Failed decluttering {repo_path}:")
            print(traceback.format_exc())

    # Sync latest mvsep_gui.py into HMS_REPO_DIR so both repos have identical copies
    mvsep_src = os.path.join(mvsep_repo, "mvsep_gui.py")
    mvsep_dst = os.path.join(hms_repo, "mvsep_gui.py")
    if os.path.isfile(mvsep_src) and not dry_run:
        try:
            shutil.copy2(mvsep_src, mvsep_dst)
            print(f"[SUCCESS] Synced latest mvsep_gui.py into {hms_repo}")
        except Exception:
            pass

    return summary


# ==============================================================================
# FUNCTION 2: COMPILE V1.2.0 STANDALONE EXECUTABLES
# ==============================================================================
def compile_v1_2_0_executables(hms_repo=HMS_REPO_DIR, mvsep_repo=MVSEP_REPO_DIR):
    """
    Compiles HMS_Unified_Studio.exe, HMS_Stem_Cleaner.exe, and MVSep_Stem_Separator.exe
    with all v1.2.0 modules bundled.
    """
    built_exes = {}
    targets = [
        (
            "HMS_Unified_Studio",
            os.path.join(hms_repo, "hms_unified_studio_app.py"),
            hms_repo,
            True,
        ),
        (
            "HMS_Stem_Cleaner",
            os.path.join(hms_repo, "hms_stem_cleaner_app.py"),
            hms_repo,
            True,
        ),
        (
            "MVSep_Stem_Separator",
            os.path.join(mvsep_repo, "mvsep_gui.py")
            if os.path.isfile(os.path.join(mvsep_repo, "mvsep_gui.py"))
            else os.path.join(hms_repo, "mvsep_gui.py"),
            mvsep_repo if os.path.isdir(mvsep_repo) else hms_repo,
            False,
        ),
    ]

    for app_name, script_path, work_dir, collect_pedalboard in targets:
        if not os.path.isfile(script_path):
            print(f"[INFO] Skipping {app_name} (script not found at {script_path})")
            continue

        print("\n" + "=" * 75)
        print(f"[RUN] Compiling {app_name}.exe from: {script_path}")
        print("=" * 75)

        try:
            cmd = [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name",
                app_name,
                "--paths",
                hms_repo,
                "--paths",
                work_dir,
                "--hidden-import",
                "hms_stem_cleaner_app",
                "--hidden-import",
                "hms_mix_json_manager",
                "--hidden-import",
                "hms_gemini_tuner",
                "--hidden-import",
                "hms_ai_api_bridge",
                "--hidden-import",
                "requests",
                "--collect-all",
                "soundfile",
            ]
            if collect_pedalboard:
                cmd.extend(["--collect-all", "pedalboard", "--collect-all", "numpy"])

            icon_path = os.path.join(work_dir, "assets", "mvsep.ico")
            if os.path.isfile(icon_path):
                cmd.extend(["--icon", icon_path, "--add-data", f"{icon_path};assets"])

            cmd.append(script_path)
            subprocess.run(cmd, cwd=work_dir, check=True)

            exe_out = os.path.join(work_dir, "dist", f"{app_name}.exe")
            if os.path.isfile(exe_out):
                mb = round(os.path.getsize(exe_out) / (1024 * 1024), 2)
                print(f"[SUCCESS] Built {app_name}.exe ({mb} MB) -> {exe_out}")
                built_exes[app_name] = exe_out

                # Remove the temporary .spec file generated by PyInstaller so root stays clean
                spec_file = os.path.join(work_dir, f"{app_name}.spec")
                if os.path.isfile(spec_file):
                    os.remove(spec_file)

        except Exception:
            print(f"[ERROR] Failed building {app_name}.exe:")
            print(traceback.format_exc())

    return built_exes


# ==============================================================================
# FUNCTION 3: UPDATE DOCS, PACKAGE V1.2.0 ZIP & PUSH TO GITHUB
# ==============================================================================
def package_and_push_v1_2_0(hms_repo=HMS_REPO_DIR, built_exes=None, remote_url=REMOTE_URL):
    """
    Updates DEV_LOG.md and RELEASE_NOTES_v1.2.0.md, packages the v1.2.0 standalone
    release ZIP, stages all clean changes, tags v1.2.0, and pushes to GitHub.
    """
    print("\n" + "=" * 75)
    print(f"[RUN] Packaging & Publishing {VERSION_TAG} to: {remote_url}")
    print("=" * 75)

    try:
        release_dir = os.path.join(hms_repo, "release_upload")
        os.makedirs(release_dir, exist_ok=True)
        today_str = datetime.now().strftime("%Y-%m-%d")

        notes_lines = [
            f"# 337 West Studio Suite — HMS Stem Cleaner & MVSep Cloud Splitter {VERSION_TAG} (Provided As-Is)",
            "",
            f"**Release Date:** {today_str}",
            "**Studio:** 337 West Productions",
            "**License:** MIT (Provided strictly **AS-IS** with no warranty or technical support)",
            "",
            "---",
            "",
            f"## What's New in {VERSION_TAG}",
            "",
            "### 1. Unified 2-Tab Dark-Mode Studio GUI (`hms_unified_studio_app.py` / `HMS_Unified_Studio.exe`)",
            "- Combines **Tab 1: MVSep Cloud Stem Splitter** and **Tab 2: HMS 9-Slider VST3 Cleaner & Master Mixer** into a single window.",
            "- Shared top bar persists both your **MVSep API Token** and **Gemini 2.5 Flash API Key** (`~/.mvsep_hms_config.json`) and includes a 1-click **Local REST API (`127.0.0.1:8765`)** toggle.",
            "",
            "### 2. Expanded 9-Slider Live Mixer & C++ VST3 Bus Controls",
            "- Exposes 5 new live VST3 and mastering sliders alongside `Vocals`, `Rhythm`, `Music`, and `Vocal Gate (dB)`:",
            "  1. **Vocal Pocket (dB)** (`nova_music_pocket_db`): Controls `TDR Nova` 2.2 kHz center-channel carving on the `Music` bus.",
            "  2. **Vocal Comp (MJUCjr)** (`mjuc_compress`): Adjusts tube vocal compression (`0.0` to `40.0`).",
            "  3. **Vocal Makeup (dB)** (`mjuc_makeup`): Adds front-of-mix vocal grit and presence (`0.0` to `6.0 dB`).",
            "  4. **Rhythm Tape Drive** (`chow_rhythm_drive`): Controls `CHOWTapeModel` analog saturation on kick, snare, and sub-bass.",
            "  5. **Master Ceiling (dB)** (`master_ceiling_db`): Sets the final brickwall limiter ceiling (`-2.0` to `-0.1 dB`).",
            "",
            "### 3. Automatic Per-Song Mix Settings JSON (`hms_mix_json_manager.py`)",
            "- Every Master Mix render automatically saves `<Song_Name>_MIX_SETTINGS.json` next to `<Song_Name>_MASTER_MIX.wav`.",
            "- Includes **`💾 Save Mix JSON`** and **`📂 Load Mix JSON`** buttons (plus automatic preset loading when selecting a song folder).",
            "",
            "### 4. Repository Declutter & Archive Organization",
            "- Moved all one-time diagnostic, test, and patch scripts into `_archive_diagnostics\\` so the repository root contains only clean production modules.",
            "",
        ]
        notes_text = "\n".join(notes_lines)

        notes_path = os.path.join(release_dir, f"RELEASE_NOTES_{VERSION_TAG}.md")
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(notes_text)
        print(f"[SUCCESS] Wrote {VERSION_TAG} Release Notes -> {notes_path}")

        # Append v1.2.0 section to DEV_LOG.md
        dev_log_path = os.path.join(hms_repo, "DEV_LOG.md")
        existing_dev = ""
        if os.path.isfile(dev_log_path):
            with open(dev_log_path, "r", encoding="utf-8") as f:
                existing_dev = f.read()
        if VERSION_TAG not in existing_dev:
            with open(dev_log_path, "a", encoding="utf-8") as f:
                f.write("\n\n---\n\n" + notes_text)
            print(f"[SUCCESS] Appended {VERSION_TAG} changelog to DEV_LOG.md")

        # Package Release ZIP
        zip_path = os.path.join(release_dir, f"HMS_Stem_Cleaner_{VERSION_TAG}_Win64_Standalone.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for doc_name in ("README.md", "LICENSE", "DEV_LOG.md"):
                p = os.path.join(hms_repo, doc_name)
                if os.path.isfile(p):
                    zf.write(p, arcname=doc_name)
            zf.write(notes_path, arcname=f"RELEASE_NOTES_{VERSION_TAG}.md")

            for _, exe_p in (built_exes or {}).items():
                if exe_p and os.path.isfile(exe_p):
                    zf.write(exe_p, arcname=os.path.basename(exe_p))
                    print(f"[INFO] + Added binary to Release ZIP: {os.path.basename(exe_p)}")

        zip_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        print(f"[SUCCESS] Created Release Bundle ({zip_mb} MB) -> {zip_path}")

        # Ensure .gitignore excludes _archive_diagnostics/, release_upload/, dist/, build/, *.spec, *.wav
        gitignore_path = os.path.join(hms_repo, ".gitignore")
        if os.path.isfile(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                ig = f.read()
            for rule in ("_archive_diagnostics/", "release_upload/", "dist/", "build/", "*.spec", "*.tmp"):
                if rule not in ig:
                    ig += f"\n{rule}"
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(ig.strip() + "\n")

        # Stage all additions, modifications, and deletions (removes archived clutter from Git tracking)
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=hms_repo, check=False)
        subprocess.run(["git", "add", "-A"], cwd=hms_repo, check=True)

        # Safety guard: unstage any accidental .wav, .exe, or .zip file
        staged_proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=hms_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        for rel_f in staged_proc.stdout.splitlines():
            rel_f = rel_f.strip()
            if rel_f.lower().endswith((".wav", ".exe", ".zip", ".flac", ".mp3")):
                print(f"[INFO] Unstaging binary file from Git commit: {rel_f}")
                subprocess.run(["git", "reset", "HEAD", rel_f], cwd=hms_repo, check=False)

        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=hms_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_msg = (
            f"Release {VERSION_TAG}: Unified 2-Tab Studio GUI, 9-Slider VST3 Mixer, "
            "Auto-Save Mix JSON & Repo Declutter"
        )
        if status_proc.stdout.strip():
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=hms_repo, check=True)
            print(f"[SUCCESS] Committed changes: {commit_msg}")
        else:
            print("[INFO] Working tree already clean.")

        subprocess.run(["git", "tag", "-f", "-a", VERSION_TAG, "-m", commit_msg], cwd=hms_repo, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=hms_repo, check=True)
        subprocess.run(["git", "push", "-f", "origin", VERSION_TAG], cwd=hms_repo, check=True)

        print("=" * 75)
        print(f"[SUCCESS] Pushed main branch and tag {VERSION_TAG} to {remote_url}!")
        print(f"          Release ZIP Ready: {zip_path}")
        print("=" * 75)
        return True

    except Exception:
        print("[ERROR] Failed packaging or pushing v1.2.0:")
        print(traceback.format_exc())
        return False


def main():
    parser = argparse.ArgumentParser(description="HMS v1.2.0 Archive Declutter, EXE Compiler & GitHub Publisher")
    parser.add_argument("--dry-run", action="store_true", help="Preview files to archive without moving or compiling")
    args = parser.parse_args()

    archive_old_repo_clutter(dry_run=args.dry_run)
    if args.dry_run:
        print("\n[INFO] Dry-run preview complete. Re-run without --dry-run to archive, compile, and push v1.2.0.")
        return

    exes = compile_v1_2_0_executables()
    package_and_push_v1_2_0(built_exes=exes)


if __name__ == "__main__":
    main()