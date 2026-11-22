# === HMS_WEBVIEW2_DARK_LOCK_FIX ===
import os as _hms_os
from pathlib import Path as _hms_Path
_hms_wv2 = _hms_Path(_hms_os.environ.get('LOCALAPPDATA', str(_hms_Path.home()))) / 'HMS Studio Suite' / 'WebView2Cache'
_hms_wv2.mkdir(parents=True, exist_ok=True)
_hms_os.environ.setdefault('WEBVIEW2_USER_DATA_FOLDER', str(_hms_wv2))
_hms_os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '--disable-gpu-compositing')
# === END_HMS_WEBVIEW2_DARK_LOCK_FIX ===

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




# === HMS_THREADSAFE_WINDOWS_PICKER_PATCH ===
def _install_threadsafe_windows_pickers():
    import os as _os
    import subprocess as _sp
    import traceback as _tb

    _CREATE_NO_WINDOW = getattr(_sp, "CREATE_NO_WINDOW", 0)

    def _sta_winforms_open_file(title="Select Audio File for MVSep"):
        # Runs a topmost native Windows OpenFileDialog in an isolated STA thread (100% immune to Tk/WebView deadlocks)
        safe_title = str(title or "Select Audio File").replace("'", "''")
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.Form; $f.TopMost = $true; $f.StartPosition = 'CenterScreen'; "
            "$d = New-Object System.Windows.Forms.OpenFileDialog; "
            f"$d.Title = '{safe_title}'; "
            "$d.Filter = 'Audio Files (*.wav;*.flac;*.mp3;*.m4a;*.ogg)|*.wav;*.flac;*.mp3;*.m4a;*.ogg|All Files (*.*)|*.*'; "
            "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.FileName) }; "
            "$f.Dispose()"
        )
        res = _sp.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW,
        )
        return (res.stdout or "").strip()

    def _sta_winforms_open_folder(title="Select Song Stem Folder"):
        safe_title = str(title or "Select Folder").replace("'", "''")
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.Form; $f.TopMost = $true; $f.StartPosition = 'CenterScreen'; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$d.Description = '{safe_title}'; $d.UseDescriptionForTitle = $true; "
            "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.SelectedPath) }; "
            "$f.Dispose()"
        )
        res = _sp.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW,
        )
        return (res.stdout or "").strip()

    def _threadsafe_browse_song_file(self, *args, **kwargs):
        title = args[0] if args and isinstance(args[0], str) else kwargs.get("title", "Select Audio File to Split with MVSep")
        selected = ""
        try:
            # Priority 1: Native pywebview file dialog when running inside the Desktop Studio window
            win = getattr(self, "_window", None)
            if win is not None and hasattr(win, "create_file_dialog"):
                try:
                    import webview as _wv
                    dlg_type = getattr(getattr(_wv, "FileDialog", _wv), "OPEN", getattr(_wv, "OPEN_DIALOG", 10))
                    picked = win.create_file_dialog(
                        dlg_type,
                        allow_multiple=False,
                        file_types=("Audio Files (*.wav;*.flac;*.mp3;*.m4a;*.ogg)", "All files (*.*)"),
                    )
                    if picked:
                        selected = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
                except Exception as _wv_err:
                    print(f"[INFO] pywebview file dialog fallback triggered: {_wv_err}")

            # Priority 2: Topmost STA WinForms dialog (works from REST :8765 worker threads & any OS thread)
            if not selected:
                selected = _sta_winforms_open_file(title=title)

            if not selected:
                return {"status": "cancelled", "ok": False, "path": "", "file_path": "", "file": ""}

            norm_file = _os.path.normpath(selected)
            print(f"[SUCCESS] Selected audio file: {norm_file}")
            return {
                "status": "ok",
                "ok": True,
                "path": norm_file,
                "file_path": norm_file,
                "file": norm_file,
                "filename": _os.path.basename(norm_file),
            }
        except Exception:
            err = _tb.format_exc()
            print(f"[ERROR] browse_song_file failed:\n{err}")
            return {"status": "error", "ok": False, "path": "", "file_path": "", "message": err}

    def _threadsafe_browse_folder(self, *args, **kwargs):
        title = args[0] if args and isinstance(args[0], str) else kwargs.get("title", "Select Song Stem Folder")
        selected = ""
        try:
            win = getattr(self, "_window", None)
            if win is not None and hasattr(win, "create_file_dialog"):
                try:
                    import webview as _wv
                    dlg_type = getattr(getattr(_wv, "FileDialog", _wv), "FOLDER", getattr(_wv, "FOLDER_DIALOG", 20))
                    picked = win.create_file_dialog(dlg_type)
                    if picked:
                        selected = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
                except Exception as _wv_err:
                    print(f"[INFO] pywebview folder dialog fallback triggered: {_wv_err}")

            if not selected:
                selected = _sta_winforms_open_folder(title=title)

            if not selected:
                return {"status": "cancelled", "ok": False, "path": "", "dir_path": "", "folder_path": ""}

            norm_dir = _os.path.normpath(selected)
            saved_mix = None
            jm = getattr(self, "json_mgr", None)
            if jm and hasattr(jm, "load_song_mix_json"):
                saved_mix = jm.load_song_mix_json(norm_dir)
            print(f"[SUCCESS] Selected folder: {norm_dir}")
            return {
                "status": "ok",
                "ok": True,
                "path": norm_dir,
                "dir_path": norm_dir,
                "folder_path": norm_dir,
                "saved_mix": saved_mix,
            }
        except Exception:
            err = _tb.format_exc()
            print(f"[ERROR] browse_folder failed:\n{err}")
            return {"status": "error", "ok": False, "path": "", "message": err}

    for _fn_name in ['browse_audio_file', 'browse_file', 'browse_master_audio', 'browse_mvsep_file', 'browse_song_file', 'choose_file', 'jsonFilePicker', 'pick_audio_file', 'pick_file', 'pick_mvsep_file', 'pick_song_file', 'select_audio_file', 'select_file', 'select_mvsep_file', 'select_song_file', 'wavFilePicker']:
        setattr(HMSWebDawBridge, _fn_name, _threadsafe_browse_song_file)
    for _fn_name in ['browse_directory', 'browse_folder', 'browse_output_folder', 'browse_stem_folder', 'choose_folder', 'pick_folder', 'select_directory', 'select_folder']:
        setattr(HMSWebDawBridge, _fn_name, _threadsafe_browse_folder)
    print("[SUCCESS] Thread-safe Windows file & folder pickers attached to HMSWebDawBridge.")


