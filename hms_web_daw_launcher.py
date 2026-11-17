# Save as: C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py
# Verify Step 1 (Bridge) : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py --test-bridge
# Verify Step 2 (Server) : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py --test-server
# Launch Desktop Web-DAW : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py

import os
import sys
import json
import time
import shutil
import argparse
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import requests

# Ensure the HMS repository directory is in sys.path for backend module imports
HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
if os.path.isdir(HMS_REPO_DIR) and HMS_REPO_DIR not in sys.path:
    sys.path.insert(0, HMS_REPO_DIR)

DEFAULT_HTML_PATH = os.path.join(HMS_REPO_DIR, "hms_web_daw.html")


# ==============================================================================
# COMPONENT 1: PYTHON <-> JAVASCRIPT BRIDGE CLASS (window.pywebview.api)
# ==============================================================================
class HMSWebDawBridge:
    """
    Exposes HMS Stem Cleaner, VST3 Master Mixdown, Rollback Vault, and JSON
    Preset functions directly to the Web-DAW frontend via window.pywebview.api.
    """

    def __init__(self, repo_dir=HMS_REPO_DIR):
        self.repo_dir = os.path.normpath(repo_dir)
        self._window = None
        self.hms_app = None
        self.json_mgr = None
        self.gemini_tuner = None
        self.ai_bridge = None
        self._load_backend_modules()

    def set_window(self, window_obj):
        """Attaches the active pywebview Window instance after creation."""
        self._window = window_obj

    def _load_backend_modules(self):
        """Dynamically imports the verified HMS backend modules with error logging."""
        print("=" * 75)
        print(f"[RUN] Initializing HMSWebDawBridge in: {self.repo_dir}")
        print("=" * 75)

        try:
            import hms_stem_cleaner_app as hms_app
            self.hms_app = hms_app
            print("[SUCCESS] Loaded core DSP engine: hms_stem_cleaner_app.py")
        except Exception:
            print("[ERROR] Failed importing hms_stem_cleaner_app.py:")
            print(traceback.format_exc())

        try:
            import hms_mix_json_manager as json_mgr
            self.json_mgr = json_mgr
            print("[SUCCESS] Loaded JSON Mix Manager: hms_mix_json_manager.py")
        except Exception:
            print("[INFO] hms_mix_json_manager.py not found; using inline JSON fallback.")

        try:
            import hms_gemini_tuner as gemini_tuner
            self.gemini_tuner = gemini_tuner
            print("[SUCCESS] Loaded Gemini Tuner: hms_gemini_tuner.py")
        except Exception:
            print("[INFO] hms_gemini_tuner.py not loaded (optional).")

        try:
            import hms_ai_api_bridge as ai_bridge
            self.ai_bridge = ai_bridge
            print("[SUCCESS] Loaded Local REST & AI Bridge: hms_ai_api_bridge.py")
        except Exception:
            print("[INFO] hms_ai_api_bridge.py not loaded (optional).")

    def get_status(self):
        """
        Health-check method called by the Web-DAW UI on startup to verify
        the Python bridge and load saved API credentials.
        """
        print("[RUN] Web-DAW requested backend status check...")
        try:
            creds = {}
            if self.ai_bridge and hasattr(self.ai_bridge, "load_ai_credentials"):
                creds = self.ai_bridge.load_ai_credentials()
            else:
                cfg_path = Path.home() / ".mvsep_hms_config.json"
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        creds = json.load(f)

            vst3_map = {}
            if self.hms_app and hasattr(self.hms_app, "resolve_vst3_binary_path"):
                vst3_map = self.hms_app.resolve_vst3_binary_path()

            response = {
                "status": "ok",
                "engine_loaded": self.hms_app is not None,
                "vst3_status": {k: bool(v) for k, v in vst3_map.items()},
                "has_mvsep_token": bool(
                    creds.get("mvsep_api_token") or creds.get("mvsep_token")
                ),
                "has_gemini_key": bool(creds.get("gemini_api_key")),
            }
            print(f"[SUCCESS] Bridge status ready: {response}")
            return response

        except Exception:
            print("[ERROR] Failed retrieving bridge status:")
            print(traceback.format_exc())
            return {"status": "error", "message": traceback.format_exc()}

    def save_credentials(self, mvsep_token="", gemini_key=""):
        """Saves MVSep and Gemini API keys to ~/.mvsep_hms_config.json."""
        print("[RUN] Saving API credentials from Web-DAW header...")
        try:
            updates = {}
            if mvsep_token and str(mvsep_token).strip():
                updates["mvsep_api_token"] = str(mvsep_token).strip()
            if gemini_key and str(gemini_key).strip():
                updates["gemini_api_key"] = str(gemini_key).strip()

            if self.ai_bridge and hasattr(self.ai_bridge, "save_ai_credentials"):
                ok = self.ai_bridge.save_ai_credentials(updates)
                return {"status": "ok" if ok else "error"}

            cfg_path = Path.home() / ".mvsep_hms_config.json"
            existing = {}
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing.update(updates)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            print(f"[SUCCESS] Saved credentials -> {cfg_path}")
            return {"status": "ok"}
        except Exception:
            print("[ERROR] Failed saving credentials:")
            print(traceback.format_exc())
            return {"status": "error", "message": traceback.format_exc()}

    def browse_folder(self, title="Select Song Stem Folder"):
        """
        Opens a native Windows folder selection dialog and returns the chosen path
        (plus any existing *_MIX_SETTINGS.json found inside that folder).
        """
        print(f"[RUN] Opening native folder dialog: '{title}'")
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected_dir = filedialog.askdirectory(title=title)
            root.destroy()

            if not selected_dir:
                print("[INFO] Folder selection cancelled by user.")
                return {"status": "cancelled", "path": ""}

            norm_dir = os.path.normpath(selected_dir)
            print(f"[SUCCESS] Selected folder: {norm_dir}")

            saved_mix = None
            if self.json_mgr and hasattr(self.json_mgr, "load_song_mix_json"):
                saved_mix = self.json_mgr.load_song_mix_json(norm_dir)

            return {"status": "ok", "path": norm_dir, "saved_mix": saved_mix}
        except Exception:
            print("[ERROR] Native folder dialog failed:")
            print(traceback.format_exc())
            return {"status": "error", "path": "", "message": traceback.format_exc()}

    def run_clean(self, payload):
        """
        Main execution entry point called by the Web-DAW action buttons:
        Modes: 'autotune', 'dry_run', 'live', 'glue_only', 'gemini_tune', 'rollback'.
        """
        print("=" * 75)
        print(f"[RUN] HMSWebDawBridge.run_clean() invoked with payload: {payload}")
        print("=" * 75)

        if not self.hms_app:
            msg = "hms_stem_cleaner_app.py is not loaded!"
            print(f"[ERROR] {msg}")
            return {"status": "error", "message": msg}

        try:
            if isinstance(payload, str):
                payload = json.loads(payload)

            mode = payload.get("mode", "dry_run")
            song_dir = payload.get("song_dir", "").strip()
            dest_root = payload.get("dest_root", "").strip() or None
            vocal_gate_db = float(payload.get("vocal_gate_db", -33.0))
            bus_weights = payload.get(
                "bus_weights", {"Vocals": 1.08, "Rhythm": 1.04, "Music": 0.90}
            )
            vst_overrides = payload.get("vst_overrides", {})

            if mode == "autotune":
                profile = self.hms_app.analyze_and_autotune_song(song_dir)
                print(f"[SUCCESS] Auto-Tune profile calculated: {profile}")
                return {"status": "ok", "mode": "autotune", "profile": profile}

            elif mode in ("dry_run", "live"):
                is_dry = mode == "dry_run"
                summary = self.hms_app.execute_stem_cleanup(
                    source_dir=song_dir,
                    dest_root=dest_root,
                    dry_run=is_dry,
                    move_source_files=bool(payload.get("move_files", False)),
                    render_master=True,
                    vocal_gate_db=vocal_gate_db,
                    bus_weights=bus_weights,
                    vst_overrides=vst_overrides,
                )
                return {"status": "ok", "mode": mode, "summary": summary}

            elif mode == "glue_only":
                res = self.hms_app.render_master_mixdown(
                    dest_song_dir=song_dir,
                    bus_weights=bus_weights,
                )
                return {"status": "ok", "mode": "glue_only", "result": res}

            elif mode == "rollback":
                song_name = os.path.basename(os.path.normpath(song_dir))
                ok = self.hms_app.restore_song_checkpoint(song_name)
                return {
                    "status": "ok" if ok else "error",
                    "mode": "rollback",
                    "song_name": song_name,
                }

            elif mode == "gemini_tune" and self.gemini_tuner:
                res = self.gemini_tuner.run_on_the_fly_gemini_mix_loop(
                    target_path=song_dir,
                    dest_root=dest_root,
                )
                return {"status": "ok", "mode": "gemini_tune", "result": res}

            else:
                return {"status": "error", "message": f"Unsupported mode: {mode}"}

        except Exception:
            err_trace = traceback.format_exc()
            print(f"[ERROR] Exception in HMSWebDawBridge.run_clean():\n{err_trace}")
            return {"status": "error", "message": err_trace}


