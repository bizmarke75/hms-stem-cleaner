# Save as: C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py
# Verify Bridge : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py --test-bridge
# Verify Server : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py --test-server
# Launch Studio : python.exe C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import requests

# Resolve frozen (--onedir) vs script runtime paths & configure %LOCALAPPDATA% WebView2 cache
try:
    from hms_runtime_paths import resolve_hms_runtime_paths as _resolve_hms_paths
    _HMS_PATHS = _resolve_hms_paths() or {}
except Exception:
    _HMS_PATHS = {}

HMS_REPO_DIR = _HMS_PATHS.get("bundle_dir") or (
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
if os.path.isdir(HMS_REPO_DIR) and HMS_REPO_DIR not in sys.path:
    sys.path.insert(0, HMS_REPO_DIR)

V14_HTML_NAME = "337_west_hms_unified_studio_web_daw_v1.4.html"
LEGACY_HTML_NAME = "hms_web_daw.html"


# ==============================================================================
# COMPONENT 1: FROZEN-SAFE HTML UI ASSET RESOLVER
# ==============================================================================
def resolve_v1_4_ui_html(override_path=None):
    """Locates the v1.4 Web-DAW HTML across _MEIPASS, install_dir, repo, and Downloads."""
    if override_path and os.path.isfile(override_path):
        return os.path.normpath(override_path)

    search_dirs = [
        _HMS_PATHS.get("bundle_dir"),
        _HMS_PATHS.get("install_dir"),
        HMS_REPO_DIR,
    ]
    for base in search_dirs:
        if not base:
            continue
        for fname in (V14_HTML_NAME, LEGACY_HTML_NAME):
            cand = os.path.join(base, fname)
            if os.path.isfile(cand):
                print(f"[SUCCESS] Resolved Web-DAW UI file: {cand}")
                return cand

    # Auto-recover from Downloads when running unfrozen
    for fname in (V14_HTML_NAME, LEGACY_HTML_NAME):
        dl = Path.home() / "Downloads" / fname
        if dl.is_file():
            dst = os.path.join(HMS_REPO_DIR, fname)
            shutil.copy2(str(dl), dst)
            print(f"[SUCCESS] Copied {fname} from Downloads -> {dst}")
            return dst

    return os.path.join(HMS_REPO_DIR, V14_HTML_NAME)


# ==============================================================================
# COMPONENT 2: SELF-CONTAINED PYTHON <-> JS BRIDGE (window.pywebview.api)
# ==============================================================================
class HMSWebDawBridge:
    """
    Self-contained v1.4 bridge connecting the Web-DAW UI to HMS Stem Cleaner,
    JSON Mix Presets, Gemini Tuner, and Free-Tier Safe MVSep Multi-Pass Queue.
    """

    def __init__(self, repo_dir=HMS_REPO_DIR):
        self.repo_dir = os.path.normpath(repo_dir)
        self._window = None
        self.hms_app = None
        self.json_mgr = None
        self.gemini_tuner = None
        self.ai_bridge = None
        self.mp_mod = None
        self._load_backend_modules()

    def set_window(self, window_obj):
        self._window = window_obj

    def _load_backend_modules(self):
        print("=" * 75)
        print(f"[RUN] Initializing Self-Contained v1.4 HMSWebDawBridge in: {self.repo_dir}")
        print("=" * 75)

        for attr, mod_name, required in (
            ("hms_app", "hms_stem_cleaner_app", True),
            ("json_mgr", "hms_mix_json_manager", False),
            ("gemini_tuner", "hms_gemini_tuner", False),
            ("ai_bridge", "hms_ai_api_bridge", False),
            ("mp_mod", "hms_mvsep_multipass", False),
        ):
            try:
                setattr(self, attr, __import__(mod_name))
                print(f"[SUCCESS] Loaded module: {mod_name}.py")
            except Exception:
                level = "[ERROR]" if required else "[INFO]"
                print(f"{level} Module {mod_name}.py not loaded.")
                if required:
                    print(traceback.format_exc())

    def _read_config(self):
        cfg_path = Path.home() / ".mvsep_hms_config.json"
        if cfg_path.is_file():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_status(self):
        """Returns backend engine health, VST3 availability, and saved API key flags."""
        try:
            creds = self._read_config()
            vst3_map = {}
            if self.hms_app and hasattr(self.hms_app, "resolve_vst3_binary_path"):
                vst3_map = self.hms_app.resolve_vst3_binary_path()
            mv_tok = str(creds.get("mvsep_api_token") or creds.get("mvsep_token") or "").strip()
            gm_key = str(creds.get("gemini_api_key") or "").strip()
            return {
                "status": "ok",
                "engine_loaded": self.hms_app is not None,
                "multipass_loaded": self.mp_mod is not None,
                "vst3_status": {k: bool(v) for k, v in vst3_map.items()},
                "has_mvsep_token": bool(mv_tok),
                "has_gemini_key": bool(gm_key),
                "mvsep_api_token": mv_tok,
                "gemini_api_key": gm_key,
            }
        except Exception:
            print(traceback.format_exc())
            return {"status": "error", "message": traceback.format_exc()}

    def save_credentials(self, mvsep_token="", gemini_key=""):
        """Saves MVSep & Gemini keys to ~/.mvsep_hms_config.json (accepts dict or positional args)."""
        try:
            if isinstance(mvsep_token, dict):
                payload = mvsep_token
                mvsep_token = payload.get("mvsep_api_token") or payload.get("mvsep_token") or ""
                gemini_key = payload.get("gemini_api_key") or ""
            cfg_path = Path.home() / ".mvsep_hms_config.json"
            existing = self._read_config()
            if str(mvsep_token).strip():
                existing["mvsep_api_token"] = str(mvsep_token).strip()
                existing["mvsep_token"] = str(mvsep_token).strip()
            if str(gemini_key).strip():
                existing["gemini_api_key"] = str(gemini_key).strip()
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            print(f"[SUCCESS] Saved credentials -> {cfg_path}")
            return {"status": "ok"}
        except Exception:
            return {"status": "error", "message": traceback.format_exc()}

    def browse_folder(self, title="Select Song Stem Folder"):
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(title=title)
            root.destroy()
            if not selected:
                return {"status": "cancelled", "path": ""}
            norm_dir = os.path.normpath(selected)
            saved_mix = None
            if self.json_mgr and hasattr(self.json_mgr, "load_song_mix_json"):
                saved_mix = self.json_mgr.load_song_mix_json(norm_dir)
            return {"status": "ok", "path": norm_dir, "saved_mix": saved_mix}
        except Exception:
            return {"status": "error", "path": "", "message": traceback.format_exc()}

    def browse_song_file(self):
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Select Audio File to Split with MVSep",
                filetypes=[("Audio Files", "*.wav *.flac *.mp3 *.m4a"), ("All Files", "*.*")],
            )
            root.destroy()
            if not selected:
                return {"status": "cancelled", "file_path": ""}
            return {"status": "ok", "file_path": os.path.normpath(selected)}
        except Exception:
            return {"status": "error", "file_path": "", "message": traceback.format_exc()}

    def run_clean(self, payload):
        """Executes autotune, dry_run, live, glue_only, rollback, or gemini_tune."""
        if not self.hms_app:
            return {"status": "error", "message": "hms_stem_cleaner_app.py is not loaded."}
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            mode = payload.get("mode", "dry_run")
            song_dir = str(payload.get("song_dir") or payload.get("source_dir") or "").strip()
            dest_root = str(payload.get("dest_root") or "").strip() or None
            vocal_gate_db = float(payload.get("vocal_gate_db", -33.0))
            bus_weights = payload.get("bus_weights", {"Vocals": 1.08, "Rhythm": 1.04, "Music": 0.90})
            vst_overrides = payload.get("vst_overrides", {})

            if mode == "autotune":
                return {"status": "ok", "mode": "autotune", "profile": self.hms_app.analyze_and_autotune_song(song_dir)}
            if mode in ("dry_run", "live"):
                summary = self.hms_app.execute_stem_cleanup(
                    source_dir=song_dir, dest_root=dest_root, dry_run=(mode == "dry_run"),
                    move_source_files=bool(payload.get("move_files", False)), render_master=True,
                    vocal_gate_db=vocal_gate_db, bus_weights=bus_weights, vst_overrides=vst_overrides,
                )
                return {"status": "ok", "mode": mode, "summary": summary}
            if mode == "glue_only":
                return {"status": "ok", "mode": "glue_only", "result": self.hms_app.render_master_mixdown(dest_song_dir=song_dir, bus_weights=bus_weights)}
            if mode == "rollback":
                song_name = os.path.basename(os.path.normpath(song_dir))
                ok = self.hms_app.restore_song_checkpoint(song_name)
                return {"status": "ok" if ok else "error", "mode": "rollback", "song_name": song_name}
            if mode == "gemini_tune" and self.gemini_tuner:
                res = self.gemini_tuner.run_on_the_fly_gemini_mix_loop(target_path=song_dir, dest_root=dest_root)
                return {"status": "ok", "mode": "gemini_tune", "result": res}
            return {"status": "error", "message": f"Unsupported mode: {mode}"}
        except Exception:
            err = traceback.format_exc()
            print(f"[ERROR] run_clean failed:\n{err}")
            return {"status": "error", "message": err}

    # ---- Free-Tier Safe Sequential Multi-Pass & Single-Pass MVSep Endpoints ----
    def get_mvsep_multipass_recipe(self):
        if not self.mp_mod:
            return {"status": "error", "message": "hms_mvsep_multipass.py not loaded."}
        return {
            "status": "ok",
            "recipe": self.mp_mod.HMS_FREE_MULTIPASS_RECIPE,
            "blocked_sep_types": sorted(self.mp_mod.PREMIUM_BLOCKED_SEP_TYPES),
            "blocked_formats": sorted(self.mp_mod.PREMIUM_BLOCKED_FORMATS),
        }

    def start_mvsep_multipass(self, payload=None):
        if not self.mp_mod:
            return {"status": "error", "message": "hms_mvsep_multipass.py not loaded."}
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            payload = payload or {}
            creds = self._read_config()
            tok = str(payload.get("api_token") or creds.get("mvsep_api_token") or creds.get("mvsep_token") or "").strip()
            return self.mp_mod.SHARED_MULTIPASS_RUNNER.start_multipass(
                api_token=tok,
                song_file_path=str(payload.get("file_path") or "").strip(),
                pass_ids=payload.get("pass_ids") or ["pass1_vocals", "pass2_music", "pass3_rhythm"],
                output_format=int(payload.get("output_format", 1)),
                free_tier_safe=bool(payload.get("free_tier_safe", True)),
                auto_clean=bool(payload.get("auto_clean", True)),
                mix_style=str(payload.get("mix_style") or "auto"),
            )
        except Exception:
            return {"status": "error", "message": traceback.format_exc()}

    def get_mvsep_multipass_status(self):
        if not self.mp_mod:
            return {"status": "error", "running": False, "logs": []}
        st = self.mp_mod.SHARED_MULTIPASS_RUNNER.get_status()
        st["status"] = "ok"
        return st

    def cancel_mvsep_multipass(self):
        if not self.mp_mod:
            return {"status": "error", "message": "hms_mvsep_multipass.py not loaded."}
        return self.mp_mod.SHARED_MULTIPASS_RUNNER.cancel()

    def start_mvsep_separation(self, payload=None):
        """Routes single-pass requests through the same Free-Tier validator & 1-job lock."""
        if not self.mp_mod:
            return {"status": "error", "message": "hms_mvsep_multipass.py not loaded."}
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = payload or {}
        chk = self.mp_mod.validate_mvsep_free_tier_request(
            sep_type=payload.get("sep_type", 63),
            output_format=payload.get("output_format", 1),
            file_path=str(payload.get("file_path") or "").strip() or None,
            free_tier_safe=bool(payload.get("free_tier_safe", True)),
        )
        if not chk["ok"]:
            return {"status": "error", "message": chk["reason"]}
        return self.start_mvsep_multipass({
            "file_path": payload.get("file_path", ""),
            "api_token": payload.get("api_token", ""),
            "pass_ids": ["pass2_music"],
            "output_format": int(payload.get("output_format", 1)),
            "free_tier_safe": bool(payload.get("free_tier_safe", True)),
            "auto_clean": bool(payload.get("auto_clean", True)),
        })

    def get_mvsep_job_status(self):
        return self.get_mvsep_multipass_status()

    def cancel_mvsep_separation(self):
        return self.cancel_mvsep_multipass()

    def launch_classic_mvsep_gui(self):
        for p in (os.path.join(self.repo_dir, "mvsep_gui.py"), r"C:\github\projects\mvsep-api-gui\mvsep_gui.py"):
            if os.path.isfile(p):
                subprocess.Popen([sys.executable, p], cwd=os.path.dirname(p))
                return {"status": "ok", "launched": p}
        return {"status": "error", "message": "mvsep_gui.py not found."}


