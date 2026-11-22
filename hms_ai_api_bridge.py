import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import requests

CONFIG_FILE_PATH = Path.home() / ".mvsep_hms_config.json"
# HMS_BRIDGE_FROZEN_SAFE
HMS_REPO_DIR = (
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

GEMINI_MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

_CONFIG_LOCK = threading.Lock()
_DSP_RENDER_LOCK = threading.Lock()

if HMS_REPO_DIR not in sys.path and os.path.isdir(HMS_REPO_DIR):
    sys.path.insert(0, HMS_REPO_DIR)


def load_ai_credentials(config_path=CONFIG_FILE_PATH, log_callback=print):
    creds = {
        "mvsep_api_token": os.environ.get("MVSEP_API_TOKEN", "").strip(),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", "").strip(),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", "").strip(),
        "mix_mode_label": "Auto-Detect (Acoustic / Dynamic Rock vs. Heavy Metal)",
    }
    try:
        with _CONFIG_LOCK:
            if config_path.is_file():
                with open(config_path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                for key in creds:
                    val = str(stored.get(key, "")).strip()
                    if val:
                        creds[key] = val
                log_callback(f"[INFO] Loaded AI credentials from: {config_path}")
    except Exception:
        log_callback("[ERROR] Failed reading AI credentials config:")
        log_callback(traceback.format_exc())
    return creds


def save_ai_credentials(updates_dict, config_path=CONFIG_FILE_PATH, log_callback=print):
    log_callback("[RUN] Saving AI API credentials to disk...")
    try:
        with _CONFIG_LOCK:
            existing = {}
            if config_path.is_file():
                with open(config_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)

            for k, v in updates_dict.items():
                if v is not None and str(v).strip():
                    existing[k] = str(v).strip()

            temp_path = config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            os.replace(temp_path, config_path)

        log_callback(f"[SUCCESS] AI API credentials saved -> {config_path}")
        return True
    except Exception:
        log_callback("[ERROR] Failed saving AI API credentials:")
        log_callback(traceback.format_exc())
        return False


def _query_gemini_with_model_fallback(prompt_text, api_key, log_callback=print):
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    last_error = "No Gemini model candidates succeeded."
    for model_name in GEMINI_MODEL_CANDIDATES:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
        )
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code in (403, 404):
                last_error = f"{model_name} HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return raw_text, model_name
        except requests.RequestException as ex:
            last_error = f"{model_name} error: {ex}"
    raise RuntimeError(last_error)


def generate_ai_mix_and_suno_report(
    song_name,
    telemetry,
    mix_style="auto",
    api_key="",
    provider="gemini",
    log_callback=print,
):
    log_callback("=" * 65)
    log_callback(f"[RUN] Requesting AI Mix & Suno Advisor ({provider.upper()}) for '{song_name}'...")
    clean_key = (api_key or "").strip()
    if not clean_key:
        creds = load_ai_credentials(log_callback=lambda _: None)
        clean_key = creds.get("gemini_api_key" if provider.lower() == "gemini" else "openai_api_key", "")
    if not clean_key:
        log_callback("[INFO] no LLM API key configured; skipping cloud AI mix report.")
        return {"status": "skipped", "model_used": "none", "mix_notes": "", "suno_tags": ""}

    prompt_text = (
        f"You are a mastering engineer and Suno AI v6 prompt architect.\n"
        f"Track Title: {song_name}\n"
        f"Detected/Selected Mix Style: {mix_style}\n"
        f"HMS DSP Telemetry JSON: {json.dumps(telemetry, default=str)}\n\n"
        'Return strictly valid JSON with two keys: "mix_notes" (3 concise bullet points) and "suno_tags" (comma-separated Suno v6 tags under 250 chars).'
    )
    try:
        if provider.lower() == "gemini":
            raw_text, used_model = _query_gemini_with_model_fallback(prompt_text, clean_key, log_callback)
        else:
            used_model = "gpt-4o-mini"
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"},
                json={
                    "model": used_model,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt_text}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            raw_text = resp.json()["choices"][0]["message"]["content"].strip()

        parsed = json.loads(raw_text)
        result = {
            "status": "ok",
            "model_used": used_model,
            "mix_notes": parsed.get("mix_notes", ""),
            "suno_tags": parsed.get("suno_tags", ""),
        }
        log_callback(f"[SUCCESS] AI Mix & Suno Report generated via '{used_model}'")
        return result
    except Exception as ex:
        log_callback(f"[ERROR] AI Mix Advisor request failed (non-fatal): {ex}")
        return {"status": "error", "model_used": "none", "mix_notes": str(ex), "suno_tags": ""}


