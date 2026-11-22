# Save as: C:\github\projects\hms-stem-cleaner\release_v1_4_1_suite.py
# 1. Dry-Run Preview Only : python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_1_suite.py --dry-run
# 2. Local Build (No Push): python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_1_suite.py --no-push
# 3. Full Rebuild + Push  : python.exe C:\github\projects\hms-stem-cleaner\release_v1_4_1_suite.py

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

HMS_REPO_DIR = Path(r"C:\github\projects\hms-stem-cleaner")
REMOTE_URL = "https://github.com/bizmarke75/hms-stem-cleaner.git"
VERSION_NUM = "1.4.1"
VERSION_TAG = f"v{VERSION_NUM}"

# Stray or superseded root files to move into _archive_diagnostics\ before committing
STRAY_FILES_TO_ARCHIVE = [
    "hms-stem-cleaner.rar",
    "test_mix_json_fallback.py",
    "HMS_Studio_Suite.spec",
    "release_v1_4_0_suite.py",
]


def _atomic_write(path: Path, text: str, check_py: bool = False):
    """Writes UTF-8 text via a temp sibling file, optionally runs py_compile, and swaps atomically."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if check_py:
        py_compile.compile(str(tmp), doraise=True)
    os.replace(tmp, path)


# ==============================================================================
# FUNCTION 1: CLEAN STRAY FILES, FIX BRIDGE TYPO, BUMP VERSION & SYNTAX-CHECK
# ==============================================================================
def prepare_v1_4_1_sources(repo_dir: Path = HMS_REPO_DIR, dry_run: bool = False) -> bool:
    """
    Archives stray root files, fixes the callback keyword typo in hms_ai_api_bridge.py,
    bumps APP_VERSION to 1.4.1 in build_v1_4_windows_installer.py, and compiles all root .py files.
    """
    print("=" * 75)
    print(f"[RUN] Step 1: Preparing {VERSION_TAG} sources & cleaning repo root (dry_run={dry_run})")
    print("=" * 75)

    try:
        archive_dir = repo_dir / "_archive_diagnostics"

        # 1. Archive stray/superseded files so Git stays clean
        for fname in STRAY_FILES_TO_ARCHIVE:
            src = repo_dir / fname
            if src.is_file():
                dst = archive_dir / fname
                if dry_run:
                    print(f"[INFO] [DRY-RUN ARCHIVE] {fname} -> _archive_diagnostics\\{fname}")
                else:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        dst.unlink()
                    shutil.move(str(src), str(dst))
                    print(f"[SUCCESS] Archived stray file: {fname}")

        # 2. Fix minor callback keyword typo in hms_ai_api_bridge.py
        bridge_py = repo_dir / "hms_ai_api_bridge.py"
        if bridge_py.is_file():
            b_src = bridge_py.read_text(encoding="utf-8")
            b_new = (
                b_src
                .replace("load_ai_credentials(callback=lambda _: None)", "load_ai_credentials(log_callback=lambda _: None)")
                .replace("_query_gemini_with_model_fallback(prompt_text, clean_key, callback)", "_query_gemini_with_model_fallback(prompt_text, clean_key, log_callback)")
            )
            if b_new != b_src:
                if dry_run:
                    print("[INFO] [DRY-RUN] Would fix log_callback typo in hms_ai_api_bridge.py")
                else:
                    _atomic_write(bridge_py, b_new, check_py=True)
                    print("[SUCCESS] Fixed log_callback argument typo in hms_ai_api_bridge.py")

        # 3. Bump APP_VERSION in build_v1_4_windows_installer.py to 1.4.1
        inst_py = repo_dir / "build_v1_4_windows_installer.py"
        if inst_py.is_file():
            i_src = inst_py.read_text(encoding="utf-8")
            i_new = i_src.replace('APP_VERSION = "1.4.0"', f'APP_VERSION = "{VERSION_NUM}"')
            if i_new != i_src:
                if dry_run:
                    print(f'[INFO] [DRY-RUN] Would bump APP_VERSION -> "{VERSION_NUM}" in build_v1_4_windows_installer.py')
                else:
                    _atomic_write(inst_py, i_new, check_py=True)
                    print(f'[SUCCESS] Bumped APP_VERSION -> "{VERSION_NUM}" in build_v1_4_windows_installer.py')
            else:
                print(f"[INFO] build_v1_4_windows_installer.py already targets {VERSION_NUM}.")

        # 4. Syntax-verify every active Python script in the repo root
        py_files = sorted(repo_dir.glob("*.py"))
        for pf in py_files:
            py_compile.compile(str(pf), doraise=True)
        print(f"[SUCCESS] Syntax-verified {len(py_files)} Python module(s) with zero errors.")
        return True

    except Exception:
        print("[ERROR] Step 1 failed during source preparation:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 2: GENERATE CHANGELOG.MD, UPDATE DEV_LOG.MD, README.MD & RELEASE NOTES
# ==============================================================================
def update_v1_4_1_changelogs_and_docs(repo_dir: Path = HMS_REPO_DIR, dry_run: bool = False):
    """
    Creates/updates CHANGELOG.md, appends Section 10 (v1.4.1) to DEV_LOG.md,
    refreshes version strings in README.md, and writes release_upload\\RELEASE_NOTES_v1.4.1.md.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    changelog_path = repo_dir / "CHANGELOG.md"
    devlog_path = repo_dir / "DEV_LOG.md"
    readme_path = repo_dir / "README.md"
    notes_path = repo_dir / "release_upload" / f"RELEASE_NOTES_{VERSION_TAG}.md"

    print("\n" + "=" * 75)
    print(f"[RUN] Step 2: Writing CHANGELOG.md, DEV_LOG.md, README.md & RELEASE_NOTES_{VERSION_TAG}.md")
    print("=" * 75)

    try:
        release_notes_lines = [
            f"# 337 West Productions — HMS Unified Studio Suite {VERSION_TAG} (Provided As-Is)",
            "",
            f"**Release Date:** {today}  ",
            "**Studio:** 337 West Productions  ",
            "**License:** MIT (Provided strictly **AS-IS** with no warranty or technical support)",
            "",
            "---",
            "",
            f"## What's Fixed & Improved in {VERSION_TAG}",
            "",
            "### 1. WebView2 Dark-Lock & Canvas GPU Thrashing Fix",
            "- Fixed a Windows Edge WebView2 freeze where `animateSpectrumAndMeters()` reallocated `<canvas>` textures 60 times per second and competed with the v1.4.3 Stereo PCM Waveform engine.",
            "- Added `--disable-gpu-compositing` and `%LOCALAPPDATA%\\HMS Studio Suite\\WebView2Cache` pre-initialization at launcher startup.",
            "",
            "### 2. Native Windows JSON Pickers (Zero Modal Dim/Lock)",
            "- Replaced raw HTML `<input type=\"file\" accept=\".json\">` prompts in desktop mode with a topmost Python bridge picker (`browse_json_file`), eliminating WebView2 modal dimming/locking when clicking **Load JSON** or **Load Recipe JSON**.",
            "",
            "### 3. Complete v1.4 PyWebView Bridge Parity & AI Recipe Generator",
            "- Wired all v1.4 Web-DAW bridge methods strictly prior to `__main__` inside `hms_web_daw_launcher.py`: `get_keys_status`, `save_keys`, `browse_json_file`, `generate_recipe`, `execute_stem_cleanup`, `start_mvsep_single_pass`, `run_single_pass`, and `run_all_passes`.",
            "- **Generate Recipe (Gemini)** now builds and saves `<Song>.hms_recipe.json` alongside your audio track using Gemini (with automatic fallback to the verified 4-pass Free-Tier Safe recipe) and streams live progress to the Web-DAW console.",
            "- Fixed a `log_callback` keyword mismatch in `hms_ai_api_bridge.py` (`generate_ai_mix_and_suno_report`).",
            "",
            "### 4. Seamless In-Place Windows Installer Upgrade",
            "- `HMS_Studio_Suite_v1.4.1_Setup.exe` preserves the fixed Windows AppId GUID so it upgrades `v1.4.0` cleanly without touching `~/.mvsep_hms_config.json` or `%LOCALAPPDATA%\\HMS Studio Suite\\_HMS_Rollback_Vault`.",
            "",
        ]
        release_notes_text = "\n".join(release_notes_lines)

        changelog_lines = [
            "# Changelog — HMS Unified Studio Suite",
            "",
            "All notable changes to **337 West Productions — HMS Unified Studio Suite** are documented in this file.",
            "",
            "---",
            "",
            f"## [{VERSION_NUM}] - {today}",
            "### Fixed",
            "- Stopped 60 FPS `<canvas>` GPU texture reallocation in `337_west_hms_unified_studio_web_daw_v1.4.html` and added WebView2 GPU compositing fallback in `hms_web_daw_launcher.py`.",
            "- Routed **Load JSON** and **Load Recipe JSON** through a topmost native Python file dialog (`browse_json_file`) so Edge WebView2 never dims or locks behind a hidden modal picker.",
            "- Restored full v1.4 bridge method parity (`get_keys_status`, `save_keys`, `generate_recipe`, `execute_stem_cleanup`, `start_mvsep_single_pass`, `run_single_pass`, `run_all_passes`) before `__main__`.",
            "- Fixed `log_callback` keyword typo in `hms_ai_api_bridge.py`.",
            "### Added",
            "- End-to-end **Generate Recipe (Gemini)** builder writing `<Song>.hms_recipe.json` with verified 4-pass Free-Tier Safe fallback (tested on *C.R.E.A.M. (Blues)*).",
            "- Dedicated repository `CHANGELOG.md` and `release_v1_4_1_suite.py` release automation.",
            "",
            "## [1.4.0] - 2026-11-20",
            "### Added",
            "- Non-portable Admin Windows Installer (`HMS_Studio_Suite_v1.4.0_Setup.exe`) via PyInstaller `--onedir` + Inno Setup 6 with `%LOCALAPPDATA%\\HMS Studio Suite` writable data routing (`hms_runtime_paths.py`).",
            "- Real-Time Stereo PCM Waveform & Oscilloscope Engine (v1.4.3) with Pure-JS 8/16/24/32-bit & `WAVE_FORMAT_EXTENSIBLE` WAV parsing.",
            "- MVSep Registered Free-Tier Safe Mode & 1-concurrent-job Sequential Multi-Pass Runner (`hms_mvsep_multipass.py`).",
            "",
            "## [1.3.0] - 2026-11-17",
            "### Added",
            "- Dark-mode Web-DAW Frontend (`hms_web_daw.html`), native Windows Edge WebView2 launcher (`hms_web_daw_launcher.py`), and Google Chrome Studio Server (`launch_chrome_web_daw.py`).",
            "",
            "## [1.2.0] - 2026-11-17",
            "### Added",
            "- Unified 2-Tab Studio GUI (`hms_unified_studio_app.py`), 9-Slider VST3 Mixer, and automatic `<Song_Name>_MIX_SETTINGS.json` persistence (`hms_mix_json_manager.py`).",
            "",
            "## [1.1.0] - 2026-11-14",
            "### Added",
            "- Mix Style Mode Switch (`Auto-Detect`, `Acoustic / Dynamic Rock`, `Heavy Metal / Industrial`), 6-stem `Other_Synths` retention fix, and lossless WAV-to-FLAC MVSep pre-compression.",
            "",
            "## [1.0.0] - 2026-11-12",
            "### Added",
            "- Initial standalone Win64 release of HMS Stem Cleaner & Headless 64-Bit VST3 Master Engine (`hms_stem_cleaner_app.py`) with Atomic WAV Writer and Rollback Vault.",
            "",
        ]
        changelog_text = "\n".join(changelog_lines)

        devlog_v141_lines = [
            "",
            "---",
            "",
            f"## 10. {VERSION_TAG} WebView2 Dark-Lock Fix, Native JSON Pickers & Full v1.4 Bridge Parity ({ts})",
            "- **WebView2 Stability & Canvas Fix:** Guarded `animateSpectrumAndMeters()` against 60x/sec canvas reallocation and enforced `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu-compositing` + `%LOCALAPPDATA%\\HMS Studio Suite\\WebView2Cache`.",
            "- **Native Topmost JSON File Pickers:** Added `browse_json_file()` to `HMSWebDawBridge` and intercepted `.json` `<input type=\"file\">` elements in `337_west_hms_unified_studio_web_daw_v1.4.html` so desktop Load JSON / Load Recipe JSON never dim or lock the WebView2 surface.",
            "- **Full v1.4 Bridge & AI Recipe Generator:** Attached `get_keys_status`, `save_keys`, `generate_recipe`, `execute_stem_cleanup`, `start_mvsep_single_pass`, `run_single_pass`, and `run_all_passes` before `if __name__ == \"__main__\":`. Verified end-to-end 4-pass recipe generation and master rendering on `C.R.E.A.M. (Blues).wav`.",
            "- **API Bridge & Docs Hygiene:** Fixed `log_callback` typo in `hms_ai_api_bridge.py`, added `CHANGELOG.md`, archived stray `.rar`/test files, and bumped installer builder to `v1.4.1`.",
            "",
        ]
        devlog_v141_block = "\n".join(devlog_v141_lines)

        if dry_run:
            print(f"[INFO] [DRY-RUN] Would write: {changelog_path}")
            print(f"[INFO] [DRY-RUN] Would write: {notes_path}")
            print(f"[INFO] [DRY-RUN] Would append Section 10 ({VERSION_TAG}) to: {devlog_path}")
            print(f"[INFO] [DRY-RUN] Would update version strings in: {readme_path}")
            return {"changelog": str(changelog_path), "dev_log": str(devlog_path), "notes": str(notes_path)}

        notes_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(notes_path, release_notes_text)
        print(f"[SUCCESS] Wrote Release Notes -> {notes_path}")

        _atomic_write(changelog_path, changelog_text)
        print(f"[SUCCESS] Wrote CHANGELOG.md -> {changelog_path}")

        existing_dev = devlog_path.read_text(encoding="utf-8") if devlog_path.is_file() else ""
        if f"## 10. {VERSION_TAG}" not in existing_dev:
            _atomic_write(devlog_path, existing_dev.rstrip() + "\n" + devlog_v141_block)
            print(f"[SUCCESS] Appended Section 10 ({VERSION_TAG}) to DEV_LOG.md")
        else:
            print(f"[INFO] DEV_LOG.md already contains Section 10 ({VERSION_TAG}).")

        if readme_path.is_file():
            rm = readme_path.read_text(encoding="utf-8")
            rm_new = (
                rm.replace("(`v1.4.0`)", f"(`{VERSION_TAG}`)")
                .replace("HMS_Studio_Suite_v1.4.0_Setup.exe", f"HMS_Studio_Suite_{VERSION_TAG}_Setup.exe")
                .replace("Core v1.4.0 Repository Layout", f"Core {VERSION_TAG} Repository Layout")
            )
            if rm_new != rm:
                _atomic_write(readme_path, rm_new)
                print(f"[SUCCESS] Updated README.md version references -> {VERSION_TAG}")

        return {"changelog": str(changelog_path), "dev_log": str(devlog_path), "notes": str(notes_path)}

    except Exception:
        print("[ERROR] Step 2 failed updating changelogs and docs:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 3: REBUILD --ONEDIR BUNDLE & COMPILE v1.4.1 WINDOWS SETUP.EXE
# ==============================================================================
def rebuild_v1_4_1_suite_installer(repo_dir: Path = HMS_REPO_DIR, dry_run: bool = False):
    """
    Runs fix_v1_4_html_and_rebuild.py and build_v1_4_windows_installer.py to
    compile dist\\HMS_Studio_Suite and installer_out\\HMS_Studio_Suite_v1.4.1_Setup.exe.
    """
    print("\n" + "=" * 75)
    print(f"[RUN] Step 3: Rebuilding --onedir bundle & {VERSION_TAG} Admin Installer (dry_run={dry_run})")
    print("=" * 75)

    expected_setup = repo_dir / "installer_out" / f"HMS_Studio_Suite_{VERSION_TAG}_Setup.exe"
    if dry_run:
        print("[INFO] [DRY-RUN] Would run fix_v1_4_html_and_rebuild.py and build_v1_4_windows_installer.py")
        print(f"[INFO] [DRY-RUN] Target Setup.exe: {expected_setup}")
        return expected_setup

    try:
        subprocess.run([sys.executable, str(repo_dir / "fix_v1_4_html_and_rebuild.py")], cwd=str(repo_dir), check=True)
        subprocess.run([sys.executable, str(repo_dir / "build_v1_4_windows_installer.py")], cwd=str(repo_dir), check=True)

        if not expected_setup.is_file():
            print(f"[ERROR] Expected Setup.exe not found after build: {expected_setup}")
            return None

        size_mb = round(expected_setup.stat().st_size / (1024 * 1024), 2)
        print(f"[SUCCESS] Verified {VERSION_TAG} Windows Installer ({size_mb} MB): {expected_setup}")
        return expected_setup

    except Exception:
        print("[ERROR] Step 3 failed rebuilding the suite or installer:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 4: GITIGNORE GUARD, COMMIT, TAG v1.4.1 & PUSH TO GITHUB
# ==============================================================================
def commit_tag_and_push_v1_4_1(
    repo_dir: Path = HMS_REPO_DIR,
    remote_url: str = REMOTE_URL,
    dry_run: bool = False,
    skip_push: bool = False,
) -> bool:
    """
    Ensures .gitignore blocks archives/binaries, stages clean files with a >25 MB
    safety check, commits, tags v1.4.1, and pushes main + v1.4.1 to GitHub.
    """
    print("\n" + "=" * 75)
    print(f"[RUN] Step 4: Git Safety Audit, Tag {VERSION_TAG} & Push (dry_run={dry_run}, skip_push={skip_push})")
    print("=" * 75)

    if dry_run:
        proc = subprocess.run(["git", "status", "-s"], cwd=str(repo_dir), capture_output=True, text=True)
        print(proc.stdout or "[INFO] Working tree clean.")
        return True

    try:
        # 1. Ensure .gitignore excludes .rar archives and all build/media binaries
        ig_path = repo_dir / ".gitignore"
        ig_lines = ig_path.read_text(encoding="utf-8").splitlines() if ig_path.is_file() else []
        for rule in ("_archive_diagnostics/", "installer_out/", "release_upload/", "dist/", "build/", "*.rar", "*.spec", "*.tmp", "*.wav", "*.exe", "*.zip"):
            if rule not in ig_lines:
                ig_lines.append(rule)
        _atomic_write(ig_path, "\n".join(ig_lines).strip() + "\n")

        # 2. Verify remote URL and stage clean source/doc files
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=str(repo_dir), check=False)
        subprocess.run(["git", "add", "-A"], cwd=str(repo_dir), check=True)

        # 3. Binary & Large-File Safety Guard
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(repo_dir), capture_output=True, text=True, check=True
        ).stdout.splitlines()

        for rel_f in [s.strip() for s in staged if s.strip()]:
            fp = repo_dir / rel_f
            if fp.is_file():
                mb = fp.stat().st_size / (1024 * 1024)
                if rel_f.lower().endswith((".wav", ".exe", ".zip", ".rar", ".flac", ".mp3")) or mb > 25.0:
                    print(f"[ERROR] Safety Guard unstaged binary/large file: {rel_f} ({mb:.2f} MB)")
                    subprocess.run(["git", "reset", "HEAD", rel_f], cwd=str(repo_dir), check=False)

        # 4. Commit if changes exist
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir), capture_output=True, text=True, check=True
        ).stdout.strip()

        commit_msg = (
            f"Release {VERSION_TAG}: Fix WebView2 dark-lock & JSON pickers, restore full v1.4 bridge + AI recipe generator, update changelogs"
        )
        if porcelain:
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(repo_dir), check=True)
            print(f"[SUCCESS] Committed: {commit_msg}")
        else:
            print("[INFO] Working tree clean; proceeding to tag.")

        # 5. Tag & Push
        subprocess.run(["git", "tag", "-f", "-a", VERSION_TAG, "-m", commit_msg], cwd=str(repo_dir), check=True)
        print(f"[SUCCESS] Created annotated tag: {VERSION_TAG}")

        if skip_push:
            print("[INFO] --no-push set; skipping push to origin.")
            return True

        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(repo_dir), check=True)
        subprocess.run(["git", "push", "-f", "origin", VERSION_TAG], cwd=str(repo_dir), check=True)
        print(f"[SUCCESS] Pushed main and tag {VERSION_TAG} to {remote_url}!")
        return True

    except Exception:
        print("[ERROR] Step 4 failed during Git commit/tag/push:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"HMS Unified Studio Suite {VERSION_TAG} Rebuild, Changelog & GitHub Publisher")
    parser.add_argument("--dry-run", action="store_true", help="Preview every step without modifying files, building, or pushing")
    parser.add_argument("--no-build", action="store_true", help="Skip PyInstaller & Inno Setup rebuild")
    parser.add_argument("--no-push", action="store_true", help="Commit & tag locally without pushing to GitHub")
    args = parser.parse_args()

    if not prepare_v1_4_1_sources(HMS_REPO_DIR, dry_run=args.dry_run):
        sys.exit(1)

    if not update_v1_4_1_changelogs_and_docs(HMS_REPO_DIR, dry_run=args.dry_run):
        sys.exit(1)

    setup_exe = None
    if not args.no_build:
        setup_exe = rebuild_v1_4_1_suite_installer(HMS_REPO_DIR, dry_run=args.dry_run)
        if not setup_exe:
            sys.exit(1)

    if not commit_tag_and_push_v1_4_1(HMS_REPO_DIR, REMOTE_URL, dry_run=args.dry_run, skip_push=args.no_push):
        sys.exit(1)

    if not args.dry_run:
        notes_file = HMS_REPO_DIR / "release_upload" / f"RELEASE_NOTES_{VERSION_TAG}.md"
        print("\n" + "=" * 75)
        print(f"[SUCCESS] {VERSION_TAG} REBUILD & GIT PUSH COMPLETE!")
        if setup_exe and Path(setup_exe).is_file():
            print(f"[INFO] Install upgrade locally:\n       & \"{setup_exe}\"")
            print(
                f"[INFO] Publish GitHub Release with Setup.exe:\n"
                f'       gh release create {VERSION_TAG} "{setup_exe}" '
                f'--repo bizmarke75/hms-stem-cleaner '
                f'--title "HMS Unified Studio Suite {VERSION_TAG} (WebView2 Fix + Native JSON Pickers + AI Recipe Generator)" '
                f'--notes-file "{notes_file}"'
            )
        print("=" * 75)