# Save as: C:\github\projects\hms-stem-cleaner\release_v1_4_0_suite.py
# Safe Dry-Run Preview    : python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_0_suite.py --dry-run
# Local Clean + Docs Only : python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_0_suite.py --no-push
# Full Clean + Docs + Push: python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_0_suite.py

import argparse
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
REMOTE_URL = "https://github.com/bizmarke75/hms-stem-cleaner.git"
VERSION_TAG = "v1.4.0"

# Strict lowercase whitelist of active v1.4.0 production files kept in the repo root
V14_CORE_WHITELIST = {
    "337_west_hms_unified_studio_web_daw_v1.4.html",
    "hms_web_daw.html",
    "hms_web_daw_launcher.py",
    "launch_chrome_web_daw.py",
    "hms_runtime_paths.py",
    "hms_mvsep_multipass.py",
    "hms_unified_studio_app.py",
    "hms_stem_cleaner_app.py",
    "hms_mix_json_manager.py",
    "hms_gemini_tuner.py",
    "hms_ai_api_bridge.py",
    "mvsep_gui.py",
    "fix_v1_4_html_and_rebuild.py",
    "build_v1_4_windows_installer.py",
    "release_v1_4_0_suite.py",
    "launch_hms_chrome_daw.bat",
    "launch_hms_web_daw.bat",
    "readme.md",
    "dev_log.md",
    "license",
    "requirements.txt",
    ".gitignore",
}

# Folders that stay untouched in the repo root
PROTECTED_DIRS = {
    ".git",
    "assets",
    "docs",
    "dist",
    "build",
    "installer_out",
    "release_upload",
    "src_backup",
    "_archive_diagnostics",
    "_hms_rollback_vault",
    "__pycache__",
}


def _atomic_write_text(file_path, text):
    """Writes UTF-8 text via a temporary sibling file and atomically replaces the target."""
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_path, file_path)


# ==============================================================================
# FUNCTION 1: ARCHIVE ONE-TIME PATCH SCRIPTS & OLD BUILDERS INTO _archive_diagnostics\
# ==============================================================================
def archive_temporary_v1_4_scripts(repo_dir=HMS_REPO_DIR, dry_run=False):
    """
    Moves temporary one-time patchers, diagnostic scripts, old release scripts,
    and stray .spec/.tmp/.bak files into _archive_diagnostics\\ while keeping
    all active v1.4.0 production modules intact.

    Args:
        repo_dir (str): Path to the HMS repository root.
        dry_run (bool): When True, logs planned moves without altering disk files.

    Returns:
        dict: {"kept": list[str], "archived": list[str]}
    """
    norm_repo = os.path.normpath(repo_dir)
    archive_dir = os.path.join(norm_repo, "_archive_diagnostics")
    summary = {"kept": [], "archived": []}

    print("=" * 75)
    print(f"[RUN] Step 1: Auditing & Archiving Temporary Scripts in: {norm_repo} (dry_run={dry_run})")
    print("=" * 75)

    if not os.path.isdir(norm_repo):
        print(f"[ERROR] Repository path not found: {norm_repo}")
        return summary

    try:
        if not dry_run:
            os.makedirs(archive_dir, exist_ok=True)

        for item in sorted(os.listdir(norm_repo)):
            item_path = os.path.join(norm_repo, item)
            lower_name = item.lower()

            if os.path.isdir(item_path):
                if lower_name in PROTECTED_DIRS:
                    continue
                if lower_name.startswith(("_layer", "hms_raw_input", "test_")):
                    dst = os.path.join(archive_dir, item)
                    if dry_run:
                        print(f"[INFO] [DRY-RUN ARCHIVE DIR] {item} -> _archive_diagnostics\\{item}")
                    else:
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.move(item_path, dst)
                        print(f"[SUCCESS] [ARCHIVED DIR] {item} -> _archive_diagnostics\\{item}")
                    summary["archived"].append(item)
                continue

            # Keep whitelisted v1.4.0 production files
            if lower_name in V14_CORE_WHITELIST:
                print(f"[INFO] [KEEP CORE] {item}")
                summary["kept"].append(item)
                continue

            # Move non-whitelisted .py scripts (old patch_/fix_/upgrade_/test_/release_) and build artifacts
            if lower_name.endswith((".py", ".spec", ".tmp", ".bak", ".log")):
                dst = os.path.join(archive_dir, item)
                if dry_run:
                    print(f"[INFO] [DRY-RUN ARCHIVE] {item} -> _archive_diagnostics\\{item}")
                else:
                    if os.path.exists(dst):
                        os.remove(dst)
                    shutil.move(item_path, dst)
                    print(f"[SUCCESS] [MOVED TO ARCHIVE] {item} -> _archive_diagnostics\\{item}")
                summary["archived"].append(item)

        print("-" * 75)
        print(
            f"[SUCCESS] Step 1 Complete: {len(summary['kept'])} Core File(s) Kept | "
            f"{len(summary['archived'])} Temp Item(s) {'Previewed' if dry_run else 'Archived'}."
        )
        return summary

    except Exception:
        print("[ERROR] Failed archiving temporary v1.4 scripts:")
        print(traceback.format_exc())
        return summary