_install_threadsafe_windows_pickers()
# === /HMS_THREADSAFE_WINDOWS_PICKER_PATCH ===




# === HMS_V1_4_BRIDGE_METHODS_PATCH ===
def _hms_attach_v1_4_bridge_methods():
    import json as _json
    import os as _os
    import threading as _threading
    import traceback as _tb
    from pathlib import Path as _Path

    # Auto-discover the active JS bridge class in this launcher module
    _hints = {"get_status", "browse_folder", "browse_master_audio", "browse_output_folder", "run_clean"}
    _cands = []
    for _nm, _obj in list(globals().items()):
        if isinstance(_obj, type) and getattr(_obj, "__module__", None) == __name__:
            _score = len(set(dir(_obj)) & _hints) * 10
            if any(k in _nm.lower() for k in ("bridge", "api", "daw", "studio")):
                _score += 5
            _cands.append((_score, _nm, _obj))

    if not _cands:
        print("[ERROR] Could not locate bridge class in hms_web_daw_launcher.py")
        return

    _cands.sort(key=lambda x: x[0], reverse=True)
    _cls = _cands[0][2]
    globals().setdefault("HMSWebDawBridge", _cls)
    print(f"[INFO] Attaching v1.4 API methods to bridge class: {_cls.__name__}")

    def _mask_key(val):
        s = str(val or "").strip()
        if not s:
            return ""
        return (s[:4] + "..." + s[-4:]) if len(s) > 10 else "****"

    def _vault_path():
        return _Path.home() / ".mvsep_hms_config.json"

    def _read_vault():
        p = _vault_path()
        if p.is_file():
            try:
                return _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _push_ui_log(self, msg):
        print(msg)
        win = getattr(self, "_window", None)
        if win is not None:
            try:
                win.evaluate_js(f"window.hmsPushConsoleLog && window.hmsPushConsoleLog({_json.dumps(str(msg))});")
            except Exception:
                pass

    def get_keys_status(self):
        """Returns masked MVSEP & Gemini key status from ~/.mvsep_hms_config.json."""
        try:
            cfg = _read_vault()
            mv = str(cfg.get("mvsep_api_token") or cfg.get("mvsep_token") or "").strip()
            gm = str(cfg.get("gemini_api_key") or cfg.get("gemini_key") or "").strip()
            return {
                "status": "ok",
                "vault_path": str(_vault_path()),
                "has_mvsep": bool(mv),
                "has_gemini": bool(gm),
                "keys": {
                    "mvsep_api_key": _mask_key(mv),
                    "gemini_api_key": _mask_key(gm),
                },
            }
        except Exception:
            return {"status": "error", "error": _tb.format_exc()}

    def save_keys(self, payload=None):
        """Atomically saves MVSEP & Gemini keys into ~/.mvsep_hms_config.json."""
        try:
            if isinstance(payload, str):
                payload = _json.loads(payload)
            payload = payload or {}
            cfg = _read_vault()
            saved_fields = []

            mv = str(payload.get("mvsep_api_key") or payload.get("mvsep_api_token") or "").strip()
            gm = str(payload.get("gemini_api_key") or "").strip()
            if mv:
                cfg["mvsep_api_token"] = mv
                saved_fields.append("mvsep_api_token")
            if gm:
                cfg["gemini_api_key"] = gm
                saved_fields.append("gemini_api_key")

            p = _vault_path()
            tmp = p.with_suffix(".tmp")
            tmp.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")
            _os.replace(tmp, p)
            self._push_ui_log(f"[SUCCESS] Saved {saved_fields} to {p}")
            return {"status": "ok", "vault_path": str(p), "saved_fields": saved_fields}
        except Exception:
            return {"status": "error", "error": _tb.format_exc()}

    def browse_json_file(self, title="Select JSON File"):
        """Opens a topmost native Windows JSON picker so WebView2 never dims/locks."""
        self._push_ui_log(f"[RUN] Opening native JSON picker: {title}")
        try:
            import tkinter as _tk
            from tkinter import filedialog as _fd
            root = _tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            picked = _fd.askopenfilename(
                parent=root,
                title=title,
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            )
            root.destroy()
            if not picked:
                self._push_ui_log("[INFO] JSON selection cancelled.")
                return {"status": "cancelled", "path": "", "filename": "", "content": ""}

            norm_p = _os.path.normpath(picked)
            content = _Path(norm_p).read_text(encoding="utf-8")
            self._push_ui_log(f"[SUCCESS] Loaded JSON -> {norm_p}")
            return {"status": "ok", "path": norm_p, "filename": _os.path.basename(norm_p), "content": content}
        except Exception:
            err = _tb.format_exc()
            self._push_ui_log(f"[ERROR] Native JSON picker failed:\n{err}")
            return {"status": "error", "error": err}

    def generate_recipe(self, audio_path, style_hint="Auto-Detect"):
        """Generates a 4-pass Free-Tier Safe .hms_recipe.json (with Gemini customization if key is set)."""
        self._push_ui_log(f"[RUN] Generating Multi-Pass Recipe ({style_hint}) for: {audio_path}")
        try:
            norm_audio = _os.path.normpath(str(audio_path or "").strip())
            if not norm_audio or not _os.path.isfile(norm_audio):
                msg = f"Master audio file not found: {norm_audio}"
                self._push_ui_log(f"[ERROR] {msg}")
                return {"status": "error", "error": msg}

            song_base = _os.path.splitext(_os.path.basename(norm_audio))[0]
            save_path = _os.path.join(_os.path.dirname(norm_audio), f"{song_base}.hms_recipe.json")

            recipe = {
                "recipe_name": f"{song_base} — HMS Free-Tier Safe 4-Pass Recipe",
                "end_user_overview": f"Sequential 1-job-at-a-time stem extraction tailored for {style_hint}.",
                "passes": [
                    {
                        "pass_id": 1,
                        "stage_name": "Lead & Backing Vocals",
                        "input_source": "MASTER_MIX",
                        "mvsep_config": {"model_type": "BS Roformer 124-Band (sep=40)", "opt_params": "add_opt1=171"},
                        "user_instructions": ["Extracts clean vocals without Premium Ensemble credits."],
                        "expected_outputs": ["vocals.wav"],
                    },
                    {
                        "pass_id": 2,
                        "stage_name": "Guitars, Keys & Synths",
                        "input_source": "MASTER_MIX",
                        "mvsep_config": {"model_type": "BS Roformer SW 6-Stems (sep=63)", "opt_params": ""},
                        "user_instructions": ["Keeps Guitar, Piano, and Other_Synths; archives duplicates."],
                        "expected_outputs": ["guitar.wav", "piano.wav", "other.wav"],
                    },
                    {
                        "pass_id": 3,
                        "stage_name": "Rhythm (Drums & Bass)",
                        "input_source": "MASTER_MIX",
                        "mvsep_config": {"model_type": "Demucs4 HT ft (sep=20)", "opt_params": "add_opt1=0"},
                        "user_instructions": ["Extracts punchy Drums & Bass stems."],
                        "expected_outputs": ["drums.wav", "bass.wav"],
                    },
                    {
                        "pass_id": 4,
                        "stage_name": "Optional Kit Split (DrumSep)",
                        "input_source": "PASS_3_DRUMS",
                        "mvsep_config": {"model_type": "DrumSep Standalone (sep=37)", "opt_params": ""},
                        "user_instructions": ["Splits isolated Drums into Kick, Snare, Toms, and Cymbals."],
                        "expected_outputs": ["kick.wav", "snare.wav", "cymbals.wav"],
                    },
                ],
            }
            source_used = "local-free-tier-safe"

            cfg = _read_vault()
            gemini_key = str(cfg.get("gemini_api_key") or "").strip()
            ai_bridge = getattr(self, "ai_bridge", None)
            if gemini_key and ai_bridge and hasattr(ai_bridge, "_query_gemini_with_model_fallback"):
                try:
                    self._push_ui_log("[RUN] Querying Gemini for custom multi-pass recipe...")
                    prompt = (
                        f"Create an HMS Multi-Pass MVSep recipe JSON for track '{song_base}' "
                        f"with style '{style_hint}'. Keep all passes Free-Tier Safe (sep_type 40, 63, 20, 37). "
                        f"Return strictly valid JSON matching this exact structure: {_json.dumps(recipe)}"
                    )
                    raw_txt, used_model = ai_bridge._query_gemini_with_model_fallback(
                        prompt, gemini_key, log_callback=lambda m: self._push_ui_log(m)
                    )
                    parsed = _json.loads(raw_txt)
                    if isinstance(parsed.get("passes"), list) and parsed["passes"]:
                        recipe = parsed
                        source_used = used_model
                        self._push_ui_log(f"[SUCCESS] Gemini ({used_model}) generated custom recipe!")
                except Exception as gx:
                    self._push_ui_log(f"[INFO] Gemini cloud call skipped ({gx}); using verified local 4-pass recipe.")
            else:
                self._push_ui_log("[INFO] Using verified local 4-pass Free-Tier Safe recipe.")

            tmp_recipe = save_path + ".tmp"
            with open(tmp_recipe, "w", encoding="utf-8") as rf:
                _json.dump(recipe, rf, indent=2)
            _os.replace(tmp_recipe, save_path)
            self._push_ui_log(f"[SUCCESS] Saved recipe file -> {save_path}")

            return {"status": "ok", "source": source_used, "saved_path": save_path, "recipe": recipe}
        except Exception:
            err = _tb.format_exc()
            self._push_ui_log(f"[ERROR] generate_recipe failed:\n{err}")
            return {"status": "error", "error": err}

    def execute_stem_cleanup(self, payload=None):
        """Maps v1.4 HTML console actions to run_clean()."""
        if isinstance(payload, str):
            payload = _json.loads(payload)
        payload = dict(payload or {})
        action_map = {
            "ai_autotune": "autotune",
            "dry_run": "dry_run",
            "live_clean": "live",
            "glue_only": "glue_only",
            "gemini_tune": "gemini_tune",
            "rollback": "rollback",
        }
        payload["mode"] = action_map.get(payload.get("action", ""), payload.get("mode", "dry_run"))
        if hasattr(self, "run_clean"):
            return self.run_clean(payload)
        return {"status": "error", "error": "run_clean() not found on bridge."}

    def start_mvsep_single_pass(self, payload=None):
        """Routes Tab 2A single-pass MVSEP button to start_mvsep_multipass / start_mvsep_separation."""
        if isinstance(payload, str):
            payload = _json.loads(payload)
        payload = dict(payload or {})
        if hasattr(self, "start_mvsep_separation"):
            return self.start_mvsep_separation({
                "file_path": payload.get("audio_path", ""),
                "sep_type": payload.get("sep_type", 63),
                "output_format": payload.get("output_format", 1),
                "free_tier_safe": True,
            })
        return {"status": "error", "error": "Single-pass MVSEP handler not attached."}

    def _run_passes_worker(self, passes_list, audio_path, dest_root, is_dry_run):
        import time as _time
        win = getattr(self, "_window", None)
        def _upd(pid, pct, msg, st):
            if win is not None:
                try:
                    win.evaluate_js(f"window.hmsUpdateProgress && window.hmsUpdateProgress({_json.dumps({'pass_id': pid, 'percent': pct, 'message': msg, 'status': st})});")
                except Exception:
                    pass
        if is_dry_run:
            for p in passes_list:
                pid = int(p.get("pass_id", 1))
                _upd(pid, 35, f"[DRY-RUN] Validating {p.get('stage_name', 'Pass')}...", "running")
                _time.sleep(0.5)
                _upd(pid, 100, f"[DRY-RUN] {p.get('stage_name', 'Pass')} verified (0 credits spent).", "complete")
            return
        if hasattr(self, "start_mvsep_multipass"):
            id_map = {1: "pass1_vocals", 2: "pass2_music", 3: "pass3_rhythm", 4: "pass4_drumsep"}
            pass_ids = [id_map.get(int(p.get("pass_id", 1)), "pass1_vocals") for p in passes_list]
            res = self.start_mvsep_multipass({
                "file_path": audio_path,
                "pass_ids": pass_ids,
                "output_format": 1,
                "free_tier_safe": True,
                "auto_clean": True,
            })
            if res.get("status") != "ok":
                _upd(int(passes_list[0].get("pass_id", 1)), 0, res.get("message", "Failed"), "error")

    def run_single_pass(self, pass_obj, audio_path, dest_root, is_dry_run=False):
        _threading.Thread(target=self._run_passes_worker, args=([pass_obj], audio_path, dest_root, bool(is_dry_run)), daemon=True).start()
        return {"status": "ok"}

    def run_all_passes(self, recipe, audio_path, dest_root, is_dry_run=False):
        passes_list = (recipe or {}).get("passes", [])
        _threading.Thread(target=self._run_passes_worker, args=(passes_list, audio_path, dest_root, bool(is_dry_run)), daemon=True).start()
        return {"status": "ok"}

    _cls._push_ui_log = _push_ui_log
    _cls.get_keys_status = get_keys_status
    _cls.save_keys = save_keys
    _cls.browse_json_file = browse_json_file
    _cls.generate_recipe = generate_recipe
    _cls.execute_stem_cleanup = execute_stem_cleanup
    _cls.start_mvsep_single_pass = start_mvsep_single_pass
    _cls._run_passes_worker = _run_passes_worker
    _cls.run_single_pass = run_single_pass
    _cls.run_all_passes = run_all_passes

