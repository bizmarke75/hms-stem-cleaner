import os
import sys
try:
    from hms_runtime_paths import resolve_hms_runtime_paths as _resolve_hms_paths
    _HMS_PATHS = _resolve_hms_paths() or {}
except Exception:
    _HMS_PATHS = {}

import json
import os
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import webview

from hms_daw_bridge_helpers import generate_gemini_recipe_manifest, open_native_file_dialog
from hms_mvsep_downloader import poll_and_download_mvsep_stems
from hms_mvsep_uploader import upload_to_mvsep_streamed
from hms_recipe_runner import (
    _safe_folder_name,
    execute_single_recipe_pass,
    run_recipe_manifest,
)
from hms_vault_and_progress import (
    get_vault_path,
    load_api_vault,
    push_progress_update,
    save_api_vault,
)

# Directories skipped during recursive script lookup so virtualenvs/build caches are ignored
_IGNORED_SEARCH_DIRS = {".git", ".venv", "venv", "__pycache__", "build", "dist", "node_modules"}


def find_headless_dsp_script(repo_root: Path, filename: str = "hms_headless_dsp.py") -> Optional[Path]:
    """
    Locate hms_headless_dsp.py automatically in the repo root or any subfolder (including backups).

    Priority order:
        1. Exact match in repo_root.
        2. First match in an active subfolder (e.g., src/, scripts/).
        3. Fallback match in a backup subfolder (e.g., 'src_backup', 'backups').

    Args:
        repo_root: Root directory of the hms-stem-cleaner repository.
        filename: Target Python filename to discover.

    Returns:
        Optional[Path]: Resolved Path to the script, or None if not found.
    """
    print(f"[RUN] Searching for {filename} under {repo_root}...")
    try:
        direct_candidate = repo_root / filename
        if direct_candidate.is_file():
            print(f"[SUCCESS] Found {filename} in repo root -> {direct_candidate}")
            return direct_candidate

        active_matches = []
        backup_matches = []

        for candidate in repo_root.rglob(filename):
            if not candidate.is_file():
                continue

            rel_parts = candidate.relative_to(repo_root).parts[:-1]
            if any(part.lower() in _IGNORED_SEARCH_DIRS for part in rel_parts):
                continue

            if any("backup" in part.lower() or "bak" in part.lower() for part in rel_parts):
                backup_matches.append(candidate)
            else:
                active_matches.append(candidate)

        if active_matches:
            active_matches.sort(key=lambda p: (len(p.parts), str(p).lower()))
            chosen = active_matches[0]
            print(f"[SUCCESS] Auto-discovered {filename} in subfolder -> {chosen}")
            return chosen

        if backup_matches:
            backup_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            chosen = backup_matches[0]
            print(f"[INFO] No root copy found; using backup subfolder copy -> {chosen}")
            return chosen

        print(f"[ERROR] {filename} was not found anywhere under {repo_root}")
        return None
    except Exception:
        print("[ERROR] find_headless_dsp_script() encountered an exception:")
        print(traceback.format_exc())
        return None


def build_headless_dsp_command(
    headless_script: Path,
    payload: Dict[str, Any],
    python_exe: Optional[str] = None,
) -> List[str]:
    """
    Build the exact CLI argument list accepted by hms_headless_dsp.py:
        [--source SOURCE] [--dest DEST] [--live] [--move] [--no-master]

    Args:
        headless_script: Resolved Path to hms_headless_dsp.py.
        payload: Mix settings and action payload sent from the v1.4 Web DAW UI.
        python_exe: Optional Python interpreter override (defaults to sys.executable).

    Returns:
        List[str]: Subprocess argument list safe for Windows paths containing spaces.
    """
    print("[RUN] Building hms_headless_dsp.py CLI command...")
    try:
        song_dir = str(payload.get("song_dir", "")).strip()
        if not song_dir:
            raise ValueError("payload['song_dir'] is required for --source.")

        # Fall back to parent folder of song_dir if Dest Root was left blank in the UI
        dest_root = str(payload.get("dest_root", "")).strip()
        if not dest_root:
            dest_root = str(Path(song_dir).parent)
            print(f"[INFO] Dest Root blank; defaulting --dest to parent folder -> {dest_root}")

        action = str(payload.get("action", "live_clean")).strip().lower()
        is_dry_run = bool(payload.get("dry_run", False)) or (action == "dry_run")
        move_raw = bool(payload.get("move_source_files", False))
        no_master = bool(payload.get("no_master", False))

        cmd: List[str] = [
            python_exe or sys.executable,
            str(headless_script),
            "--source",
            song_dir,
            "--dest",
            dest_root,
        ]

        # hms_headless_dsp.py runs a dry-run audit by default and requires --live for real writes
        if not is_dry_run:
            cmd.append("--live")
        if move_raw:
            cmd.append("--move")
        if no_master:
            cmd.append("--no-master")

        print(f"[SUCCESS] Built DSP command: {cmd}")
        return cmd
    except Exception:
        print("[ERROR] build_headless_dsp_command() failed:")
        print(traceback.format_exc())
        raise


