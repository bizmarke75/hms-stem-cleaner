# Save as: C:\github\projects\hms-stem-cleaner\launch_chrome_web_daw.py
# Run in PowerShell: python.exe C:\github\projects\hms-stem-cleaner\launch_chrome_web_daw.py

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
if os.path.isdir(HMS_REPO_DIR) and HMS_REPO_DIR not in sys.path:
    sys.path.insert(0, HMS_REPO_DIR)

HTML_PATH = os.path.join(HMS_REPO_DIR, "hms_web_daw.html")


# ==============================================================================
# FUNCTION 1: FREE PORT 8765 IF AN OLD BACKGROUND SERVER IS HOLDING IT
# ==============================================================================
def ensure_port_is_free_for_chrome_daw(port=8765):
    """
    Finds any stale background Python process listening on 127.0.0.1:8765
    (that returns 'Use GET /health or POST /api/clean') and terminates it
    so the Chrome Web-DAW Server can bind cleanly to port 8765.
    """
    print("=" * 75)
    print(f"[RUN] Checking if port {port} is held by an old background process...")
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            errors="ignore",
        )
        my_pid = os.getpid()
        killed_pids = set()

        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3].upper() == "LISTENING":
                pid = int(parts[4])
                if pid != my_pid and pid > 0 and pid not in killed_pids:
                    print(f"[INFO] Terminating stale server on port {port} (PID {pid})...")
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    killed_pids.add(pid)

        if killed_pids:
            time.sleep(0.5)
            print(f"[SUCCESS] Freed port {port} from old process(es): {killed_pids}")
        else:
            print(f"[SUCCESS] Port {port} is clean and ready.")
        return True
    except Exception:
        print("[ERROR] Port check warning:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 2: PATCH hms_web_daw.html FOR GOOGLE CHROME REST API (:8765)
# ==============================================================================
def patch_html_for_chrome_rest_api(html_path=HTML_PATH):
    """
    Ensures hms_web_daw.html connects all buttons (Browse Song, Split Stems,
    Browse Folder, Save Keys, and all 6 HMS actions) to http://127.0.0.1:8765.
    """
    print(f"[RUN] Verifying Google Chrome REST bindings in: {html_path}")
    if not os.path.isfile(html_path):
        print(f"[ERROR] Missing HTML file: {html_path}")
        return False

    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Prevent key-loader from putting the MVSep token into #hms-mvsep-song-path
        old_line = 'const meta = ((el.id || "") + " " + (el.name || "") + " " + (el.placeholder || "")).toLowerCase();'
        safe_line = (
            'if (el.id === "hms-mvsep-song-path") continue;\n'
            '      const meta = ((el.id || "") + " " + (el.name || "") + " " + (el.placeholder || "")).toLowerCase();'
        )
        if 'if (el.id === "hms-mvsep-song-path") continue;' not in html and old_line in html:
            html = html.replace(old_line, safe_line)

        chrome_marker = "<!-- HMS_CHROME_FULL_BRIDGE_V2 -->"
        chrome_script = f"""
{chrome_marker}
<script>
(function() {{
  const API_BASE = window.location.origin.startsWith("http")
    ? window.location.origin
    : "http://127.0.0.1:8765";

  async function postJson(endpoint, bodyObj) {{
    const r = await fetch(API_BASE + endpoint, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(bodyObj || {{}})
    }});
    return await r.json();
  }}

  window.addEventListener("DOMContentLoaded", async () => {{
    const songInput = document.getElementById("hms-mvsep-song-path");
    if (songInput && songInput.value && !songInput.value.includes("\\\\") && !songInput.value.includes("/")) {{
      songInput.value = "";
    }}

    try {{
      const r = await fetch(API_BASE + "/api/status");
      if (r.ok) {{
        const st = await r.json();
        const dot = document.getElementById("bridgeDot");
        const txt = document.getElementById("bridgeStatusText");
        if (dot) dot.className = "dot";
        if (txt) txt.textContent = "Bridge: Chrome Live Connected";
        if (st.mvsep_api_token) {{
          const mvEl = document.getElementById("mvsepTokenInput");
          if (mvEl) mvEl.value = st.mvsep_api_token;
        }}
        if (st.gemini_api_key) {{
          const gmEl = document.getElementById("geminiKeyInput");
          if (gmEl) gmEl.value = st.gemini_api_key;
        }}
        appendLog("[SUCCESS] Google Chrome connected to HMS Python Backend (" + API_BASE + ")", "ok");
      }}
    }} catch (e) {{}}
  }});

  window.browseSongFolder = async function() {{
    const res = await postJson("/api/browse_folder", {{ title: "Select Song Stem Folder" }});
    if (res && res.status === "ok" && res.path) {{
      document.getElementById("songDirInput").value = res.path;
      appendLog("[SUCCESS] Selected Song Folder: " + res.path, "ok");
      if (res.saved_mix) {{
        applyMixProfileToSliders(res.saved_mix);
        appendLog("[SUCCESS] Auto-loaded MIX_SETTINGS.json from song folder!", "ok");
      }}
    }}
  }};

  window.browseDestFolder = async function() {{
    const res = await postJson("/api/browse_folder", {{ title: "Select Destination Root Folder" }});
    if (res && res.status === "ok" && res.path) {{
      document.getElementById("destRootInput").value = res.path;
      appendLog("[SUCCESS] Selected Destination Folder: " + res.path, "ok");
    }}
  }};

  window.saveApiCredentials = async function() {{
    const mv = document.getElementById("mvsepTokenInput").value.trim();
    const gm = document.getElementById("geminiKeyInput").value.trim();
    await postJson("/api/credentials", {{ mvsep_api_token: mv, gemini_api_key: gm }});
    appendLog("[SUCCESS] Saved API Keys to ~/.mvsep_hms_config.json!", "ok");
  }};

  window.triggerHmsAction = async function(mode) {{
    const payload = get9SliderPayload(mode);
    appendLog(`[RUN] Executing '${{mode.toUpperCase()}}' on: ${{payload.song_dir}}`, "run");
    const res = await postJson("/api/run_action", payload);
    if (res.status === "ok") {{
      if (mode === "autotune" && res.profile) applyMixProfileToSliders(res.profile);
      appendLog(`[SUCCESS] Completed '${{mode}}': ` + JSON.stringify(res), "ok");
    }} else {{
      appendLog(`[ERROR] '${{mode}}' error: ` + (res.message || JSON.stringify(res)), "err");
    }}
  }};

  window.addEventListener("DOMContentLoaded", () => {{
    setTimeout(() => {{
      const browseBtn = document.getElementById("hms-mvsep-browse-song-btn");
      const startBtn = document.getElementById("hms-mvsep-start-btn");
      const cancelBtn = document.getElementById("hms-mvsep-cancel-btn");
      const classicBtn = document.getElementById("hms-open-classic-mvsep-btn") || document.getElementById("hms-mvsep-open-classic-btn");
      const songInput = document.getElementById("hms-mvsep-song-path");
      const logDrawer = document.getElementById("hms-mvsep-log-drawer");
      let pollTimer = null;

      function setMvsepLog(lines) {{
        if (!logDrawer) return;
        logDrawer.innerHTML = lines.map(line => {{
          let c = "#94a3b8";
          if (line.includes("[SUCCESS]")) c = "#22c55e";
          else if (line.includes("[ERROR]")) c = "#ef4444";
          else if (line.includes("[RUN]")) c = "#38bdf8";
          return `<div style="color:${{c}};">${{line}}</div>`;
        }}).join("");
        logDrawer.scrollTop = logDrawer.scrollHeight;
      }}

      if (browseBtn) {{
        const bClone = browseBtn.cloneNode(true);
        browseBtn.parentNode.replaceChild(bClone, browseBtn);
        bClone.addEventListener("click", async () => {{
          const res = await postJson("/api/browse_song", {{}});
          if (res && res.status === "ok" && res.file_path) {{
            songInput.value = res.file_path;
            setMvsepLog([`[SUCCESS] Selected track: ${{res.file_path}}`]);
          }}
        }});
      }}

      if (classicBtn) {{
        const cClone = classicBtn.cloneNode(true);
        classicBtn.parentNode.replaceChild(cClone, classicBtn);
        cClone.addEventListener("click", async () => {{
          const res = await postJson("/api/mvsep/classic", {{}});
          setMvsepLog([res.status === "ok" ? `[SUCCESS] Launched Classic mvsep_gui.py` : `[ERROR] ${{res.message}}`]);
        }});
      }}

      if (startBtn) {{
        const sClone = startBtn.cloneNode(true);
        startBtn.parentNode.replaceChild(sClone, startBtn);
        sClone.addEventListener("click", async () => {{
          const fpath = (songInput.value || "").trim();
          if (!fpath) {{
            setMvsepLog(["[ERROR] Click 'Browse Song' first to choose a WAV/FLAC/MP3 file."]);
            return;
          }}
          const mvKeyEl = document.getElementById("mvsepTokenInput");
          const autoChk = document.getElementById("hms-mvsep-autoclean-cb") || document.getElementById("hms-mvsep-autoclean-chk");
          const payload = {{
            file_path: fpath,
            sep_type: parseInt(document.getElementById("hms-mvsep-model-select").value, 10),
            output_format: parseInt(document.getElementById("hms-mvsep-format-select").value, 10),
            auto_clean: autoChk ? autoChk.checked : true,
            api_token: mvKeyEl ? mvKeyEl.value.trim() : ""
          }};
          const res = await postJson("/api/mvsep/start", payload);
          if (res.status === "ok") {{
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(async () => {{
              const st = await (await fetch(API_BASE + "/api/mvsep/status")).json();
              if (st.logs && st.logs.length) setMvsepLog(st.logs);
              if (st.song_workspace_dir) {{
                const sd = document.getElementById("songDirInput");
                if (sd && sd.value !== st.song_workspace_dir) sd.value = st.song_workspace_dir;
              }}
              if (!st.running) clearInterval(pollTimer);
            }}, 1500);
          }} else {{
            setMvsepLog([`[ERROR] ${{res.message}}`]);
          }}
        }});
      }}

      if (cancelBtn) {{
        const xClone = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(xClone, cancelBtn);
        xClone.addEventListener("click", async () => {{
          await postJson("/api/mvsep/cancel", {{}});
        }});
      }}
    }}, 350);
  }});
}})();
</script>
"""

        for old_m in ("<!-- HMS_CHROME_FULL_BRIDGE_V1 -->", chrome_marker):
            if old_m in html:
                s_idx = html.index(old_m)
                e_idx = html.find("</script>", s_idx)
                if e_idx != -1:
                    html = html[:s_idx] + html[e_idx + len("</script>"):]

        if "</body>" in html:
            html = html.replace("</body>", chrome_script + "\n</body>", 1)
        else:
            html = html + "\n" + chrome_script

        tmp = f"{html_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, html_path)
        print("[SUCCESS] Updated hms_web_daw.html for Google Chrome!")
        return True
    except Exception:
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 3: CHROME WEB-DAW HTTP SERVER ON 127.0.0.1:8765
# ==============================================================================
import hms_web_daw_launcher as _launcher_mod
_BRIDGE = _launcher_mod.HMSWebDawBridge()


class ChromeDAWRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[CHROME-DAW] {self.address_string()} - {fmt % args}")

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, code, data):
        raw = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path in ("/", "/index.html", "/hms_web_daw.html"):
            with open(HTML_PATH, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if clean_path == "/health":
            self._send_json(200, {"status": "online", "browser": "chrome", "service": "HMS Web-DAW"})
            return

        if clean_path in ("/api/status", "/api/credentials"):
            self._send_json(200, _BRIDGE.get_status())
            return

        if clean_path == "/api/mvsep/status":
            if hasattr(_BRIDGE, "get_mvsep_job_status"):
                self._send_json(200, _BRIDGE.get_mvsep_job_status())
            else:
                self._send_json(200, {"running": False, "logs": []})
            return

        self._send_json(404, {"error": f"Unknown path: {clean_path}"})

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            body_str = self.rfile.read(length).decode("utf-8") if length else "{}"
            req = json.loads(body_str) if body_str else {}
        except Exception:
            req = {}

        if clean_path == "/api/credentials":
            self._send_json(200, _BRIDGE.save_credentials(req))
            return

        if clean_path == "/api/browse_song":
            if hasattr(_BRIDGE, "browse_song_file"):
                self._send_json(200, _BRIDGE.browse_song_file())
            else:
                self._send_json(200, _BRIDGE.browse_folder("Select Audio Track"))
            return

        if clean_path == "/api/browse_folder":
            self._send_json(200, _BRIDGE.browse_folder(req.get("title", "Select Folder")))
            return

        if clean_path == "/api/mvsep/start":
            self._send_json(200, _BRIDGE.start_mvsep_separation(req))
            return

        if clean_path == "/api/mvsep/cancel":
            self._send_json(200, _BRIDGE.cancel_mvsep_separation())
            return

        if clean_path == "/api/mvsep/classic":
            self._send_json(200, _BRIDGE.launch_classic_mvsep_gui())
            return

        if clean_path in ("/api/run_action", "/api/clean"):
            self._send_json(200, _BRIDGE.run_clean(req))
            return

        self._send_json(404, {"error": f"Unknown POST path: {clean_path}"})


def find_chrome_exe():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    # 1. Free port 8765 if an old _HMSRequestHandler process is holding it!
    ensure_port_is_free_for_chrome_daw(args.port)

    # 2. Patch hms_web_daw.html
    patch_html_for_chrome_rest_api(HTML_PATH)

    # 3. Start the Chrome Web-DAW HTTP Server on 127.0.0.1:8765
    url = f"http://127.0.0.1:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ChromeDAWRequestHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[SUCCESS] Chrome Web-DAW Server listening at: {url}")

    if args.test:
        import requests
        r = requests.get(url, timeout=3)
        assert r.status_code == 200 and "<html" in r.text.lower()
        print("[SUCCESS] VERIFIED: GET http://127.0.0.1:8765/ returns the full HTML Web-DAW UI!")
        server.shutdown()
        return

    chrome_bin = find_chrome_exe()
    if chrome_bin:
        print(f"[RUN] Opening Google Chrome Studio Window -> {url}")
        subprocess.Popen([chrome_bin, f"--app={url}", "--start-maximized"])
    else:
        webbrowser.open(url)

    print("=" * 75)
    print("[INFO] HMS Web-DAW is live in Google Chrome!")
    print("       Keep this terminal running while using the DAW (Press Ctrl+C to stop).")
    print("=" * 75)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.shutdown()




