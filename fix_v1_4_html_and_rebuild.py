# Save as: C:\github\projects\hms-stem-cleaner\fix_v1_4_html_and_rebuild.py
# Quick 1-Second Patch Test : python.exe C:\github\projects\hms-stem-cleaner\fix_v1_4_html_and_rebuild.py --quick
# Clean Full --onedir Build : python.exe C:\github\projects\hms-stem-cleaner\fix_v1_4_html_and_rebuild.py

import importlib.util
import os
import py_compile
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
V14_HTML_NAME = "337_west_hms_unified_studio_web_daw_v1.4.html"
LEGACY_HTML_NAME = "hms_web_daw.html"


# ==============================================================================
# FUNCTION 1: DISCOVER, STAGE & SYNC v1.4 WEB-DAW HTML FILES
# ==============================================================================
def resolve_and_stage_v1_4_html(repo_dir=HMS_REPO_DIR):
    """
    Ensures 337_west_hms_unified_studio_web_daw_v1.4.html exists in repo_dir
    and updates hms_runtime_paths.py to prioritize it before legacy hms_web_daw.html.

    Args:
        repo_dir (str): Path to the HMS Studio Suite repository root.

    Returns:
        list[str]: Verified list of absolute HTML paths to bundle via PyInstaller.
    """
    norm_repo = os.path.normpath(repo_dir)
    downloads_dir = Path.home() / "Downloads"

    v14_repo_path = os.path.join(norm_repo, V14_HTML_NAME)
    legacy_repo_path = os.path.join(norm_repo, LEGACY_HTML_NAME)

    print("=" * 75)
    print(f"[RUN] Checking Web-DAW UI HTML files in: {norm_repo}")
    print("=" * 75)

    try:
        # Phase 1: Locate 337_west_hms_unified_studio_web_daw_v1.4.html (repo -> Downloads -> legacy alias)
        if os.path.isfile(v14_repo_path):
            print(f"[INFO] Found v1.4 UI file in repo root: {v14_repo_path}")
        else:
            dl_v14 = downloads_dir / V14_HTML_NAME
            if dl_v14.is_file():
                shutil.copy2(str(dl_v14), v14_repo_path)
                print(f"[SUCCESS] Copied v1.4 UI file from Downloads -> {v14_repo_path}")
            elif os.path.isfile(legacy_repo_path):
                shutil.copy2(legacy_repo_path, v14_repo_path)
                print(f"[INFO] Created v1.4 UI file from existing {LEGACY_HTML_NAME} -> {v14_repo_path}")
            else:
                dl_legacy = downloads_dir / LEGACY_HTML_NAME
                if dl_legacy.is_file():
                    shutil.copy2(str(dl_legacy), v14_repo_path)
                    shutil.copy2(str(dl_legacy), legacy_repo_path)
                    print(f"[SUCCESS] Copied {LEGACY_HTML_NAME} from Downloads and staged as {V14_HTML_NAME}")
                else:
                    print(f"[ERROR] Could not locate {V14_HTML_NAME} or {LEGACY_HTML_NAME} in repo or Downloads.")
                    return []

        # Collect all existing Web-DAW HTML files to bundle so both v1.4 and fallback references work
        staged_htmls = [v14_repo_path]
        if os.path.isfile(legacy_repo_path):
            staged_htmls.append(legacy_repo_path)

        # Phase 2: Update hms_runtime_paths.py so it prioritizes v1.4 HTML first
        runtime_paths_file = os.path.join(norm_repo, "hms_runtime_paths.py")
        if os.path.isfile(runtime_paths_file):
            with open(runtime_paths_file, "r", encoding="utf-8") as f:
                rt_code = f.read()

            if V14_HTML_NAME not in rt_code:
                old_candidates = (
                    '        candidate_html_paths = [\n'
                    '            os.path.join(bundle_dir, "hms_web_daw.html"),\n'
                    '            os.path.join(install_dir, "hms_web_daw.html"),\n'
                    '        ]'
                )
                new_candidates = (
                    '        candidate_html_paths = [\n'
                    f'            os.path.join(bundle_dir, "{V14_HTML_NAME}"),\n'
                    f'            os.path.join(install_dir, "{V14_HTML_NAME}"),\n'
                    '            os.path.join(bundle_dir, "hms_web_daw.html"),\n'
                    '            os.path.join(install_dir, "hms_web_daw.html"),\n'
                    '        ]'
                )
                if old_candidates in rt_code:
                    updated_rt = rt_code.replace(old_candidates, new_candidates, 1)
                    tmp_path = f"{runtime_paths_file}.tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write(updated_rt)
                    py_compile.compile(tmp_path, doraise=True)
                    os.replace(tmp_path, runtime_paths_file)
                    print("[SUCCESS] Updated hms_runtime_paths.py to prioritize v1.4 HTML.")

        print(f"[SUCCESS] Staged HTML files ready for bundle: {staged_htmls}")
        return staged_htmls

    except Exception:
        print("[ERROR] Failed staging v1.4 Web-DAW HTML files:")
        print(traceback.format_exc())
        return []