def _save_mix_settings_sidecar(song_path: Path, payload: Dict[str, Any]) -> Optional[Path]:
    """
    Persist <Song_Name>_MIX_SETTINGS.json inside song_path, stripping any trailing '_Stems' suffix
    so hms_mix_json_manager.py and hms_headless_dsp.py locate the active 9-slider preset cleanly.
    """
    if not song_path.exists():
        print(f"[INFO] Source song path does not exist yet; skipping preset sidecar write: {song_path}")
        return None
    try:
        clean_song_name = re.sub(r"_stems$", "", song_path.name, flags=re.IGNORECASE) or song_path.name
        preset_file = song_path / f"{clean_song_name}_MIX_SETTINGS.json"
        preset_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[SUCCESS] Saved 9-slider sidecar preset -> {preset_file}")
        return preset_file
    except Exception:
        print("[ERROR] Failed to write _MIX_SETTINGS.json sidecar:")
        print(traceback.format_exc())
        return None


def _push_console_log(window: Any, message: str) -> None:
    """Thread-safely forward a diagnostic line into the 337 West bottom console."""
    print(message)
    if window is None:
        return
    try:
        js_code = f"window.hmsPushConsoleLog && window.hmsPushConsoleLog({json.dumps(str(message))});"
        if hasattr(window, "run_js"):
            window.run_js(js_code)
        else:
            window.evaluate_js(js_code)
    except Exception:
        print(traceback.format_exc())


def _sync_source_dir_ui(window: Any, folder_path: str) -> None:
    """Auto-populate the Console Source Song Dir field when MVSEP finishes downloading."""
    if window is None:
        return
    try:
        js_code = f"window.hmsSetSourceSongDir && window.hmsSetSourceSongDir({json.dumps(str(folder_path))});"
        if hasattr(window, "run_js"):
            window.run_js(js_code)
        else:
            window.evaluate_js(js_code)
    except Exception:
        print(traceback.format_exc())


