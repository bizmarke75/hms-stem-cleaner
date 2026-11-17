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




# === WEB_DAW_BRIDGE_KEY_PERSISTENCE_PATCH ===
def _patch_bridge_key_methods():
    orig_get_status = HMSWebDawBridge.get_status

    def _read_disk_creds(self):
        if self.ai_bridge and hasattr(self.ai_bridge, "load_ai_credentials"):
            return self.ai_bridge.load_ai_credentials(log_callback=lambda _: None)
        cfg_path = Path.home() / ".mvsep_hms_config.json"
        if cfg_path.is_file():
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _patched_get_status(self):
        base = orig_get_status(self)
        if not isinstance(base, dict):
            base = {"status": "ok"}
        creds = _read_disk_creds(self)
        mv_key = str(creds.get("mvsep_api_token") or creds.get("mvsep_token") or "").strip()
        gm_key = str(creds.get("gemini_api_key") or creds.get("gemini_key") or "").strip()
        base["mvsep_api_token"] = mv_key
        base["gemini_api_key"] = gm_key
        base["has_mvsep_token"] = bool(mv_key)
        base["has_gemini_key"] = bool(gm_key)
        return base

    def _load_credentials(self):
        creds = _read_disk_creds(self)
        mv_key = str(creds.get("mvsep_api_token") or creds.get("mvsep_token") or "").strip()
        gm_key = str(creds.get("gemini_api_key") or creds.get("gemini_key") or "").strip()
        print(f"[INFO] Web-DAW loaded saved keys (MVSep={bool(mv_key)}, Gemini={bool(gm_key)})")
        return {
            "status": "ok",
            "mvsep_api_token": mv_key,
            "gemini_api_key": gm_key,
            "has_mvsep_token": bool(mv_key),
            "has_gemini_key": bool(gm_key),
        }

    def _patched_save_credentials(self, mvsep_token="", gemini_key=""):
        print("[RUN]HMSWebDawBridge.save_credentials() invoked...")
        try:
            # Support being called with a single dict/JSON object from JS
            if isinstance(mvsep_token, dict):
                payload = mvsep_token
                mvsep_token = (
                    payload.get("mvsep_api_token")
                    or payload.get("mvsep_token")
                    or payload.get("mvsepKey")
                    or ""
                )
                gemini_key = (
                    payload.get("gemini_api_key")
                    or payload.get("gemini_key")
                    or payload.get("geminiKey")
                    or ""
                )

            updates = {}
            if mvsep_token is not None and str(mvsep_token).strip():
                updates["mvsep_api_token"] = str(mvsep_token).strip()
            if gemini_key is not None and str(gemini_key).strip():
                updates["gemini_api_key"] = str(gemini_key).strip()

            cfg_path = Path.home() / ".mvsep_hms_config.json"
            existing = {}
            if cfg_path.is_file():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing.update(updates)

            tmp_path = cfg_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            os.replace(tmp_path, cfg_path)

            print(f"[SUCCESS] Saved keys to {cfg_path} (Keys updated: {list(updates.keys())})")
            return {
                "status": "ok",
                "config_path": str(cfg_path),
                "mvsep_api_token": existing.get("mvsep_api_token", ""),
                "gemini_api_key": existing.get("gemini_api_key", ""),
                "has_mvsep_token": bool(existing.get("mvsep_api_token")),
                "has_gemini_key": bool(existing.get("gemini_api_key")),
            }
        except Exception:
            err = traceback.format_exc()
            print(f"[ERROR] Failed saving keys in HMSWebDawBridge:\n{err}")
            return {"status": "error", "message": err}

    HMSWebDawBridge.get_status = _patched_get_status
    HMSWebDawBridge.load_credentials = _load_credentials
    HMSWebDawBridge.save_credentials = _patched_save_credentials
    HMSWebDawBridge.save_api_keys = _patched_save_credentials


_patch_bridge_key_methods()




# === WEB_DAW_MVSEP_CLOUD_SPLITTER_PATCH ===
import shutil
import subprocess
import threading
import time
import zipfile
from urllib.parse import unquote, urlparse
import requests

MVSEP_API_CREATE_URL = "https://mvsep.com/api/separation/create"
MVSEP_API_GET_URL = "https://mvsep.com/api/separation/get"