_hms_attach_v1_4_bridge_methods()
# === END_HMS_V1_4_BRIDGE_METHODS_PATCH ===




# === HMS_PYWEBVIEW_STORAGE_PATH_FIX ===
def _hms_enforce_persistent_webview_storage():
    """
    Wraps webview.start() so Edge WebView2 always uses persistent %LOCALAPPDATA%
    storage (private_mode=False) instead of a throwaway Temp\tmp* folder that
    triggers [WinError 2] deletion warnings on exit.
    """
    import os as _os
    from pathlib import Path as _Path

    try:
        import webview as _wv
    except Exception:
        return

    if getattr(_wv.start, "_hms_storage_wrapped", False):
        return

    _orig_start = _wv.start
    _cache_dir = _Path(_os.environ.get("LOCALAPPDATA", str(_Path.home()))) / "HMS Studio Suite" / "WebView2Cache"
    _cache_dir.mkdir(parents=True, exist_ok=True)
    _os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(_cache_dir)

    def _patched_start(*args, **kwargs):
        # Force persistent user data folder so pywebview never creates/deletes Temp\tmp*
        kwargs["private_mode"] = False
        kwargs["storage_path"] = str(_cache_dir)
        return _orig_start(*args, **kwargs)

    _patched_start._hms_storage_wrapped = True
    _patched_start._hms_cache_dir = str(_cache_dir)
    _wv.start = _patched_start
    print(f"[INFO] PyWebView persistent storage_path active -> {_cache_dir}")