class _HMSRequestHandler(BaseHTTPRequestHandler):
    log_callback = print

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_str, *args):
        self.log_callback(f"[HMS-API]  -_s")

    def do_GET(self):
        if self.path == "/health":
            self._send_json(
                200,
                {
                    "status": "online",
                    "service": "HMS Stem Cleaner API",
                    "dsp_busy": _DSP_RENDER_LOCK.locked(),
                },
            )
        else:
            self._send_json(404, {"error": "Use GET /health or POST /api/clean"})

    def do_POST(self):
        if self.path != "/api/clean":
            self._send_json(404, {"error": "Use POST /api/clean"})
            return

        try:
            content_len = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(content_len).decode("utf-8")) if content_len else {}
            song_dir = req.get("song_dir", "")
            if not song_dir or not os.path.isdir(song_dir):
                self._send_json(400, {"error": f"Invalid song_dir: {song_dir}"})
                return

            with _DSP_RENDER_LOCK:
                import hms_stem_cleaner_app as hms
                res = hms.execute_stem_cleanup(
                    song_dir=song_dir,
                    dest_root=req.get("dest_root"),
                    dry_run=bool(req.get("dry_run", True)),
                    move_source_files=False,
                    render_master=True,
                )
            self._send_json(200, {"status": "completed", "result": res})
        except Exception as ex:
            self._send_json(500, {"error": str(ex), "traceback": traceback.format_exc()})


