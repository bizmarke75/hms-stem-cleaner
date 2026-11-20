# Save as: C:\github\projects\hms-stem-cleaner\hms_runtime_paths.py
# Purpose: Decouples read-only installation paths from writable Windows user data
#          so HMS Studio Suite v1.4 can be installed anywhere (e.g., Program Files or D:\Apps).

import os
import sys
import traceback


def resolve_hms_runtime_paths(app_name="HMS Studio Suite"):
    """
    Resolves read-only application bundle paths and writable Windows user-data paths.

    Args:
        app_name (str): Folder name used inside %LOCALAPPDATA% for writable studio data.

    Returns:
        dict | None: Dictionary of verified absolute paths, or None if path setup fails.

    Failure Modes:
        - Returns None and prints full traceback if %LOCALAPPDATA% cannot be created
          or fails the write-permission probe.
    """
    print("=" * 72)
    print(f"[RUN] Resolving runtime & installer paths for: {app_name}")
    print("=" * 72)

    try:
        # Phase 1: Determine read-only installation / bundle root directory.
        # - Frozen PyInstaller (--onedir or --onefile): use _MEIPASS if present, else exe folder.
        # - Unfrozen Python script: use the directory containing this module.
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            bundle_dir = getattr(sys, "_MEIPASS", exe_dir)
            install_dir = exe_dir
            print(f"[INFO] Running in FROZEN mode. exe_dir={exe_dir}")
        else:
            install_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = install_dir
            print(f"[INFO] Running in SCRIPT mode. install_dir={install_dir}")

        # Phase 2: Locate bundled Web-DAW frontend HTML relative to bundle_dir / install_dir.
        candidate_html_paths = [
            os.path.join(bundle_dir, "337_west_hms_unified_studio_web_daw_v1.4.html"),
            os.path.join(install_dir, "337_west_hms_unified_studio_web_daw_v1.4.html"),
            os.path.join(bundle_dir, "hms_web_daw.html"),
            os.path.join(install_dir, "hms_web_daw.html"),
        ]
        html_path = next((p for p in candidate_html_paths if os.path.isfile(p)), candidate_html_paths[0])
        html_exists = os.path.isfile(html_path)
        print(f"[INFO] Resolved Web-DAW HTML path: {html_path} (exists={html_exists})")

        # Phase 3: Determine writable Windows User Data directory (%LOCALAPPDATA%\HMS Studio Suite).
        # Keeping mutable data here prevents UAC PermissionError crashes when installed in Program Files.
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        user_data_dir = os.path.normpath(os.path.join(local_appdata, app_name))
        rollback_vault_dir = os.path.join(user_data_dir, "_HMS_Rollback_Vault")
        logs_dir = os.path.join(user_data_dir, "logs")
        presets_dir = os.path.join(user_data_dir, "presets")
        webview_cache_dir = os.path.join(user_data_dir, "WebView2Cache")
        os.makedirs(webview_cache_dir, exist_ok=True)
        # Prevent Edge WebView2 Access Denied errors when launched from Program Files
        os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", webview_cache_dir)

        # Keep shared API key vault compatible with existing ~/.mvsep_hms_config.json location.
        config_path = os.path.normpath(os.path.join(os.path.expanduser("~"), ".mvsep_hms_config.json"))

        # Phase 4: Create writable directories and verify write permissions with a probe file.
        for folder in (user_data_dir, rollback_vault_dir, logs_dir, presets_dir):
            os.makedirs(folder, exist_ok=True)
            print(f"[INFO] Verified writable directory: {folder}")

        probe_file = os.path.join(logs_dir, ".write_probe.tmp")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        print("[SUCCESS] Write-permission probe passed inside %LOCALAPPDATA%.")

        paths = {
            "is_frozen": bool(getattr(sys, "frozen", False)),
            "install_dir": install_dir,
            "bundle_dir": bundle_dir,
            "html_path": html_path,
            "html_exists": html_exists,
            "user_data_dir": user_data_dir,
            "rollback_vault_dir": rollback_vault_dir,
            "logs_dir": logs_dir,
            "presets_dir": presets_dir,
            "config_path": config_path,
        }

        print("[SUCCESS] All HMS v1.4 runtime paths resolved cleanly.")
        return paths

    except Exception:
        print("[ERROR] Failed while resolving HMS runtime paths:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# ISOLATED TEST DRIVER (Run directly in PowerShell to verify Function 1)
# ==============================================================================
if __name__ == "__main__":
    print("=== Running Isolated Verification for hms_runtime_paths.py ===")
    result = resolve_hms_runtime_paths()
    if result:
        print("\n--- Resolved Path Contract ---")
        for key, value in result.items():
            print(f"  {key:20s}: {value}")
        print("\n[SUCCESS] Step 1 verification passed! Ready for Step 2 (--onedir bundle builder).")
    else:
        print("\n[ERROR] Step 1 verification failed. Inspect traceback above.")