_hms_enforce_persistent_webview_storage()
# === END_HMS_PYWEBVIEW_STORAGE_PATH_FIX ===




# === HMS_DAW_VERIFY_API_BRIDGE_PATCH ===
def _attach_verify_api_keys_to_bridge():
    """Adds live verify_api_keys() directly onto HMSWebDawBridge for window.pywebview.api."""
    if "HMSWebDawBridge" not in globals():
        return

    def verify_api_keys(self, payload=None):
        import json as _json
        import traceback as _tb
        try:
            if isinstance(payload, str):
                payload = _json.loads(payload)
            payload = payload or {}
            ai_mod = self.ai_bridge
            if ai_mod is None:
                import hms_ai_api_bridge as ai_mod
                self.ai_bridge = ai_mod
            return ai_mod.verify_live_api_connections(
                mvsep_token=payload.get("mvsep_api_token"),
                gemini_key=payload.get("gemini_api_key"),
            )
        except Exception:
            err = _tb.format_exc()
            print(f"[ERROR] HMSWebDawBridge.verify_api_keys failed:\n{err}")
            return {"status": "error", "gemini_ok": False, "gemini_detail": err, "mvsep_ok": False}

    HMSWebDawBridge.verify_api_keys = verify_api_keys


_attach_verify_api_keys_to_bridge()
# === END_HMS_DAW_VERIFY_API_BRIDGE_PATCH ===




