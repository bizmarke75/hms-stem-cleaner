# Save as: C:\github\projects\hms-stem-cleaner\release_v1_3_0_web_daw.py
# Fast Clean + Git Push      : python.exe C:\github\projects\hms-stem-cleaner\release_v1_3_0_web_daw.py
# Clean + Build EXE + Push   : python.exe C:\github\projects\hms-stem-cleaner\release_v1_3_0_web_daw.py --build-exe

import argparse
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"

# Core production files that stay in the root of C:\github\projects\hms-stem-cleaner
KEEP_PRODUCTION_FILES = {
    "hms_web_daw.html",
    "hms_web_daw_launcher.py",
    "launch_chrome_web_daw.py",
    "hms_unified_studio_app.py",
    "hms_stem_cleaner_app.py",
    "hms_mix_json_manager.py",
    "hms_gemini_tuner.py",
    "hms_ai_api_bridge.py",
    "release_v1_2_0_suite.py",
    "release_v1_3_0_web_daw.py",
    "Launch_HMS_Chrome_DAW.bat",
    "Launch_HMS_Web_DAW.bat",
    "README.md",
    "DEV_LOG.md",
    "LICENSE",
    "requirements.txt",
    ".gitignore",
}


# ==============================================================================
# FUNCTION 1: ARCHIVE ONE-TIME PATCH SCRIPTS INTO _archive_diagnostics\
# ==============================================================================
def archive_v1_3_patch_scripts(repo_dir=HMS_REPO_DIR):
    """
    Moves temporary one-time patch/fix scripts into _archive_diagnostics\\
    so the main repository root only contains active production modules.
    """
    print("=" * 75)
    print(f"[RUN] Auditing and archiving temporary patch scripts in: {repo_dir}")
    archive_dir = os.path.join(repo_dir, "_archive_diagnostics")
    os.makedirs(archive_dir, exist_ok=True)

    moved = []
    try:
        for fname in os.listdir(repo_dir):
            fpath = os.path.join(repo_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if fname in KEEP_PRODUCTION_FILES:
                continue
            if fname.startswith(("fix_", "patch_", "test_", "add_mvsep_", "upgrade_", "build_web_daw")):
                dest = os.path.join(archive_dir, fname)
                shutil.move(fpath, dest)
                moved.append(fname)
                print(f"[INFO] Archived one-time script -> _archive_diagnostics\\{fname}")

        print(f"[SUCCESS] Workspace clean! Archived {len(moved)} temporary script(s).")
        return moved
    except Exception:
        print("[ERROR] Failed archiving temporary scripts:")
        print(traceback.format_exc())
        return moved


# ==============================================================================
# FUNCTION 2: UPDATE DEV_LOG.md & CREATE 1-CLICK DESKTOP SHORTCUTS
# ==============================================================================
def update_dev_log_and_shortcuts(repo_dir=HMS_REPO_DIR):
    """
    Appends the v1.3.0 Web-DAW & Chrome Studio Server documentation to DEV_LOG.md
    and writes 1-click .bat launchers to the user's Desktop.
    """
    print("=" * 75)
    print("[RUN] Updating DEV_LOG.md and Desktop launchers...")
    try:
        log_path = os.path.join(repo_dir, "DEV_LOG.md")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        section_lines = [
            "",
            "---",
            "",
            f"## 8. v1.3.0 Web-DAW Studio UI & Google Chrome / PyWebView Server ({ts})",
            "- **`hms_web_daw.html`:** Full dark-mode Web-DAW frontend featuring:",
            "  - **Step 1: MVSep Cloud Stem Splitter Deck** (File browser, 10 separation models including BS Roformer SW 6-Stems, 5 output formats, live GPU queue log drawer, and automatic handoff to the 9-slider mixer).",
            "  - **Real-Time 60 FPS Web Audio FFT Spectrum Analyzer & WAV Audition Deck** (110 Hz Sawtooth test stem signal + local WAV/Master audition player).",
            "  - **9-Slider Hardware Rack:** Group A Motor Faders (`Vocals: 1.08`, `Rhythm: 1.04`, `Music: 0.90`) + Group B VST3 Controls (`Vocal Gate: -33.0 dB`, `TDR Nova Pocket: -2.5 dB`, `MJUCjr Compress: 18.0%`, `MJUCjr Makeup: 1.5 dB`, `CHOWTape Drive: 0.35`, `Master Ceiling: -0.3 dB`).",
            "- **`launch_chrome_web_daw.py`:** Frees stale processes on port `8765`, serves `hms_web_daw.html` at `http://127.0.0.1:8765/` with full CORS and REST endpoints (`/api/status`, `/api/credentials`, `/api/browse_song`, `/api/browse_folder`, `/api/mvsep/*`, `/api/run_action`), and launches Google Chrome in Studio App mode (`--app=http://127.0.0.1:8765/`).",
            "- **`hms_web_daw_launcher.py`:** Native Windows Edge WebView2 (`pywebview`) desktop wrapper with `HMSWebDawBridge`.",
        ]

        existing = ""
        if os.path.isfile(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                existing = f.read()

        if "## 8. v1.3" not in existing:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(existing.rstrip() + "\n" + "\n".join(section_lines) + "\n")
            print(f"[SUCCESS] Appended Section 8 (v1.3.0 Web-DAW) to: {log_path}")
        else:
            print("[INFO] DEV_LOG.md already contains Section 8.")

        # Create 1-Click Chrome Launcher on Desktop
        chrome_bat = (
            "@echo off\r\n"
            "title 337 West Productions - HMS Chrome Web-DAW Server (:8765)\r\n"
            "cd /d \"C:\\github\\projects\\hms-stem-cleaner\"\r\n"
            f"\"{sys.executable}\" \"C:\\github\\projects\\hms-stem-cleaner\\launch_chrome_web_daw.py\"\r\n"
        )
        with open(os.path.join(repo_dir, "Launch_HMS_Chrome_DAW.bat"), "w", encoding="utf-8") as f:
            f.write(chrome_bat)

        desktop = Path.home() / "Desktop"
        if desktop.is_dir():
            with open(desktop / "Launch_HMS_Chrome_DAW.bat", "w", encoding="utf-8") as f:
                f.write(chrome_bat)
            print(f"[SUCCESS] Created Desktop Shortcut: {desktop / 'Launch_HMS_Chrome_DAW.bat'}")

        return True
    except Exception:
        print("[ERROR] Failed updating DEV_LOG.md / shortcuts:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 3: OPTIONAL PYINSTALLER BUILD + GIT COMMIT & PUSH (v1.3.0)
# ==============================================================================
def commit_and_push_v1_3_0(repo_dir=HMS_REPO_DIR, build_exe=False):
    """
    Optionally compiles dist\\HMS_Web_DAW_Studio.exe, then stages, commits,
    tags v1.3.0, and pushes to origin main on GitHub.
    """
    if build_exe:
        print("=" * 75)
        print("[RUN] Compiling dist\\HMS_Web_DAW_Studio.exe via PyInstaller...")
        html_file = os.path.join(repo_dir, "hms_web_daw.html")
        launcher_file = os.path.join(repo_dir, "hms_web_daw_launcher.py")
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onefile", "--windowed",
            "--name", "HMS_Web_DAW_Studio",
            "--paths", repo_dir,
            "--add-data", f"{html_file};.",
            "--hidden-import", "hms_stem_cleaner_app",
            "--hidden-import", "hms_mix_json_manager",
            "--hidden-import", "hms_gemini_tuner",
            "--hidden-import", "hms_ai_api_bridge",
            "--collect-all", "webview",
            "--collect-all", "pedalboard",
            "--collect-all", "numpy",
            launcher_file,
        ]
        subprocess.run(cmd, cwd=repo_dir, check=False)

    print("=" * 75)
    print("[RUN] Staging and pushing v1.3.0 Web-DAW Suite to GitHub...")
    try:
        stage_files = [
            "DEV_LOG.md",
            "hms_web_daw.html",
            "hms_web_daw_launcher.py",
            "launch_chrome_web_daw.py",
            "hms_ai_api_bridge.py",
            "release_v1_3_0_web_daw.py",
            "Launch_HMS_Chrome_DAW.bat",
            "Launch_HMS_Web_DAW.bat",
        ]
        for fn in stage_files:
            fp = os.path.join(repo_dir, fn)
            if os.path.isfile(fp):
                subprocess.run(["git", "add", fn], cwd=repo_dir, check=False)

        diff = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if diff.stdout.strip():
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(
                ["git", "commit", "-m", f"Release v1.3.0: Add Chrome & PyWebView Web-DAW UI + Integrated MVSep Cloud Splitter ({ts})"],
                cwd=repo_dir,
                check=True,
            )
            subprocess.run(["git", "tag", "-f", "v1.3.0"], cwd=repo_dir, check=False)
            subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, check=True)
            subprocess.run(["git", "push", "-f", "origin", "v1.3.0"], cwd=repo_dir, check=False)
            print("[SUCCESS] Committed and pushed v1.3.0 + tag to https://github.com/bizmarke75/hms-stem-cleaner!")
        else:
            print("[INFO] Git working tree already clean and up to date.")
        return True
    except Exception:
        print("[ERROR] Git commit/push failed:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS v1.3.0 Web-DAW Cleanup & Release Publisher")
    parser.add_argument("--build-exe", action="store_true", help="Also compile dist\\HMS_Web_DAW_Studio.exe")
    args = parser.parse_args()

    archive_v1_3_patch_scripts()
    update_dev_log_and_shortcuts()
    commit_and_push_v1_3_0(build_exe=args.build_exe)