# ==============================================================================
# COMPONENT 2: AUTO-START LOCAL REST API SERVER (127.0.0.1:8765)
# ==============================================================================
def ensure_local_rest_server_running(host="127.0.0.1", port=8765):
    """
    Checks if the Local HMS REST API (http://127.0.0.1:8765/health) is already
    online. If not, starts it automatically via hms_ai_api_bridge.py.
    """
    health_url = f"http://{host}:{port}/health"
    print(f"[RUN] Checking if Local HMS REST API is active at: {health_url}")

    try:
        resp = requests.get(health_url, timeout=1.5)
        if resp.status_code == 200:
            print(f"[SUCCESS] Local HMS REST API is already online at {health_url}")
            return True, None
    except Exception:
        print("[INFO] Port 8765 not active yet; starting background server...")

    try:
        import hms_ai_api_bridge as ai_bridge
        srv, _ = ai_bridge.start_local_hms_api_server(host=host, port=port)
        if srv:
            time.sleep(0.25)
            chk = requests.get(health_url, timeout=3.0)
            if chk.status_code == 200:
                print(f"[SUCCESS] Verified Local REST API health check: {chk.json()}")
                return True, srv
    except Exception:
        print("[ERROR] Failed auto-starting Local HMS REST API server:")
        print(traceback.format_exc())

    return False, None