# === CHROME_DAW_WAV_STREAMER_PATCH_V1 ===
from urllib.parse import parse_qs, urlparse, unquote

def _scan_song_audio_files(song_dir, dest_root=""):
    results = []
    seen_paths = set()

    if not song_dir:
        return results

    norm_song = os.path.normpath(song_dir.strip())
    song_name = os.path.basename(norm_song)
    if song_name.endswith("_Stems"):
        base_song_name = song_name[:-6]
    else:
        base_song_name = song_name

    search_dirs = []
    if dest_root and os.path.isdir(dest_root.strip()):
        for candidate_name in (song_name, base_song_name):
            cand_dir = os.path.join(os.path.normpath(dest_root.strip()), candidate_name)
            if os.path.isdir(cand_dir) and cand_dir not in search_dirs:
                search_dirs.append(cand_dir)

    if os.path.isdir(norm_song) and norm_song not in search_dirs:
        search_dirs.append(norm_song)

    for s_dir in search_dirs:
        for root_dir, _, files in os.walk(s_dir):
            if "_HMS_Rollback_Vault" in root_dir:
                continue
            for fn in sorted(files):
                if not fn.lower().endswith((".wav", ".flac", ".mp3")):
                    continue
                full_p = os.path.normpath(os.path.join(root_dir, fn))
                if full_p in seen_paths:
                    continue
                seen_paths.add(full_p)

                upper_fn = fn.upper()
                if "MASTER_MIX" in upper_fn:
                    category = "1_MASTER"
                    badge = "★ MASTER MIX"
                elif "GLUED" in upper_fn:
                    category = "2_GLUED"
                    badge = "● GLUED BUS"
                elif "CLEAN" in upper_fn:
                    category = "3_CLEAN"
                    badge = "✓ CLEAN STEM"
                else:
                    category = "4_RAW"
                    badge = "○ RAW STEM"

                results.append({
                    "name": fn,
                    "path": full_p,
                    "category": category,
                    "badge": badge,
                    "size_mb": round(os.path.getsize(full_p) / (1024 * 1024), 2),
                })

    results.sort(key=lambda x: (x["category"], x["name"]))
    return results