# ==============================================================================
# COMPONENT 3: LOCAL REST SERVER (:8765) & DESKTOP WINDOW LAUNCHER
# ==============================================================================
def ensure_local_rest_server_running(host="127.0.0.1", port=8765):
    health_url = f"http://{host}:{port}/health"
    try:
        if requests.get(health_url, timeout=1.5).status_code == 200:
            print(f"[SUCCESS] Local HMS REST API already online at {health_url}")
            return True, None
    except Exception:
        pass
    try:
        import hms_ai_api_bridge as ai_bridge
        srv, _ = ai_bridge.start_local_hms_api_server(host=host, port=port)
        if srv:
            time.sleep(0.25)
            if requests.get(health_url, timeout=3.0).status_code == 200:
                print(f"[SUCCESS] Started Local REST API on {health_url}")
                return True, srv
    except Exception:
        print("[ERROR] Local REST API startup warning:")
        print(traceback.format_exc())
    return False, None


def launch_hms_web_daw_desktop(html_path=None, width=1520, height=920):
    ensure_local_rest_server_running(port=8765)
    bridge = HMSWebDawBridge()
    resolved_html = resolve_v1_4_ui_html(html_path)
    if not os.path.isfile(resolved_html):
        print(f"[ERROR] Missing Web-DAW UI HTML: {resolved_html}")
        return False
    try:
        import webview
        window = webview.create_window(
            title="337 West Productions — HMS Unified Studio Suite v1.4 (Web-DAW)",
            url=resolved_html,
            js_api=bridge,
            width=width,
            height=height,
            min_size=(1180, 740),
            background_color="#07090e",
        )
        bridge.set_window(window)
        webview.start(debug=False)
        return True
    except ImportError:
        webbrowser.open(Path(resolved_html).as_uri())
        return True
    except Exception:
        print("[ERROR] Failed launching Web-DAW desktop window:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# ISOLATED VERIFICATION DRIVERS (--test-bridge & --test-server)
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS Unified Studio Suite v1.4 Desktop Launcher")
    parser.add_argument("--test-bridge", action="store_true", help="Verify HMSWebDawBridge in isolation")
    parser.add_argument("--test-server", action="store_true", help="Verify Local REST API (:8765)")
    parser.add_argument("--html", type=str, default=None, help="Optional explicit HTML path")
    args = parser.parse_args()

    if args.test_bridge:
        b = HMSWebDawBridge()
        st = b.get_status()
        assert st.get("status") == "ok" and st.get("engine_loaded") is True
        blocked = b.start_mvsep_separation({"sep_type": 26, "output_format": 1, "free_tier_safe": True})
        assert blocked.get("status") == "error" and "Free-Tier Safe Mode" in blocked.get("message", "")
        print("[SUCCESS] v1.4 SELF-CONTAINED BRIDGE & FREE-TIER GUARDRAILS PASSED 100%!")
    elif args.test_server:
        ok, srv = ensure_local_rest_server_running(port=8765)
        assert ok is True
        if srv:
            srv.shutdown()
        print("[SUCCESS] LOCAL REST SERVER (:8765) VERIFICATION PASSED 100%!")
    else:
        launch_hms_web_daw_desktop(html_path=args.html)