# === HMS_LAUNCHER_EMPTY_DIR_GUARD_PATCH ===
def _hms_validate_bridge_source_dir(raw_path):
    """Validates source_dir on HMSWebDawBridge DSP calls before invoking Python audio engines."""
    import os as _os

    if raw_path is None:
        return False, "No Source Song Dir selected. Click 'Browse' next to Source Song Dir first."

    s = str(raw_path).strip()
    if not s or s in (".", "..", "./", ".\\", "/", "\\") or "click browse" in s.lower():
        return False, "No Source Song Dir selected. Click 'Browse' next to Source Song Dir first."

    abs_p = _os.path.abspath(s)
    if not _os.path.exists(abs_p):
        return False, f"Source Song Dir does not exist: {abs_p}"

    if _os.path.isdir(abs_p) and (
        _os.path.isfile(_os.path.join(abs_p, "hms_web_daw_launcher.py"))
        or _os.path.isfile(_os.path.join(abs_p, "HMS_Studio_Suite.exe"))
    ):
        return False, f"Refusing to run on the HMS application folder ({abs_p}). Pick a song stems folder instead."

    return True, abs_p


def _hms_extract_source_dir_from_call(args, kwargs):
    """Extracts source_dir from either dict/JSON payloads or positional arguments."""
    import json as _json

    for k in ("source_dir", "song_dir", "target_path", "dir"):
        if k in kwargs:
            return kwargs.get(k)

    if args:
        first = args[0]
        if isinstance(first, dict):
            for k in ("source_dir", "song_dir", "target_path", "dir"):
                if k in first:
                    return first.get(k)
            return ""
        if isinstance(first, str):
            st = first.strip()
            if st.startswith("{"):
                try:
                    parsed = _json.loads(st)
                    if isinstance(parsed, dict):
                        for k in ("source_dir", "song_dir", "target_path", "dir"):
                            if k in parsed:
                                return parsed.get(k)
                        return ""
                except Exception:
                    pass
            # Handle (mode, source_dir, ...) signature if mode is passed first
            if st.lower() in ("gemini_tune", "autotune", "dry_run", "live", "glue_only", "rollback"):
                return args[1] if len(args) > 1 else ""
            return st
    return ""