def start_local_hms_api_server(host="127.0.0.1", port=8765, log_callback=print):
    log_callback(f"[RUN] Starting Local HMS REST API Server on http://{host}:{port} ...")
    try:
        _HMSRequestHandler.log_callback = log_callback
        server = ThreadingHTTPServer((host, port), _HMSRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log_callback(f"[SUCCESS] HMS REST API listening at http://{host}:{port}/api/clean")
        return server, thread
    except Exception:
        log_callback("[ERROR] Failed starting Local HMS REST API Server:")
        log_callback(traceback.format_exc())
        return None, None




# === WEB_DAW_CREDENTIALS_ENDPOINT_PATCH ===
def _patch_hms_request_handler_for_credentials():
    orig_do_get = _HMSRequestHandler.do_GET
    orig_do_post = _HMSRequestHandler.do_POST

    def _do_options(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _enhanced_do_get(self):
        if self.path.startswith("/api/credentials"):
            creds = load_ai_credentials(log_callback=lambda _: None)
            self._send_json(200, {
                "status": "ok",
                "mvsep_api_token": creds.get("mvsep_api_token", ""),
                "gemini_api_key": creds.get("gemini_api_key", ""),
                "openai_api_key": creds.get("openai_api_key", ""),
            })
            return
        return orig_do_get(self)

    def _enhanced_do_post(self):
        if self.path.startswith("/api/credentials"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
                req = json.loads(raw) if raw else {}
                updates = {}
                mv_val = req.get("mvsep_api_token") or req.get("mvsep_token") or req.get("mvsepKey")
                gm_val = req.get("gemini_api_key") or req.get("gemini_key") or req.get("geminiKey")
                if mv_val is not None and str(mv_val).strip():
                    updates["mvsep_api_token"] = str(mv_val).strip()
                if gm_val is not None and str(gm_val).strip():
                    updates["gemini_api_key"] = str(gm_val).strip()
                ok = save_ai_credentials(updates)
                creds = load_ai_credentials(log_callback=lambda _: None)
                self._send_json(200 if ok else 500, {
                    "status": "ok" if ok else "error",
                    "mvsep_api_token": creds.get("mvsep_api_token", ""),
                    "gemini_api_key": creds.get("gemini_api_key", ""),
                })
            except Exception as ex:
                self._send_json(500, {"status": "error", "message": str(ex)})
            return
        return orig_do_post(self)

    _HMSRequestHandler.do_OPTIONS = _do_options
    _HMSRequestHandler.do_GET = _enhanced_do_get
    _HMSRequestHandler.do_POST = _enhanced_do_post


_patch_hms_request_handler_for_credentials()




# === WEB_DAW_FULL_REST_BRIDGE_PATCH ===
_SHARED_WEB_DAW_BRIDGE = None

def _get_shared_web_daw_bridge():
    global _SHARED_WEB_DAW_BRIDGE
    if _SHARED_WEB_DAW_BRIDGE is None:
        import hms_web_daw_launcher as launcher
        _SHARED_WEB_DAW_BRIDGE = launcher.HMSWebDawBridge()
    return _SHARED_WEB_DAW_BRIDGE


def _patch_rest_server_for_full_web_daw():
    prev_do_get = _HMSRequestHandler.do_GET
    prev_do_post = _HMSRequestHandler.do_POST

    def _full_do_get(self):
        if self.path.startswith("/api/mvsep/status"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.get_mvsep_job_status())
            return
        if self.path.startswith("/api/status"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.get_status())
            return
        return prev_do_get(self)

    def _full_do_post(self):
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
            req = json.loads(raw) if raw else {}
        except Exception:
            req = {}

        if self.path.startswith("/api/browse_song"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.browse_song_file())
            return

        if self.path.startswith("/api/browse_folder"):
            b = _get_shared_web_daw_bridge()
            title = req.get("title", "Select Folder")
            self._send_json(200, b.browse_folder(title))
            return

        if self.path.startswith("/api/mvsep/start"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.start_mvsep_separation(req))
            return

        if self.path.startswith("/api/mvsep/cancel"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.cancel_mvsep_separation())
            return

        if self.path.startswith("/api/mvsep/classic"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.launch_classic_mvsep_gui())
            return

        if self.path.startswith("/api/run_action"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.run_clean(req))
            return

        return prev_do_post(self)

    _HMSRequestHandler.do_GET = _full_do_get
    _HMSRequestHandler.do_POST = _full_do_post


_patch_rest_server_for_full_web_daw()




# === HMS_MVSEP_MULTIPASS_REST_PATCH ===
def _attach_multipass_routes_to_hms_rest():
    if "_HMSRequestHandler" not in globals():
        return

    _prev_get = _HMSRequestHandler.do_GET
    _prev_post = _HMSRequestHandler.do_POST

    def _mp_do_get(self):
        if self.path.startswith("/api/mvsep/multipass/status"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.get_mvsep_multipass_status())
            return
        if self.path.startswith("/api/mvsep/multipass/recipe"):
            b = _get_shared_web_daw_bridge()
            self._send_json(200, b.get_mvsep_multipass_recipe())
            return
        return _prev_get(self)

    def _mp_do_post(self):
        # Only consume self.rfile for our multipass routes so other handlers stay intact
        if self.path.startswith("/api/mvsep/multipass/"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
                req = json.loads(raw) if raw else {}
            except Exception:
                req = {}

            b = _get_shared_web_daw_bridge()
            if self.path.startswith("/api/mvsep/multipass/start"):
                self._send_json(200, b.start_mvsep_multipass(req))
                return
            if self.path.startswith("/api/mvsep/multipass/cancel"):
                self._send_json(200, b.cancel_mvsep_multipass())
                return
            self._send_json(404, {"status": "error", "message": f"Unknown multipass route: {self.path}"})
            return

        return _prev_post(self)

    _HMSRequestHandler.do_GET = _mp_do_get
    _HMSRequestHandler.do_POST = _mp_do_post


_attach_multipass_routes_to_hms_rest()






# === HMS_REST_BROWSE_ROUTES_PATCH ===
def _install_threadsafe_rest_browse_routes():
    if "_HMSRequestHandler" not in globals():
        return
    _prev_post = _HMSRequestHandler.do_POST

    def _browse_do_post(self):
        low_path = (self.path or "").lower()
        if any(k in low_path for k in ("/api/browse_song", "/api/browse_file", "/api/pick_file", "/api/mvsep/browse")):
            try:
                clen = int(self.headers.get("Content-Length", 0))
                if clen:
                    self.rfile.read(clen)
            except Exception:
                pass
            import hms_web_daw_launcher as _wl
            res = _wl.HMSWebDawBridge().browse_song_file()
            self._send_json(200, res)
            return
        if any(k in low_path for k in ("/api/browse_folder", "/api/pick_folder")):
            try:
                clen = int(self.headers.get("Content-Length", 0))
                if clen:
                    self.rfile.read(clen)
            except Exception:
                pass
            import hms_web_daw_launcher as _wl
            res = _wl.HMSWebDawBridge().browse_folder()
            self._send_json(200, res)
            return
        return _prev_post(self)

    _HMSRequestHandler.do_POST = _browse_do_post


_install_threadsafe_rest_browse_routes()
# === /HMS_REST_BROWSE_ROUTES_PATCH ===




# === HMS_LIVE_KEY_VERIFY_PATCH ===
def verify_live_api_connections(mvsep_token=None, gemini_key=None, log_callback=print):
    """
    Performs a live verification of the saved MVSep token and Gemini API key
    using the exact x-goog-api-key header and active model fallback chain used by the DAW.
    """
    import requests as _req
    import traceback as _tb

    log_callback("[RUN] Verifying live MVSep & Gemini API connections from DAW backend...")
    try:
        creds = load_ai_credentials(log_callback=lambda _: None)
        mv_val = str(mvsep_token if mvsep_token is not None else (creds.get("mvsep_api_token") or creds.get("mvsep_token") or "")).strip()
        gm_val = str(gemini_key if gemini_key is not None else creds.get("gemini_api_key", "")).strip()

        # 1. Check MVSep token presence & format (avoid heavy file upload during health test)
        mv_ok = len(mv_val) >= 12 and "PASTE" not in mv_val.upper()
        mv_detail = (
            f"Loaded ({mv_val[:4]}...{mv_val[-4:]}, {len(mv_val)} chars)"
            if mv_ok
            else ("Missing MVSep token" if not mv_val else f"Suspicious token length ({len(mv_val)} chars)")
        )

        # 2. Live Gemini API handshake across active Google AI Studio models
        gm_ok = False
        gm_model = ""
        gm_detail = ""
        if not gm_val or "YourActualKey" in gm_val or "PASTE_" in gm_val:
            gm_detail = "Missing or placeholder Gemini key in ~/.mvsep_hms_config.json"
        else:
            candidates = (
                "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            )
            payload = {"contents": [{"parts": [{"text": "Reply OK"}]}]}
            headers = {"x-goog-api-key": gm_val, "Content-Type": "application/json"}
            last_err = "No model responded"
            for model in candidates:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                try:
                    resp = _req.post(url, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 200:
                        gm_ok = True
                        gm_model = model
                        reply_txt = (
                            resp.json()
                            .get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "OK")
                            .strip()
                        )
                        gm_detail = f"Connected ({model}: {reply_txt[:30]})"
                        break
                    else:
                        # Extract concise Google RPC reason (e.g. ACCESS_TOKEN_TYPE_UNSUPPORTED)
                        try:
                            err_json = resp.json().get("error", {})
                            msg = err_json.get("message", resp.text[:160])
                            reason = ""
                            for d in err_json.get("details", []):
                                if isinstance(d, dict) and d.get("reason"):
                                    reason = f" [{d['reason']}]"
                                    break
                            last_err = f"HTTP {resp.status_code}{reason}: {msg}"
                        except Exception:
                            last_err = f"HTTP {resp.status_code}: {resp.text[:160]}"
                        # Stop retrying other models immediately on 401 auth failure
                        if resp.status_code == 401:
                            break
                except Exception as req_ex:
                    last_err = str(req_ex)

            if not gm_ok:
                gm_detail = last_err

        status = "ok" if (gm_ok and mv_ok) else ("partial" if (gm_ok or mv_ok) else "error")
        result = {
            "status": status,
            "gemini_ok": gm_ok,
            "gemini_model": gm_model,
            "gemini_detail": gm_detail,
            "mvsep_ok": mv_ok,
            "mvsep_detail": mv_detail,
        }
        log_callback(f"[{'SUCCESS' if gm_ok else 'ERROR'}] Gemini Live Check -> {gm_detail}")
        log_callback(f"[{'SUCCESS' if mv_ok else 'INFO'}] MVSep Token Check -> {mv_detail}")
        return result
    except Exception as ex:
        log_callback("[ERROR] verify_live_api_connections failed:")
        log_callback(_tb.format_exc())
        return {
            "status": "error",
            "gemini_ok": False,
            "gemini_model": "",
            "gemini_detail": str(ex),
            "mvsep_ok": False,
            "mvsep_detail": str(ex),
        }


def _patch_rest_for_verify_keys():
    """Exposes GET/POST /api/verify_keys on local 127.0.0.1:8765 REST server."""
    if "_HMSRequestHandler" not in globals():
        return
    cls = globals()["_HMSRequestHandler"]
    if getattr(cls, "_hms_verify_keys_patched", False):
        return
    orig_get = cls.do_GET
    orig_post = cls.do_POST

    def _get_with_verify(self):
        if self.path.split("?")[0] == "/api/verify_keys":
            self._send_json(200, verify_live_api_connections())
            return
        return orig_get(self)

    def _post_with_verify(self):
        if self.path.split("?")[0] == "/api/verify_keys":
            import json as _json
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = _json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except Exception:
                req = {}
            self._send_json(
                200,
                verify_live_api_connections(
                    mvsep_token=req.get("mvsep_api_token"),
                    gemini_key=req.get("gemini_api_key"),
                ),
            )
            return
        return orig_post(self)

    cls.do_GET = _get_with_verify
    cls.do_POST = _post_with_verify
    cls._hms_verify_keys_patched = True


_patch_rest_for_verify_keys()
# === END_HMS_LIVE_KEY_VERIFY_PATCH ===


if __name__ == "__main__":
    print("=== Running Isolated Verification for hms_ai_api_bridge.py ===")
    creds = load_ai_credentials()
    print(f"[INFO] Found config keys: {list(creds.keys())}")
    print(f"[INFO] Gemini Key Configured: {bool(creds.get('gemini_api_key'))}")
    print(f"[INFO] MVSep Token Configured: {bool(creds.get('mvsep_api_token'))}")
    srv, _ = start_local_hms_api_server(port=8765)
    if srv:
        time.sleep(0.3)
        r = requests.get("http://127.0.0.1:8765/health", timeout=5)
        print(f"[SUCCESS] Health Check Response ({r.status_code}): {r.json()}")
        srv.shutdown()