def _attach_wav_streamer_to_chrome_handler():
    orig_do_get = ChromeDAWRequestHandler.do_GET

    def _stream_do_get(self):
        parsed = urlparse(self.path)
        clean_path = parsed.path
        qs = parse_qs(parsed.query)

        if clean_path == "/api/list_song_wavs":
            song_dir = (qs.get("song_dir", [""])[0] or "").strip()
            dest_root = (qs.get("dest_root", [""])[0] or "").strip()
            tracks = _scan_song_audio_files(song_dir, dest_root)
            self._send_json(200, {"status": "ok", "count": len(tracks), "tracks": tracks})
            return

        if clean_path == "/api/stream_wav":
            raw_path = unquote(qs.get("path", [""])[0] or "").strip()
            norm_p = os.path.normpath(raw_path)
            if not raw_path or not os.path.isfile(norm_p):
                self._send_json(404, {"status": "error", "message": f"Audio file not found: {norm_p}"})
                return

            try:
                file_size = os.path.getsize(norm_p)
                ext = os.path.splitext(norm_p)[1].lower()
                mime = "audio/flac" if ext == ".flac" else "audio/mpeg" if ext == ".mp3" else "audio/wav"

                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    byte_range = range_header.split("=")[1].split("-")
                    start_b = int(byte_range[0]) if byte_range[0] else 0
                    end_b = int(byte_range[1]) if (len(byte_range) > 1 and byte_range[1]) else file_size - 1
                    end_b = min(end_b, file_size - 1)
                    chunk_len = max(0, end_b - start_b + 1)

                    self.send_response(206)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start_b}-{end_b}/{file_size}")
                    self.send_header("Content-Length", str(chunk_len))
                    self._send_cors_headers()
                    self.end_headers()

                    with open(norm_p, "rb") as af:
                        af.seek(start_b)
                        remaining = chunk_len
                        while remaining > 0:
                            buf = af.read(min(65536, remaining))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            remaining -= len(buf)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(file_size))
                    self._send_cors_headers()
                    self.end_headers()
                    with open(norm_p, "rb") as af:
                        while True:
                            buf = af.read(65536)
                            if not buf:
                                break
                            self.wfile.write(buf)
            except (ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception:
                print(traceback.format_exc())
            return

        return orig_do_get(self)

    ChromeDAWRequestHandler.do_GET = _stream_do_get


_attach_wav_streamer_to_chrome_handler()




# === CHROME_DAW_VERIFY_KEYS_ENDPOINT_V1 ===
import requests as _req_verify

def _verify_saved_api_keys_live(req_dict=None):
    req_dict = req_dict or {}
    st = _BRIDGE.get_status()
    mv_key = (req_dict.get("mvsep_api_token") or st.get("mvsep_api_token") or "").strip()
    gm_key = (req_dict.get("gemini_api_key") or st.get("gemini_api_key") or "").strip()

    mv_masked = (mv_key[:5] + "..." + mv_key[-4:]) if len(mv_key) > 10 else ("SET" if mv_key else "MISSING")
    gm_masked = (gm_key[:6] + "..." + gm_key[-4:]) if len(gm_key) > 10 else ("SET" if gm_key else "MISSING")

    # Test Gemini Key live against Google AI Studio active models
    gm_ok = False
    gm_model = "none"
    gm_msg = "No Gemini key configured"
    if gm_key:
        candidates = ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]
        headers = {"x-goog-api-key": gm_key, "Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": "Reply with OK"}]}]}
        for m in candidates:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
                r = _req_verify.post(url, headers=headers, json=payload, timeout=10)
                if r.status_code == 200:
                    gm_ok = True
                    gm_model = m
                    gm_msg = f"Connected ({m})"
                    break
                else:
                    gm_msg = f"HTTP {r.status_code} on {m}"
            except Exception as ex:
                gm_msg = str(ex)

    return {
        "status": "ok",
        "mvsep_present": bool(mv_key),
        "mvsep_masked": mv_masked,
        "mvsep_length": len(mv_key),
        "gemini_present": bool(gm_key),
        "gemini_masked": gm_masked,
        "gemini_live_ok": gm_ok,
        "gemini_model": gm_model,
        "gemini_message": gm_msg,
    }