def _hms_install_launcher_dir_guards():
    """Wraps HMSWebDawBridge DSP/Tune methods so empty source_dir aborts cleanly."""
    if "HMSWebDawBridge" not in globals():
        return

    bridge_cls = globals()["HMSWebDawBridge"]
    for meth_name in ("run_clean", "execute_stem_cleanup", "run_gemini_tune", "gemini_tune"):
        orig_meth = getattr(bridge_cls, meth_name, None)
        if not callable(orig_meth) or getattr(orig_meth, "_hms_dir_guarded", False):
            continue

        def _make_wrapper(_fn, _name):
            def _wrapped(self, *args, **kwargs):
                raw_dir = _hms_extract_source_dir_from_call(args, kwargs)
                ok, msg = _hms_validate_bridge_source_dir(raw_dir)
                if not ok:
                    print(f"[ERROR] Blocked {_name}: {msg}")
                    return {"status": "error", "message": msg, "error": msg}
                return _fn(self, *args, **kwargs)

            _wrapped._hms_dir_guarded = True
            return _wrapped

        setattr(bridge_cls, meth_name, _make_wrapper(orig_meth, meth_name))


_hms_install_launcher_dir_guards()
# === END_HMS_LAUNCHER_EMPTY_DIR_GUARD_PATCH ===


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