# ==============================================================================
# COMPONENT 3: HTML ASSET LOCATOR & NATIVE DESKTOP WINDOW LAUNCHER
# ==============================================================================
def ensure_web_daw_html_exists(target_html_path=DEFAULT_HTML_PATH):
    """
    Locates hms_web_daw.html in C:\\github\\projects\\hms-stem-cleaner or copies it
    automatically from the user's Downloads folder if downloaded from Canvas.
    """
    norm_target = os.path.normpath(target_html_path)
    if os.path.isfile(norm_target):
        print(f"[SUCCESS] Found Web-DAW UI file: {norm_target}")
        return norm_target

    downloads_candidate = Path.home() / "Downloads" / "hms_web_daw.html"
    if downloads_candidate.is_file():
        shutil.copy2(str(downloads_candidate), norm_target)
        print(f"[SUCCESS] Copied hms_web_daw.html from Downloads -> {norm_target}")
        return norm_target

    print(f"[INFO] {norm_target} not found yet.")
    print("[INFO] Tip: Download 'hms_web_daw.html' from the Canvas preview into:")
    print(f"       {norm_target}")
    return norm_target


def launch_hms_web_daw_desktop(html_path=DEFAULT_HTML_PATH, width=1520, height=920):
    """
    Starts the Local REST API (:8765), initializes HMSWebDawBridge, and opens
    the 337 West Web-DAW inside a native Edge WebView2 window via pywebview
    (or opens the default system browser if pywebview is not installed).
    """
    print("=" * 75)
    print("[RUN] Launching 337 West — HMS Unified Studio Web-DAW Desktop...")
    print("=" * 75)

    # 1. Ensure background REST API (:8765) is running
    api_ok, srv_instance = ensure_local_rest_server_running(port=8765)

    # 2. Initialize the Python <-> JS Bridge
    bridge = HMSWebDawBridge()

    # 3. Resolve HTML path
    resolved_html = ensure_web_daw_html_exists(html_path)
    if not os.path.isfile(resolved_html):
        print(f"[ERROR] Cannot launch UI until hms_web_daw.html is saved to: {resolved_html}")
        return False

    try:
        import webview
        print("[RUN] Opening native Windows Edge WebView2 Studio Window...")
        window = webview.create_window(
            title="337 West Productions — HMS Unified Studio Suite v1.3 (Web-DAW)",
            url=resolved_html,
            js_api=bridge,
            width=width,
            height=height,
            min_size=(1180, 740),
            background_color="#07090e",
            text_select=False,
        )
        bridge.set_window(window)
        webview.start(debug=False)
        print("[SUCCESS] Web-DAW Desktop session closed cleanly.")
        return True

    except ImportError:
        print("[INFO] 'pywebview' package is not installed yet (run: pip install pywebview).")
        print(f"[RUN] Opening Web-DAW in your default browser connected to http://127.0.0.1:8765 ...")
        file_uri = Path(resolved_html).as_uri()
        webbrowser.open(file_uri)
        if srv_instance:
            print("[INFO] Local REST API (:8765) is running. Press Ctrl+C in terminal to stop.")
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                print("\n[INFO] Shutting down Local REST API server...")
                srv_instance.shutdown()
        return True

    except Exception:
        print("[ERROR] Failed launching Web-DAW window:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# ISOLATED VERIFICATION DRIVERS (--test-bridge & --test-server)
# ==============================================================================
def _verify_step1_bridge():
    print("[RUN] Running isolated verification for Component 1: HMSWebDawBridge...")
    bridge = HMSWebDawBridge()
    status = bridge.get_status()
    assert status.get("status") == "ok", "Bridge status check failed!"
    assert status.get("engine_loaded") is True, "hms_stem_cleaner_app failed to load!"
    print("[SUCCESS] COMPONENT 1 (HMSWebDawBridge) VERIFICATION PASSED 100%!")


def _verify_step2_server():
    print("[RUN] Running isolated verification for Component 2: Local REST Server (:8765)...")
    ok, srv = ensure_local_rest_server_running(port=8765)
    assert ok is True, "Local REST API server on port 8765 failed health check!"
    if srv:
        srv.shutdown()
    print("[SUCCESS] COMPONENT 2 (Local REST Server :8765) VERIFICATION PASSED 100%!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS Web-DAW Desktop Bridge & Launcher")
    parser.add_argument("--test-bridge", action="store_true", help="Verify Component 1 (HMSWebDawBridge)")
    parser.add_argument("--test-server", action="store_true", help="Verify Component 2 (Local REST API :8765)")
    parser.add_argument("--html", type=str, default=DEFAULT_HTML_PATH, help="Path to hms_web_daw.html")
    args = parser.parse_args()

    if args.test_bridge:
        _verify_step1_bridge()
    elif args.test_server:
        _verify_step2_server()
    else:
        launch_hms_web_daw_desktop(html_path=args.html)