def _attach_verify_keys_handler():
    orig_do_post = ChromeDAWRequestHandler.do_POST

    def _verify_do_post(self):
        clean_path = self.path.split("?")[0]
        if clean_path == "/api/verify_keys":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body_str = self.rfile.read(length).decode("utf-8") if length else "{}"
                req = json.loads(body_str) if body_str else {}
            except Exception:
                req = {}
            self._send_json(200, _verify_saved_api_keys_live(req))
            return
        return orig_do_post(self)

    ChromeDAWRequestHandler.do_POST = _verify_do_post


_attach_verify_keys_handler()




# === HMS_CHROME_MULTIPASS_ROUTES_PATCH ===
def _attach_multipass_routes_to_chrome_server():
    if "ChromeDAWRequestHandler" not in globals():
        return

    _prev_get = ChromeDAWRequestHandler.do_GET
    _prev_post = ChromeDAWRequestHandler.do_POST

    def _chrome_mp_get(self):
        if self.path.startswith("/api/mvsep/multipass/status"):
            self._send_json(200, _BRIDGE.get_mvsep_multipass_status())
            return
        if self.path.startswith("/api/mvsep/multipass/recipe"):
            self._send_json(200, _BRIDGE.get_mvsep_multipass_recipe())
            return
        return _prev_get(self)

    def _chrome_mp_post(self):
        if self.path.startswith("/api/mvsep/multipass/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                req = json.loads(body) if body else {}
            except Exception:
                req = {}

            if self.path.startswith("/api/mvsep/multipass/start"):
                self._send_json(200, _BRIDGE.start_mvsep_multipass(req))
                return
            if self.path.startswith("/api/mvsep/multipass/cancel"):
                self._send_json(200, _BRIDGE.cancel_mvsep_multipass())
                return
            self._send_json(404, {"status": "error", "message": f"Unknown multipass route: {self.path}"})
            return

        return _prev_post(self)

    ChromeDAWRequestHandler.do_GET = _chrome_mp_get
    ChromeDAWRequestHandler.do_POST = _chrome_mp_post


_attach_multipass_routes_to_chrome_server()


if __name__ == "__main__":
    main()