# ==============================================================================
# FUNCTION 2: QUICK-PATCH EXISTING BUNDLE OR CLEAN REBUILD --ONEDIR
# ==============================================================================
def rebuild_v1_4_onedir_bundle(
    repo_dir=HMS_REPO_DIR,
    html_files=None,
    app_name="HMS_Studio_Suite",
    quick_patch_only=False,
):
    """
    Either quick-copies the v1.4 HTML into an existing dist\\HMS_Studio_Suite\\_internal
    folder (--quick) or performs a clean PyInstaller --onedir rebuild bundling all HTML assets.

    Args:
        repo_dir (str): Repository root directory.
        html_files (list[str]): Staged HTML file paths returned by Function 1.
        app_name (str): Executable and output folder name.
        quick_patch_only (bool): If True, copies HTML straight into _internal without recompiling.

    Returns:
        str | None: Path to the verified dist\\HMS_Studio_Suite folder, or None on error.
    """
    norm_repo = os.path.normpath(repo_dir)
    dist_root = os.path.join(norm_repo, "dist")
    bundle_dir = os.path.join(dist_root, app_name)
    internal_dir = os.path.join(bundle_dir, "_internal")
    exe_path = os.path.join(bundle_dir, f"{app_name}.exe")
    launcher_path = os.path.join(norm_repo, "hms_web_daw_launcher.py")

    if not html_files:
        print("[ERROR] No staged HTML files were provided to rebuild_v1_4_onedir_bundle().")
        return None

    try:
        # Fast path: copy missing v1.4 HTML directly into _internal for instant verification
        if quick_patch_only:
            print("\n" + "=" * 75)
            print(f"[RUN] Quick-Patching existing bundle folder: {internal_dir}")
            print("=" * 75)

            if not os.path.isdir(internal_dir):
                print(f"[ERROR] Existing _internal directory not found: {internal_dir}")
                print("[INFO] Run without --quick to compile the full --onedir bundle.")
                return None

            for html_src in html_files:
                dest_internal = os.path.join(internal_dir, os.path.basename(html_src))
                shutil.copy2(html_src, dest_internal)
                print(f"[SUCCESS] Copied -> {dest_internal}")

            return bundle_dir

        # Full clean PyInstaller --onedir build
        print("\n" + "=" * 75)
        print(f"[RUN] Rebuilding clean PyInstaller --onedir bundle -> {bundle_dir}")
        print("=" * 75)

        if not os.path.isfile(launcher_path):
            print(f"[ERROR] Missing launcher script: {launcher_path}")
            return None

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name", app_name,
            "--distpath", dist_root,
            "--paths", norm_repo,
        ]

        # Bundle every staged HTML file into _internal (sys._MEIPASS root)
        for html_src in html_files:
            cmd.extend(["--add-data", f"{html_src};."])
            print(f"[INFO] Adding bundled UI asset: {os.path.basename(html_src)}")

        # Include all HMS backend modules and native libraries
        for mod in (
            "hms_runtime_paths",
            "hms_stem_cleaner_app",
            "hms_mix_json_manager",
            "hms_gemini_tuner",
            "hms_ai_api_bridge",
            "hms_mvsep_multipass",
            "requests",
        ):
            cmd.extend(["--hidden-import", mod])

        for pkg in ("webview", "pedalboard", "numpy"):
            cmd.extend(["--collect-all", pkg])

        if importlib.util.find_spec("soundfile") is not None:
            cmd.extend(["--collect-all", "soundfile"])

        icon_candidate = os.path.join(norm_repo, "assets", "hms.ico")
        if os.path.isfile(icon_candidate):
            cmd.extend(["--icon", icon_candidate, "--add-data", f"{icon_candidate};assets"])

        cmd.append(launcher_path)

        print("[INFO] Compiling clean --onedir bundle (~45-75 seconds)...")
        subprocess.run(cmd, cwd=norm_repo, check=True)

        # Verify both the executable and the exact v1.4 HTML file exist inside the bundle
        bundled_v14 = os.path.join(internal_dir, V14_HTML_NAME)
        if not os.path.isfile(exe_path) or not os.path.isfile(bundled_v14):
            print(f"[ERROR] Post-build verification failed! exe={os.path.isfile(exe_path)}, v14_html={os.path.isfile(bundled_v14)}")
            return None

        print("=" * 75)
        print("[SUCCESS] CLEAN v1.4 --onedir BUNDLE VERIFIED!")
        print(f"          Executable : {exe_path}")
        print(f"          UI HTML    : {bundled_v14}")
        print("=" * 75)
        return bundle_dir

    except Exception:
        print("[ERROR] Failed updating/rebuilding v1.4 --onedir bundle:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# ISOLATED TEST DRIVER & ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    quick_mode = "--quick" in sys.argv
    staged = resolve_and_stage_v1_4_html(HMS_REPO_DIR)
    if not staged:
        sys.exit(1)

    bundle = rebuild_v1_4_onedir_bundle(HMS_REPO_DIR, staged, quick_patch_only=quick_mode)
    if bundle:
        print("\n[SUCCESS] Ready to launch dist\\HMS_Studio_Suite\\HMS_Studio_Suite.exe!")
        sys.exit(0)
    else:
        sys.exit(1)