MVSEP_MODELS = {
    "BS Roformer SW (6 Stems: Vocals, Bass, Drums, Guitar, Piano, Other)": 63,
    "BS Roformer (Vocals / Instrumental)": 40,
    "Demucs4 HT (Vocals, Drums, Bass, Other)": 20,
    "DrumSep (4-6 Drum Stems)": 37,
    "Ensemble Vocals/Instrum (SOTA Quality)": 26,
    "Ensemble 5 Stems (Vocals, Bass, Drums, Other)": 28,
    "MDX23C (Vocals / Instrumental)": 25,
    "SCNet XL (Vocals / Instrumental)": 46,
    "Reverb Removal (noreverb)": 22,
    "DeNoise (aufr33 & gabox)": 47,
}

MVSEP_FORMATS = {
    "WAV (Uncompressed, 16-bit)": 1,
    "FLAC (Lossless, 16-bit)": 2,
    "FLAC (Lossless, 24-bit)": 5,
    "MP3 (320 kbps)": 0,
    "WAV (Uncompressed, 32-bit)": 4,
}


def _patch_bridge_with_mvsep_splitter():
    HMSWebDawBridge._mvsep_lock = threading.Lock()
    HMSWebDawBridge._mvsep_cancel = threading.Event()
    HMSWebDawBridge._mvsep_state = {
        "running": False,
        "status": "idle",
        "logs": ["[INFO] MVSep Cloud Splitter ready."],
        "song_workspace_dir": "",
        "last_error": "",
    }

    def _append_mvsep_log(self, msg):
        print(msg)
        with self._mvsep_lock:
            self._mvsep_state["logs"].append(str(msg))
            if len(self._mvsep_state["logs"]) > 250:
                self._mvsep_state["logs"] = self._mvsep_state["logs"][-250:]

    def browse_song_file(self):
        print("[RUN] Opening audio file dialog for MVSep Stem Splitter...")
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Select Audio File to Split with MVSep",
                filetypes=[
                    ("Audio Files", "*.wav *.flac *.mp3 *.m4a"),
                    ("WAV Audio Files", "*.wav"),
                    ("All Files", "*.*"),
                ],
            )
            root.destroy()
            if selected:
                print(f"[SUCCESS] Selected song file: {selected}")
                return {"status": "ok", "file_path": selected}
            return {"status": "cancelled", "file_path": ""}
        except Exception:
            err = traceback.format_exc()
            print(f"[ERROR] browse_song_file failed:\n{err}")
            return {"status": "error", "message": err}

    def get_mvsep_job_status(self):
        with self._mvsep_lock:
            return {
                "status": "ok",
                "running": self._mvsep_state["running"],
                "job_status": self._mvsep_state["status"],
                "logs": list(self._mvsep_state["logs"]),
                "song_workspace_dir": self._mvsep_state["song_workspace_dir"],
                "last_error": self._mvsep_state["last_error"],
            }

    def cancel_mvsep_separation(self):
        self._mvsep_cancel.set()
        self._append_mvsep_log("[INFO] Cancellation requested by user.")
        return {"status": "ok"}

    def launch_classic_mvsep_gui(self):
        candidates = [
            r"C:\github\projects\mvsep-api-gui\mvsep_gui.py",
            r"H:\suno projects\mvsep_gui.py",
            os.path.join(HMS_REPO_DIR, "mvsep_gui.py"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                subprocess.Popen([sys.executable, path], cwd=os.path.dirname(path))
                self._append_mvsep_log(f"[SUCCESS] Launched classic mvsep_gui.py: {path}")
                return {"status": "ok", "launched": path}
        return {"status": "error", "message": "mvsep_gui.py not found in standard paths."}

    def _stage_downloaded_stems(self, input_audio_path, downloaded_paths):
        parent_dir = os.path.dirname(os.path.abspath(input_audio_path))
        raw_base = os.path.splitext(os.path.basename(input_audio_path))[0]
        clean_song_name = "".join(
            "_" if c in '<>:"/\\|?* ' else c for c in raw_base
        ).strip("_") or "MVSep_Song"

        song_workspace_dir = os.path.join(parent_dir, f"{clean_song_name}_Stems")
        os.makedirs(song_workspace_dir, exist_ok=True)
        self._append_mvsep_log(f"[INFO] Staging stems into: {song_workspace_dir}")

        staged_count = 0
        for item_path in downloaded_paths:
            if not item_path or not os.path.isfile(item_path):
                continue
            ext = os.path.splitext(item_path)[1].lower()
            if ext == ".zip":
                self._append_mvsep_log(f"[RUN] Extracting ZIP archive: {os.path.basename(item_path)}")
                with zipfile.ZipFile(item_path, "r") as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        safe_name = os.path.basename(member.filename)
                        if not safe_name:
                            continue
                        dest_member = os.path.join(song_workspace_dir, safe_name)
                        with zf.open(member) as src_f, open(dest_member, "wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)
                        staged_count += 1
                        self._append_mvsep_log(f"[INFO] Extracted stem -> {safe_name}")
            else:
                dest_file = os.path.join(song_workspace_dir, os.path.basename(item_path))
                if os.path.abspath(item_path) != os.path.abspath(dest_file):
                    shutil.move(item_path, dest_file)
                staged_count += 1
                self._append_mvsep_log(f"[INFO] Staged stem -> {os.path.basename(dest_file)}")

        return song_workspace_dir if staged_count > 0 else None

    def start_mvsep_separation(self, payload=None):
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = payload or {}

        with self._mvsep_lock:
            if self._mvsep_state["running"]:
                return {"status": "error", "message": "An MVSep separation job is already running."}

        file_path = str(payload.get("file_path") or "").strip()
        api_token = str(payload.get("api_token") or "").strip()
        if not api_token:
            cfg_path = Path.home() / ".mvsep_hms_config.json"
            if cfg_path.is_file():
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        api_token = str(cfg.get("mvsep_api_token") or cfg.get("mvsep_token") or "").strip()
                except Exception:
                    pass

        if not api_token:
            return {"status": "error", "message": "Missing MVSep API Token. Paste your token and click Save Keys first."}
        if not file_path or not os.path.isfile(file_path):
            return {"status": "error", "message": f"Audio file not found: {file_path}"}

        sep_type = int(payload.get("sep_type", 63))
        output_format = int(payload.get("output_format", 1))
        auto_clean = bool(payload.get("auto_clean", True))

        self._mvsep_cancel.clear()
        with self._mvsep_lock:
            self._mvsep_state["running"] = True
            self._mvsep_state["status"] = "uploading"
            self._mvsep_state["song_workspace_dir"] = ""
            self._mvsep_state["last_error"] = ""
            self._mvsep_state["logs"] = [
                f"[RUN] Starting MVSep Job for: {os.path.basename(file_path)}",
                f"[INFO] sep_type={sep_type}, output_format={output_format}, auto_clean={auto_clean}",
            ]

        def _worker():
            try:
                size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
                self._append_mvsep_log(f"[RUN] Uploading {os.path.basename(file_path)} ({size_mb} MB) to MVSep...")

                res_data = None
                for attempt in range(1, 4):
                    if self._mvsep_cancel.is_set():
                        self._append_mvsep_log("[INFO] Upload cancelled.")
                        return
                    try:
                        self._append_mvsep_log(f"[INFO] Upload attempt {attempt}/3...")
                        with open(file_path, "rb") as audio_f:
                            files = {"audiofile": (os.path.basename(file_path), audio_f, "audio/wav")}
                            data = {
                                "api_token": api_token,
                                "sep_type": sep_type,
                                "output_format": output_format,
                            }
                            resp = requests.post(MVSEP_API_CREATE_URL, data=data, files=files, timeout=(20, 600))
                        if resp.status_code == 200:
                            res_data = resp.json()
                            break
                        else:
                            self._append_mvsep_log(f"[ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
                    except Exception as up_ex:
                        self._append_mvsep_log(f"[ERROR] Upload attempt {attempt} error: {up_ex}")
                    time.sleep(4)

                if not res_data or not res_data.get("success"):
                    msg = (res_data or {}).get("data", {}).get("message", "Upload failed.")
                    self._append_mvsep_log(f"[ERROR] MVSep creation failed: {msg}")
                    with self._mvsep_lock:
                        self._mvsep_state["status"] = "error"
                        self._mvsep_state["last_error"] = msg
                    return

                job_hash = res_data["data"]["hash"]
                self._append_mvsep_log(f"[SUCCESS] MVSep Job Created! Hash: {job_hash}")
                with self._mvsep_lock:
                    self._mvsep_state["status"] = "polling"

                while not self._mvsep_cancel.is_set():
                    time.sleep(10)
                    if self._mvsep_cancel.is_set():
                        break
                    poll_resp = requests.get(MVSEP_API_GET_URL, params={"hash": job_hash}, timeout=(15, 120))
                    if poll_resp.status_code != 200:
                        self._append_mvsep_log(f"[INFO] Poll HTTP {poll_resp.status_code}, retrying...")
                        continue

                    poll_json = poll_resp.json()
                    status = poll_json.get("status", "unknown")
                    data_block = poll_json.get("data", {})

                    if status == "waiting":
                        q_order = data_block.get("current_order", "?")
                        q_count = data_block.get("queue_count", "?")
                        self._append_mvsep_log(f"[INFO] Queue Waiting: Position {q_order} / {q_count}")
                    elif status in ("processing", "distributing", "merging"):
                        self._append_mvsep_log(f"[RUN] GPU Status: {status.upper()}...")
                    elif status == "done":
                        self._append_mvsep_log("[SUCCESS] Separation complete! Downloading stems...")
                        with self._mvsep_lock:
                            self._mvsep_state["status"] = "downloading"

                        download_dir = os.path.dirname(os.path.abspath(file_path))
                        files_list = data_block.get("files", [])
                        zip_link = data_block.get("link")
                        saved_paths = []

                        if isinstance(files_list, list) and files_list:
                            for idx, item in enumerate(files_list, 1):
                                dl_url = item.get("url") or item.get("link")
                                fname = item.get("name") or unquote(urlparse(dl_url).path.rsplit("/", 1)[-1])
                                safe_fname = "".join("_" if c in '<>:"/\\|?*' else c for c in os.path.basename(fname))
                                target_path = os.path.join(download_dir, safe_fname)
                                self._append_mvsep_log(f"[RUN] Downloading ({idx}/{len(files_list)}): {safe_fname}")
                                with requests.get(dl_url, stream=True, timeout=(15, 300)) as r:
                                    r.raise_for_status()
                                    with open(target_path, "wb") as out_f:
                                        for chunk in r.iter_content(chunk_size=32768):
                                            if chunk:
                                                out_f.write(chunk)
                                saved_paths.append(target_path)
                        elif zip_link:
                            fname = unquote(urlparse(zip_link).path.rsplit("/", 1)[-1]) or "stems.zip"
                            target_path = os.path.join(download_dir, fname)
                            self._append_mvsep_log(f"[RUN] Downloading ZIP: {fname}")
                            with requests.get(zip_link, stream=True, timeout=(15, 300)) as r:
                                r.raise_for_status()
                                with open(target_path, "wb") as out_f:
                                    for chunk in r.iter_content(chunk_size=32768):
                                        if chunk:
                                            out_f.write(chunk)
                            saved_paths.append(target_path)

                        workspace_dir = self._stage_downloaded_stems(file_path, saved_paths)
                        if workspace_dir:
                            with self._mvsep_lock:
                                self._mvsep_state["song_workspace_dir"] = workspace_dir
                            self._append_mvsep_log(f"[SUCCESS] Stems staged in: {workspace_dir}")

                            if auto_clean and hasattr(self, "run_clean"):
                                self._append_mvsep_log("[RUN] Auto-Clean enabled -> Running HMS VST3 Clean & 24-Bit Master...")
                                clean_res = self.run_clean({"source_dir": workspace_dir, "mode": "live"})
                                self._append_mvsep_log(f"[SUCCESS] Auto-Clean Result: {clean_res.get('status', 'done')}")

                        with self._mvsep_lock:
                            self._mvsep_state["status"] = "done"
                        return
                    else:
                        msg = data_block.get("message", f"Unexpected status: {status}")
                        self._append_mvsep_log(f"[ERROR] MVSep job failed: {msg}")
                        with self._mvsep_lock:
                            self._mvsep_state["status"] = "error"
                            self._mvsep_state["last_error"] = msg
                        return

            except Exception:
                err = traceback.format_exc()
                self._append_mvsep_log(f"[ERROR] MVSep worker exception:\n{err}")
                with self._mvsep_lock:
                    self._mvsep_state["status"] = "error"
                    self._mvsep_state["last_error"] = err
            finally:
                with self._mvsep_lock:
                    self._mvsep_state["running"] = False

        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "ok", "message": "MVSep separation job started."}

    HMSWebDawBridge._append_mvsep_log = _append_mvsep_log
    HMSWebDawBridge._stage_downloaded_stems = _stage_downloaded_stems
    HMSWebDawBridge.browse_song_file = browse_song_file
    HMSWebDawBridge.get_mvsep_job_status = get_mvsep_job_status
    HMSWebDawBridge.cancel_mvsep_separation = cancel_mvsep_separation
    HMSWebDawBridge.launch_classic_mvsep_gui = launch_classic_mvsep_gui
    HMSWebDawBridge.start_mvsep_separation = start_mvsep_separation


_patch_bridge_with_mvsep_splitter()


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