class WebDawApi:
    """Unified pywebview 6.2.1 JS-to-Python API for 337 West HMS Unified Studio Suite v1.4."""

    def __init__(self) -> None:
        self._window = None
        self._active_registry: Dict[str, Dict[str, str]] = {}

    def bind_window(self, window: Any) -> None:
        self._window = window

    # --- 1. Persistent API Vault ---
    def save_keys(self, keys_payload: dict) -> dict:
        return save_api_vault(keys_payload)

    def get_keys_status(self) -> dict:
        return load_api_vault(mask_values=True)

    # --- 2. Native Windows Explorer Pickers ---
    def browse_master_audio(self) -> dict:
        return open_native_file_dialog(self._window, mode="audio")

    def browse_output_folder(self) -> dict:
        return open_native_file_dialog(self._window, mode="folder")

    # --- 3. Gemini / Local Recipe Generator ---
    def generate_recipe(self, audio_path: str, style_hint: str = "Auto-Detect") -> dict:
        return generate_gemini_recipe_manifest(audio_path=audio_path, style_hint=style_hint)

    # --- 4. Real FLAC-Streamed Single-Pass MVSEP Pipeline (pass_id=0) ---
    def start_mvsep_single_pass(self, config: dict) -> dict:
        audio_path = str(config.get("audio_path", "")).strip()
        dest_root = str(config.get("dest_root", "")).strip()
        sep_type = int(config.get("sep_type", 63))
        output_format = int(config.get("output_format", 1))
        auto_clean = bool(config.get("auto_clean", False))
        mix_payload = config.get("mix_payload") or {}

        if not audio_path or not dest_root:
            return {"status": "error", "error": "Both audio_path and dest_root are required."}

        def _single_mvsep_worker() -> None:
            try:
                vault = load_api_vault(mask_values=False)
                token = vault.get("keys", {}).get("mvsep_api_key", "")
                if not token:
                    push_progress_update(
                        self._window, 0, 0,
                        "Missing MVSEP API key! Click 'API Vault' in the top bar and save your key first.",
                        status="error",
                    )
                    return

                song_name = _safe_folder_name(Path(audio_path).stem)
                stems_out_dir = Path(dest_root) / f"{song_name}_Stems"
                stems_out_dir.mkdir(parents=True, exist_ok=True)

                up_res = upload_to_mvsep_streamed(
                    audio_path=audio_path,
                    api_token=token,
                    sep_type=sep_type,
                    output_format=output_format,
                    window=self._window,
                    pass_id=0,
                )
                if up_res.get("status") != "ok":
                    return

                dl_res = poll_and_download_mvsep_stems(
                    job_hash=up_res["hash"],
                    endpoint_used=up_res["endpoint_used"],
                    output_dir=str(stems_out_dir),
                    window=self._window,
                    pass_id=0,
                )
                if dl_res.get("status") != "ok":
                    return

                _sync_source_dir_ui(self._window, str(stems_out_dir))
                if auto_clean:
                    mix_payload["song_dir"] = str(stems_out_dir)
                    mix_payload["dest_root"] = dest_root
                    mix_payload["action"] = "live_clean"
                    mix_payload["dry_run"] = False
                    self.execute_stem_cleanup(mix_payload)
            except Exception as exc:
                print(traceback.format_exc())
                push_progress_update(self._window, 0, 0, f"Single-pass MVSEP error: {exc}", status="error")

        threading.Thread(target=_single_mvsep_worker, daemon=True).start()
        return {"status": "started", "pass_id": 0}

    # --- 5. Multi-Pass Recipe Chainer (Single Card or Full Chain) ---
    def run_single_pass(
        self,
        pass_config: dict,
        master_wav_path: str,
        dest_root_dir: str,
        dry_run: bool = False,
    ) -> dict:
        def _worker() -> None:
            vault = load_api_vault(mask_values=False)
            token = vault.get("keys", {}).get("mvsep_api_key", "")
            song_out_dir = Path(dest_root_dir) / _safe_folder_name(Path(master_wav_path).stem)
            song_out_dir.mkdir(parents=True, exist_ok=True)
            execute_single_recipe_pass(
                pass_config=pass_config,
                master_wav_path=master_wav_path,
                song_out_dir=song_out_dir,
                stem_registry=self._active_registry,
                api_token=token,
                window=self._window,
                dry_run=dry_run,
            )

        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "started", "pass_id": pass_config.get("pass_id")}

    def run_all_passes(
        self,
        recipe_data: dict,
        master_wav_path: str,
        dest_root_dir: str,
        dry_run: bool = False,
    ) -> dict:
        def _chain_worker() -> None:
            res = run_recipe_manifest(
                recipe_data=recipe_data,
                master_wav_path=master_wav_path,
                dest_root_dir=dest_root_dir,
                window=self._window,
                dry_run=dry_run,
            )
            if res.get("status") == "ok":
                self._active_registry = res.get("registry", {})
                if res.get("song_out_dir"):
                    _sync_source_dir_ui(self._window, res["song_out_dir"])

        threading.Thread(target=_chain_worker, daemon=True).start()
        return {"status": "started", "total_passes": len(recipe_data.get("passes", []))}

    # --- 6. Tab 1 Console 9-Slider Headless DSP Bridge ---
    def execute_stem_cleanup(self, payload: dict) -> dict:
        song_dir = str(payload.get("song_dir", "")).strip()
        action = str(payload.get("action", "live_clean"))

        if not song_dir:
            return {"status": "error", "error": "Select a Source Song Dir first."}

        def _dsp_worker() -> None:
            try:
                repo_root = Path(__file__).resolve().parent
                headless_script = find_headless_dsp_script(repo_root)
                song_path = Path(song_dir)

                # Persist active 9-slider preset as <Song_Name>_MIX_SETTINGS.json inside song_dir
                preset_file = _save_mix_settings_sidecar(song_path, payload)
                if preset_file:
                    _push_console_log(self._window, f"[SUCCESS] Saved active 9-slider config -> {preset_file}")

                if headless_script is None:
                    _push_console_log(
                        self._window,
                        f"[ERROR] hms_headless_dsp.py not found anywhere under {repo_root}; saved preset JSON only.",
                    )
                    return

                _push_console_log(self._window, f"[INFO] Resolved DSP engine -> {headless_script}")

                # Expose both repo_root and script's subfolder on PYTHONPATH so sibling module imports resolve cleanly
                sub_env = os.environ.copy()
                extra_paths = [str(repo_root), str(headless_script.parent)]
                existing_pypath = sub_env.get("PYTHONPATH", "")
                sub_env["PYTHONPATH"] = os.pathsep.join(
                    extra_paths + ([existing_pypath] if existing_pypath else [])
                )

                # Use the exact argparse flags supported by hms_headless_dsp.py
                cmd = build_headless_dsp_command(headless_script, payload)
                _push_console_log(self._window, f"[RUN] Executing ({action}): {' '.join(cmd)}")

                proc = subprocess.run(
                    cmd,
                    cwd=str(repo_root),
                    env=sub_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                for line in (proc.stdout or "").splitlines():
                    if line.strip():
                        _push_console_log(self._window, line)
                if proc.returncode != 0:
                    err_text = (proc.stderr or "").strip()
                    _push_console_log(self._window, f"[ERROR] hms_headless_dsp.py exited {proc.returncode}: {err_text}")
                else:
                    _push_console_log(self._window, f"[SUCCESS] Console action '{action}' completed cleanly.")
            except Exception as exc:
                print(traceback.format_exc())
                _push_console_log(self._window, f"[ERROR] DSP worker crashed: {exc}")

        threading.Thread(target=_dsp_worker, daemon=True).start()
        return {"status": "started", "action": action, "song_dir": song_dir}


def launch_web_daw() -> None:
    api = WebDawApi()
    repo_root = Path(__file__).resolve().parent
    ui_html = repo_root / "337_west_hms_unified_studio_web_daw_v1.4.html"
    if not ui_html.exists():
        raise FileNotFoundError(
            f"Missing UI file: {ui_html}\n"
            "Drop 337_west_hms_unified_studio_web_daw_v1.4.html into your hms-stem-cleaner repo root."
        )

    storage_dir = get_vault_path().parent / "webview_storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    window = webview.create_window(
        title="337 WEST // HMS UNIFIED STUDIO SUITE (v1.4 LIVE Web-DAW)",
        url=str(ui_html),
        js_api=api,
        width=1480,
        height=920,
    )
    api.bind_window(window)

    # private_mode=False + static storage_path ensures WebView2 persists state cleanly
    webview.start(
        private_mode=False,
        storage_path=str(storage_dir),
        debug=False,
    )