# ==============================================================================
# FUNCTION 2: UPDATE README.MD, DEV_LOG.MD & RELEASE_NOTES_v1.4.0.MD
# ==============================================================================
def update_readme_devlog_and_release_notes(repo_dir=HMS_REPO_DIR, dry_run=False):
    """
    Atomically refreshes README.md with the v1.4.0 universal How-To Guide,
    appends Section 9 (v1.4.0) to DEV_LOG.md, and writes release_upload\\RELEASE_NOTES_v1.4.0.md.

    Returns:
        dict | None: Paths of updated documentation files, or None on error.
    """
    norm_repo = os.path.normpath(repo_dir)
    readme_path = os.path.join(norm_repo, "README.md")
    devlog_path = os.path.join(norm_repo, "DEV_LOG.md")
    release_dir = os.path.join(norm_repo, "release_upload")
    notes_path = os.path.join(release_dir, f"RELEASE_NOTES_{VERSION_TAG}.md")

    today_str = datetime.now().strftime("%Y-%m-%d")
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("\n" + "=" * 75)
    print(f"[RUN] Step 2: Updating README.md, DEV_LOG.md & RELEASE_NOTES_{VERSION_TAG}.md (dry_run={dry_run})")
    print("=" * 75)

    try:
        # 1. Build clean v1.4.0 Release Notes (line-list avoids nested triple-quote bugs)
        release_notes_lines = [
            f"# 337 West Productions — HMS Unified Studio Suite {VERSION_TAG} (Provided As-Is)",
            "",
            f"**Release Date:** {today_str}  ",
            "**Studio:** 337 West Productions  ",
            "**License:** MIT (Provided strictly **AS-IS** with no warranty or technical support)",
            "",
            "---",
            "",
            f"## What's New in {VERSION_TAG}",
            "",
            "### 1. Non-Portable Windows Installer (`HMS_Studio_Suite_v1.4.0_Setup.exe`)",
            "- **Decoupled Runtime Paths (`hms_runtime_paths.py`):** Separates read-only program files (`C:\\Program Files\\HMS Studio Suite` or any custom drive) from writable user data inside `%LOCALAPPDATA%\\HMS Studio Suite` (`_HMS_Rollback_Vault`, `logs`, `presets`, and `WebView2Cache`).",
            "- **Fast PyInstaller `--onedir` + Inno Setup 6 (`PrivilegesRequired=admin`):** Instant startup without `--onefile` temp extraction delays, automatic Administrator UAC elevation for `Program Files`, Start Menu & Desktop shortcuts, and clean Windows uninstallation while preserving `~/.mvsep_hms_config.json`.",
            "",
            "### 2. Real-Time Stereo PCM Waveform & Oscilloscope Engine (v1.4.3)",
            "- **Early `<head>` Stereo Web Audio Tap:** Captures live Left/Right audio via a zero-gain-clocked `ChannelSplitter` across both the Web-DAW Audition Deck and legacy left-side visualizer canvases/VU meters.",
            "- **Pure-JS 24-Bit WAV Parser:** Directly decodes 8/16/24/32-bit PCM, 32-bit Float, and Pedalboard `WAVE_FORMAT_EXTENSIBLE (0xFFFE)` 24-bit WAVs into a split **L (Cyan) / R (Emerald)** click-to-seek full-track waveform overview + 60 FPS real-time oscilloscope and FFT spectrum.",
            "- Built-in **Test 440Hz** tone toggle for 1-click visual & meter verification.",
            "",
            "### 3. MVSep Registered Free-Tier Safe Mode & Sequential Multi-Pass Queue (`hms_mvsep_multipass.py`)",
            "- **Free-Tier Safe Toggle (ON by Default):** Automatically disables Premium Ensemble models (`sep_type=26, 28, 30`) and Premium 24/32-bit formats (`output_format=4, 5`) in both the Web-DAW dropdowns and the Python backend.",
            "- **Sequential 1-Concurrent-Job Queue Runner:** Executes the 3/4-pass HMS recipe strictly one job at a time (Pass 1 `BS Roformer 124-Band Standalone`, Pass 2 `BS Roformer SW 6-Stems`, Pass 3 `Demucs4 HT ft`, optional Pass 4 `DrumSep` fed from isolated Drums) with automatic duplicate-stem isolation into `<Song_Name>_Stems_Unused_Passes\\`.",
            "- **Auto-Discovery Bridge Hook:** Safely attaches multipass methods across both native `pywebview` (`hms_web_daw_launcher.py`) and Google Chrome App Mode / Local REST API (`127.0.0.1:8765`).",
            "",
        ]
        release_notes_text = "\n".join(release_notes_lines)

        # 2. Build comprehensive v1.4.0 README.md (All-Skill-Level How-To + Architecture)
        readme_lines = [
            "# HMS Unified Studio Suite (`v1.4.0`)",
            "**By 337 West Productions** | Automated MVSep Cloud Stem Splitting, Headless 64-Bit VST3 Stem Cleanup & 24-Bit Master Mixdown",
            "",
            "> **PROVIDED STRICTLY \"AS-IS\" (MIT LICENSE — NO WARRANTY OR SUPPORT)**  ",
            "> This studio utility is shared openly for fellow Suno, MVSep, and AI-assisted music creators. Always keep backups of your raw `.wav` stems.",
            "",
            "---",
            "",
            "## What This Suite Does",
            "1. **Splits full songs into stems** directly inside the Web-DAW via MVSep Cloud (Single-Pass or Free-Tier Safe Sequential Multi-Pass).",
            "2. **Cleans stem bleed, mud, harshness, and slapback echo** headlessly in 64-bit C++ memory using **TDR Nova**, **MJUCjr**, and **CHOWTapeModel** (with automatic native Pedalboard DSP fallback if any VST3 is not installed).",
            "3. **Glues stems into Vocals, Rhythm, and Music buses** and renders a phase-tight **24-bit Master WAV** (`<Song_Name>_MASTER_MIX.wav`) with real-time stereo L/R PCM waveform auditing.",
            "",
            "---",
            "",
            "## Quick Start (Any Skill Level)",
            "",
            "### Option A: Windows Installer (Recommended — No Python Required)",
            "1. Download and run **`HMS_Studio_Suite_v1.4.0_Setup.exe`** from the **GitHub Releases** page.",
            "2. Approve the Administrator prompt to install into `C:\\Program Files\\HMS Studio Suite` (or pick any drive/folder during setup).",
            "3. *(Optional, Recommended)* Install the 3 free 64-bit `.vst3` plugins into `C:\\Program Files\\Common Files\\VST3`:",
            "   - **TDR Nova** (Dynamic EQ)",
            "   - **Klanghelm MJUCjr** (Variable-Mu Vocal Compressor)",
            "   - **CHOWTapeModel** (Analog Tape Saturation)",
            "4. Launch **HMS Unified Studio Suite** from your Desktop or Start Menu.",
            "",
            "### Option B: Run From Source (Python 3.11+ on Windows)",
            "```powershell",
            "pip install -r requirements.txt",
            "python.exe hms_web_daw_launcher.py          # Native Windows Edge WebView2 Desktop UI",
            "python.exe launch_chrome_web_daw.py         # Google Chrome Studio App Mode (:8765)",
            "```",
            "",
            "---",
            "",
            "## 3-Step Workflow Inside the v1.4 Web-DAW UI",
            "1. **Enter API Keys Once (Top API Vault):** Save your **MVSep API Token** (for cloud splitting) and optional **Gemini API Key** (for Cloud AI listening). Keys are stored outside the repo in `~/.mvsep_hms_config.json`.",
            "2. **Split or Load Stems:**",
            "   - **From a Full Song:** Use **Step 1: MVSep Cloud Stem Splitter**. Leave **Free-Tier Safe Mode** checked on a Registered Free account to block Premium Ensemble models & 24/32-bit formats and run the Multi-Pass Recipe strictly 1 job at a time.",
            "   - **From Existing Stems:** Place one song's raw `.wav` stems in a dedicated folder named after the song, click **Browse**, click **0. AI Auto-Tune**, and run **2. Full Live Clean + Master**.",
            "3. **Audition & 3-Second Re-Mix:**",
            "   - Switch tracks in the **A/B Audition Deck** and inspect the **Real-Time Stereo PCM Waveform (L/R)**.",
            "   - Adjust Group A Bus Faders (**Vocals**, **Rhythm**, **Music**) and click **3. Glue Buses & Render Master Only** to update your 24-bit Master in ~3 seconds without re-cleaning stems.",
            "   - Switch **Mix Style Mode** to **Acoustic / Dynamic Rock** to keep centered acoustic guitars & solos untouched, or **Heavy Metal / Industrial** for full Mid/Side center vocal pocket carving.",
            "",
            "---",
            "",
            "## Core v1.4.0 Repository Layout",
            "- `337_west_hms_unified_studio_web_daw_v1.4.html` / `hms_web_daw.html` — Dark-mode Web-DAW UI with Real-Time Stereo PCM Waveform, 9-Slider Hardware Rack, and MVSep Free-Tier Multi-Pass Recipe Card.",
            "- `hms_web_daw_launcher.py` — Native Windows Edge WebView2 (`pywebview`) desktop launcher & JS bridge.",
            "- `launch_chrome_web_daw.py` — Local HTTP/REST server (`127.0.0.1:8765`) & Google Chrome App Mode launcher.",
            "- `hms_runtime_paths.py` — Frozen/non-portable path resolver routing writable vault, logs, presets, and `WebView2Cache` into `%LOCALAPPDATA%\\HMS Studio Suite`.",
            "- `hms_mvsep_multipass.py` — Registered Free-Tier validator, duplicate-stem isolator, and 1-concurrent-job sequential 4-pass MVSep queue runner.",
            "- `hms_stem_cleaner_app.py` — Headless 64-bit VST3 & Pedalboard DSP engine, atomic WAV writer, and Rollback Vault.",
            "- `hms_gemini_tuner.py` & `hms_ai_api_bridge.py` — Multimodal Gemini mix tuner & local REST bridge.",
            "- `hms_mix_json_manager.py` — Per-song `<Song_Name>_MIX_SETTINGS.json` preset persistence.",
            "- `fix_v1_4_html_and_rebuild.py` & `build_v1_4_windows_installer.py` — PyInstaller `--onedir` bundle compiler and Inno Setup 6 Admin installer builder.",
            "- `DEV_LOG.md` — Complete engineering notebook, VST3 C++ parameter tables, and troubleshooting history.",
            "",
        ]
        readme_text = "\n".join(readme_lines)

        # 3. Build Section 9 append block for DEV_LOG.md
        devlog_v14_lines = [
            "",
            "---",
            "",
            f"## 9. {VERSION_TAG} Non-Portable Windows Installer, Real-Time Stereo PCM Waveform & MVSep Free-Tier Multi-Pass ({ts_str})",
            "- **Non-Portable Windows Installer Pipeline (`hms_runtime_paths.py`, `fix_v1_4_html_and_rebuild.py`, `build_v1_4_windows_installer.py`):**",
            "  - Decoupled read-only installation assets (`sys._MEIPASS` / install dir) from writable Windows user data (`%LOCALAPPDATA%\\HMS Studio Suite\\` for `_HMS_Rollback_Vault`, `logs`, `presets`, and `WebView2Cache` via `WEBVIEW2_USER_DATA_FOLDER`).",
            "  - Switched compiled distribution from `--onefile` to PyInstaller `--onedir` (`dist\\HMS_Studio_Suite\\HMS_Studio_Suite.exe`) wrapped in Inno Setup 6 (`PrivilegesRequired=admin`, `DisableDirPage=no`, fixed AppId GUID `{A4A9CA40-FF08-4C93-BD3F-0FDF3188C53F}`).",
            "- **Real-Time Stereo PCM Waveform & Oscilloscope Engine (v1.4.3):**",
            "  - Added early `<head>` `AudioNode.prototype.connect` stereo `ChannelSplitter` tap clocked via a zero-gain sink plus a Pure-JS 8/16/24/32-bit PCM & `WAVE_FORMAT_EXTENSIBLE (0xFFFE)` WAV parser.",
            "  - Renders live 60 FPS L/R oscilloscope + FFT spectrum across both the main deck and legacy left-side canvases/meters alongside a split L/R full-track click-to-seek overview and 440 Hz Test Tone.",
            "- **MVSep Registered Free-Tier Safe Mode & Sequential Multi-Pass Runner (`hms_mvsep_multipass.py`):**",
            "  - Enforces Registered Free Tier guardrails (blocks Premium Ensemble `sep_type` `{26, 28, 30}`, blocks 24/32-bit `output_format` `{4, 5}`, enforces 100 MB cap with lossless FLAC pre-compression, and locks concurrency to max 1 active job).",
            "  - Stages winning stems per pass into `<Song_Name>_Stems\\` and isolates duplicate stems into sibling `<Song_Name>_Stems_Unused_Passes\\`.",
            "  - Wired into `hms_web_daw_launcher.py` (using AST/runtime bridge auto-discovery + `HMSWebDawBridge` alias), `hms_ai_api_bridge.py`, and `launch_chrome_web_daw.py`.",
            "",
        ]
        devlog_v14_block = "\n".join(devlog_v14_lines)

        if dry_run:
            print(f"[INFO] [DRY-RUN] Would update: {readme_path}")
            print(f"[INFO] [DRY-RUN] Would append Section 9 ({VERSION_TAG}) to: {devlog_path}")
            print(f"[INFO] [DRY-RUN] Would write: {notes_path}")
            return {"readme": readme_path, "dev_log": devlog_path, "release_notes": notes_path}

        os.makedirs(release_dir, exist_ok=True)
        _atomic_write_text(notes_path, release_notes_text)
        print(f"[SUCCESS] Wrote Release Notes -> {notes_path}")

        _atomic_write_text(readme_path, readme_text)
        print(f"[SUCCESS] Updated README.md -> {readme_path}")

        existing_dev = ""
        if os.path.isfile(devlog_path):
            with open(devlog_path, "r", encoding="utf-8") as f:
                existing_dev = f.read()

        if f"## 9. {VERSION_TAG}" not in existing_dev:
            updated_dev = existing_dev.rstrip() + "\n" + devlog_v14_block
            _atomic_write_text(devlog_path, updated_dev)
            print(f"[SUCCESS] Appended Section 9 ({VERSION_TAG}) to DEV_LOG.md")
        else:
            print(f"[INFO] DEV_LOG.md already contains Section 9 ({VERSION_TAG}).")

        return {"readme": readme_path, "dev_log": devlog_path, "release_notes": notes_path}

    except Exception:
        print("[ERROR] Failed updating documentation files:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 3: VERIFY .GITIGNORE, STAGE CLEAN FILES, TAG v1.4.0 & PUSH TO GITHUB
# ==============================================================================
def ensure_gitignore_and_push_v1_4_0(
    repo_dir=HMS_REPO_DIR,
    remote_url=REMOTE_URL,
    dry_run=False,
    skip_push=False,
):
    """
    Updates .gitignore to block installers/binaries/archives, stages clean source
    files with a binary safety guard, commits v1.4.0, tags v1.4.0, and pushes to GitHub.
    """
    norm_repo = os.path.normpath(repo_dir)
    gitignore_path = os.path.join(norm_repo, ".gitignore")

    print("\n" + "=" * 75)
    print(f"[RUN] Step 3: Git Safety Audit, Tag {VERSION_TAG} & Push (dry_run={dry_run}, skip_push={skip_push})")
    print("=" * 75)

    if dry_run:
        print("[INFO] [DRY-RUN] Checking current git status (read-only)...")
        proc = subprocess.run(["git", "status", "-s"], cwd=norm_repo, capture_output=True, text=True)
        print(proc.stdout or "[INFO] Working tree clean.")
        return True

    try:
        # 1. Ensure .gitignore excludes build outputs, archives, installers, and audio binaries
        required_ignores = [
            "_archive_diagnostics/",
            "installer_out/",
            "release_upload/",
            "dist/",
            "build/",
            "_HMS_Rollback_Vault/",
            "__pycache__/",
            "*.spec",
            "*.tmp",
            "*.wav",
            "*.flac",
            "*.mp3",
            "*.exe",
            "*.zip",
        ]
        existing_ig = ""
        if os.path.isfile(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                existing_ig = f.read()

        ig_lines = [line.rstrip() for line in existing_ig.splitlines()]
        added_rules = []
        for rule in required_ignores:
            if rule not in ig_lines:
                ig_lines.append(rule)
                added_rules.append(rule)

        if added_rules:
            _atomic_write_text(gitignore_path, "\n".join(ig_lines).strip() + "\n")
            print(f"[SUCCESS] Updated .gitignore with: {added_rules}")
        else:
            print("[INFO] .gitignore already excludes installers, archives, and media binaries.")

        # 2. Point origin to the verified GitHub repo URL and stage changes
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=norm_repo, check=False)
        subprocess.run(["git", "add", "-A"], cwd=norm_repo, check=True)

        # 3. Safety Guard: Unstage any accidental binary or >25 MB file before committing
        staged_proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=norm_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        staged_files = [ln.strip() for ln in staged_proc.stdout.splitlines() if ln.strip()]
        for rel_f in staged_files:
            full_p = os.path.join(norm_repo, rel_f)
            if os.path.isfile(full_p):
                size_mb = os.path.getsize(full_p) / (1024 * 1024)
                if rel_f.lower().endswith((".wav", ".exe", ".zip", ".flac", ".mp3")) or size_mb > 25.0:
                    print(f"[ERROR] Safety Guard unstaged binary/large file: {rel_f} ({size_mb:.2f} MB)")
                    subprocess.run(["git", "reset", "HEAD", rel_f], cwd=norm_repo, check=False)

        # 4. Commit if there are staged diffs
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=norm_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_msg = (
            f"Release {VERSION_TAG}: Admin Windows Installer, Real-Time Stereo PCM Waveform, "
            "MVSep Free-Tier Safe Multi-Pass Queue & Docs"
        )
        if status_proc.stdout.strip():
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=norm_repo, check=True)
            print(f"[SUCCESS] Committed: {commit_msg}")
        else:
            print("[INFO] Working tree already clean; proceeding to tag.")

        # 5. Create/update annotated tag v1.4.0
        subprocess.run(["git", "tag", "-f", "-a", VERSION_TAG, "-m", commit_msg], cwd=norm_repo, check=True)
        print(f"[SUCCESS] Tagged HEAD as {VERSION_TAG}")

        if skip_push:
            print("[INFO] --no-push specified; skipping git push to origin.")
            return True

        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=norm_repo, check=True)
        subprocess.run(["git", "push", "-f", "origin", VERSION_TAG], cwd=norm_repo, check=True)

        print("=" * 75)
        print(f"[SUCCESS] Pushed main branch and tag {VERSION_TAG} to {remote_url}!")
        print("=" * 75)
        return True

    except Exception:
        print("[ERROR] Git staging, tagging, or push failed:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 4: VERIFY INSTALLER BINARY & PRINT GITHUB RELEASES UPLOAD COMMAND
# ==============================================================================
def print_github_release_summary(repo_dir=HMS_REPO_DIR):
    """Checks for the compiled Admin Setup.exe and prints the GitHub Release upload command."""
    norm_repo = os.path.normpath(repo_dir)
    setup_exe = os.path.join(norm_repo, "installer_out", f"HMS_Studio_Suite_{VERSION_TAG}_Setup.exe")
    notes_file = os.path.join(norm_repo, "release_upload", f"RELEASE_NOTES_{VERSION_TAG}.md")

    print("\n" + "=" * 75)
    print(f"[INFO] GitHub Release Asset Check ({VERSION_TAG})")
    print("=" * 75)

    if os.path.isfile(setup_exe):
        mb = round(os.path.getsize(setup_exe) / (1024 * 1024), 2)
        print(f"[SUCCESS] Found Admin Windows Installer ({mb} MB): {setup_exe}")
        print("[INFO] Optional 1-line GitHub CLI command to attach Setup.exe to GitHub Releases:")
        print(
            f'       gh release create {VERSION_TAG} "{setup_exe}" '
            f'--repo bizmarke75/hms-stem-cleaner '
            f'--title "HMS Unified Studio Suite {VERSION_TAG} (Admin Installer + Real-Time Waveform + Free-Tier Multi-Pass)" '
            f'--notes-file "{notes_file}"'
        )
        return setup_exe
    else:
        print(f"[INFO] Admin Setup.exe not found yet at: {setup_exe}")
        print("[INFO] Run 'python.exe build_v1_4_windows_installer.py' whenever you are ready to attach Setup.exe.")
        return None


# ==============================================================================
# ISOLATED TEST DRIVER & ENTRYPOINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="HMS Unified Studio Suite v1.4.0 Cleanup, Docs & GitHub Release Publisher")
    parser.add_argument("--dry-run", action="store_true", help="Preview archive moves & doc updates without changing files or pushing")
    parser.add_argument("--no-push", action="store_true", help="Archive scripts, update docs, and commit locally without pushing to GitHub")
    args = parser.parse_args()

    archive_temporary_v1_4_scripts(HMS_REPO_DIR, dry_run=args.dry_run)
    docs_res = update_readme_devlog_and_release_notes(HMS_REPO_DIR, dry_run=args.dry_run)
    if not docs_res:
        sys.exit(1)

    if not ensure_gitignore_and_push_v1_4_0(
        HMS_REPO_DIR,
        remote_url=REMOTE_URL,
        dry_run=args.dry_run,
        skip_push=args.no_push,
    ):
        sys.exit(1)

    print_github_release_summary(HMS_REPO_DIR)


if __name__ == "__main__":
    main()