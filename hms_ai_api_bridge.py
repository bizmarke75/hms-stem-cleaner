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
HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"

GEMINI_MODEL_CANDIDATES = [
    "gemini-4-hydrogen",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
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
        creds = load_ai_credentials(callback=lambda _: None)
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
            raw_text, used_model = _query_gemini_with_model_fallback(prompt_text, clean_key, callback)
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