# === HMS_MVSEP_MULTIPASS_BRIDGE_PATCH ===
def _attach_free_tier_multipass_to_bridge():
    import json as _json
    import traceback as _tb
    from pathlib import Path as _Path
    import hms_mvsep_multipass as _mp

    # Auto-discover the active JS API bridge class defined in this launcher module
    _bridge_method_hints = {
        "run_clean", "get_status", "browse_folder", "browse_song_file",
        "start_mvsep_separation", "save_credentials", "load_credentials",
        "list_song_wavs", "run_action", "clean_stems", "get_config",
    }
    _candidates = []
    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and getattr(_obj, "__module__", None) == __name__:
            _attrs = set(dir(_obj))
            _score = len(_attrs & _bridge_method_hints) * 10
            if any(k in _name.lower() for k in ("bridge", "api", "daw", "studio")):
                _score += 5
            _candidates.append((_score, _name, _obj))

    if _candidates:
        _candidates.sort(key=lambda item: item[0], reverse=True)
        _target_cls = _candidates[0][2]
        print(f"[INFO] Multipass hook attached to bridge class: {_target_cls.__name__}")
    else:
        class HMSWebDawBridge:
            pass
        _target_cls = HMSWebDawBridge
        print("[INFO] No bridge class found in launcher; created fallback HMSWebDawBridge.")

    # Alias HMSWebDawBridge so REST/Chrome bridges and verification scripts always resolve it
    globals().setdefault("HMSWebDawBridge", _target_cls)

    def _resolve_saved_mvsep_token(payload_token=""):
        tok = str(payload_token or "").strip()
        if tok:
            return tok
        cfg_file = _Path.home() / ".mvsep_hms_config.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as cf:
                    cfg = _json.load(cf)
                return str(cfg.get("mvsep_api_token") or cfg.get("mvsep_token") or "").strip()
            except Exception:
                pass
        return ""

    def get_mvsep_multipass_recipe(self):
        return {
            "status": "ok",
            "recipe": _mp.HMS_FREE_MULTIPASS_RECIPE,
            "blocked_sep_types": sorted(_mp.PREMIUM_BLOCKED_SEP_TYPES),
            "blocked_formats": sorted(_mp.PREMIUM_BLOCKED_FORMATS),
        }

    def start_mvsep_multipass(self, payload=None):
        try:
            if isinstance(payload, str):
                payload = _json.loads(payload)
            payload = payload or {}

            if hasattr(self, "_mvsep_lock") and hasattr(self, "_mvsep_state"):
                with self._mvsep_lock:
                    if self._mvsep_state.get("running"):
                        return {
                            "status": "error",
                            "message": "MVSep Concurrency Lock: A single-pass MVSep job is already running (max 1 concurrent job).",
                        }

            api_token = _resolve_saved_mvsep_token(payload.get("api_token", ""))
            return _mp.SHARED_MULTIPASS_RUNNER.start_multipass(
                api_token=api_token,
                song_file_path=str(payload.get("file_path") or "").strip(),
                pass_ids=payload.get("pass_ids") or ["pass1_vocals", "pass2_music", "pass3_rhythm"],
                output_format=int(payload.get("output_format", 1)),
                free_tier_safe=bool(payload.get("free_tier_safe", True)),
                auto_clean=bool(payload.get("auto_clean", True)),
                mix_style=str(payload.get("mix_style") or "auto"),
            )
        except Exception:
            err = _tb.format_exc()
            print(f"[ERROR] start_mvsep_multipass failed:\n{err}")
            return {"status": "error", "message": err}

    def get_mvsep_multipass_status(self):
        try:
            st = _mp.SHARED_MULTIPASS_RUNNER.get_status()
            st["status"] = "ok"
            return st
        except Exception:
            return {"status": "error", "running": False, "logs": [_tb.format_exc()]}

    def cancel_mvsep_multipass(self):
        try:
            return _mp.SHARED_MULTIPASS_RUNNER.cancel()
        except Exception:
            return {"status": "error", "message": _tb.format_exc()}

    # Guard single-pass start_mvsep_separation if present on the discovered bridge class
    _orig_single_start = getattr(_target_cls, "start_mvsep_separation", None)
    if callable(_orig_single_start):
        def _guarded_start_mvsep_separation(self, payload=None):
            if isinstance(payload, str):
                payload = _json.loads(payload)
            payload = payload or {}

            if _mp.SHARED_MULTIPASS_RUNNER.get_status().get("running"):
                return {
                    "status": "error",
                    "message": "MVSep Concurrency Lock: Sequential Multi-Pass queue is active (max 1 concurrent job on Free Tier).",
                }

            free_safe = bool(payload.get("free_tier_safe", True))
            chk = _mp.validate_mvsep_free_tier_request(
                sep_type=payload.get("sep_type", 63),
                output_format=payload.get("output_format", 1),
                file_path=str(payload.get("file_path") or "").strip() or None,
                free_tier_safe=free_safe,
            )
            if not chk["ok"]:
                return {"status": "error", "message": chk["reason"]}
            return _orig_single_start(self, payload)

        _target_cls.start_mvsep_separation = _guarded_start_mvsep_separation

    _target_cls.get_mvsep_multipass_recipe = get_mvsep_multipass_recipe
    _target_cls.start_mvsep_multipass = start_mvsep_multipass
    _target_cls.get_mvsep_multipass_status = get_mvsep_multipass_status
    _target_cls.cancel_mvsep_multipass = cancel_mvsep_multipass


_attach_free_tier_multipass_to_bridge()


if __name__ == "__main__":
    launch_web_daw()
