# Save as: C:\github\projects\hms-stem-cleaner\hms_mvsep_multipass.py
# Isolated Verification: python.exe C:\github\projects\hms-stem-cleaner\hms_mvsep_multipass.py --self-test

import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

API_CREATE_URL = "https://mvsep.com/api/separation/create"
API_GET_URL = "https://mvsep.com/api/separation/get"
REQUEST_TIMEOUT = (15, 120)
UPLOAD_SOCKET_TIMEOUT = 600.0
POLL_INTERVAL_SECONDS = 10
INTER_PASS_COOLDOWN_SECONDS = 3

# MVSep Registered Free Tier guardrails
PREMIUM_BLOCKED_SEP_TYPES = {26, 28, 30}   # Ensemble Vocals/Instrum, Ensemble 5-Stem, Ensemble All-In
PREMIUM_BLOCKED_FORMATS = {4, 5}           # 4 = WAV 32-bit float, 5 = FLAC 24-bit
FREE_ALLOWED_FORMATS = {0, 1, 2}           # 0 = MP3 320, 1 = WAV 16-bit, 2 = FLAC 16-bit
FREE_TIER_MAX_FILE_MB = 100.0

# Default HMS Multi-Pass Recipe (100% Registered Free Tier compatible)
HMS_FREE_MULTIPASS_RECIPE = {
    "pass1_vocals": {
        "label": "Pass 1: Vocals (BS Roformer 124-Band Standalone)",
        "sep_type": 40,
        "add_opt1": "171",  # Standalone 124-band BS Roformer (NOT Premium Ensemble 26)
        "input_source": "full_song",
        "keep_keywords": ["vocal"],
        "exclude_keywords": ["instrum", "no_vocal", "karaoke"],
    },
    "pass2_music": {
        "label": "Pass 2: Music (BS Roformer SW 6-Stems)",
        "sep_type": 63,
        "add_opt1": None,
        "input_source": "full_song",
        "keep_keywords": ["guitar", "piano", "other", "synth", "keys"],
        "exclude_keywords": ["vocal", "drum", "bass"],
    },
    "pass3_rhythm": {
        "label": "Pass 3: Rhythm (Demucs4 HT ft)",
        "sep_type": 20,
        "add_opt1": "0",  # htdemucs_ft
        "input_source": "full_song",
        "keep_keywords": ["drum", "bass"],
        "exclude_keywords": ["vocal", "other", "instrum"],
    },
    "pass4_drumsep": {
        "label": "Pass 4 (Optional): Kit Split (DrumSep Standalone)",
        "sep_type": 37,
        "add_opt1": None,
        "input_source": "isolated_drums",  # Automatically uses Pass 3/Pass 2 Drums WAV
        "keep_keywords": ["kick", "snare", "tom", "hh", "hihat", "hat", "ride", "crash", "cymbal"],
        "exclude_keywords": [],
    },
}


# ==============================================================================
# FUNCTION 1: FREE-TIER REQUEST VALIDATOR
# ==============================================================================
def validate_mvsep_free_tier_request(sep_type, output_format, file_path=None, free_tier_safe=True):
    """
    Validates an MVSep separation request against Registered Free Tier limits.

    Args:
        sep_type (int | str): MVSep separation algorithm ID.
        output_format (int | str): MVSep output encoding ID (0, 1, 2, 4, 5).
        file_path (str | None): Optional local audio file path to check against 100 MB cap.
        free_tier_safe (bool): When True, blocks Premium Ensemble models & 24/32-bit formats.

    Returns:
        dict: {"ok": bool, "reason": str, "warnings": list[str], "sep_type": int, "output_format": int}
    """
    warnings = []
    try:
        sep_id = int(sep_type)
        fmt_id = int(output_format)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "reason": f"Invalid sep_type ({sep_type!r}) or output_format ({output_format!r}).",
            "warnings": warnings,
        }

    if free_tier_safe:
        # 1. Block Premium Ensemble models
        if sep_id in PREMIUM_BLOCKED_SEP_TYPES:
            msg = (
                f"Blocked by Free-Tier Safe Mode: sep_type={sep_id} is a Premium Ensemble model. "
                "Use BS Roformer (40), BS Roformer SW (63), Demucs4 HT (20), or DrumSep (37)."
            )
            print(f"[ERROR] {msg}")
            return {"ok": False, "reason": msg, "warnings": warnings, "sep_type": sep_id, "output_format": fmt_id}

        # 2. Block 24-bit FLAC (5) and 32-bit WAV (4)
        if fmt_id in PREMIUM_BLOCKED_FORMATS or fmt_id not in FREE_ALLOWED_FORMATS:
            msg = (
                f"Blocked by Free-Tier Safe Mode: output_format={fmt_id} requires Premium credits. "
                "Switch to WAV 16-bit (1), FLAC 16-bit (2), or MP3 320 kbps (0)."
            )
            print(f"[ERROR] {msg}")
            return {"ok": False, "reason": msg, "warnings": warnings, "sep_type": sep_id, "output_format": fmt_id}

        # 3. Check local file size against MVSep's 100 MB Free-Tier upload cap
        if file_path and os.path.isfile(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            ext = os.path.splitext(file_path)[1].lower()
            if size_mb > FREE_TIER_MAX_FILE_MB:
                if ext == ".wav":
                    warnings.append(
                        f"Source WAV is {size_mb:.1f} MB (over 100 MB cap); lossless FLAC pre-compression will shrink it before upload."
                    )
                else:
                    msg = f"Blocked by Free-Tier Safe Mode: '{os.path.basename(file_path)}' is {size_mb:.1f} MB (max 100 MB on Free Tier)."
                    print(f"[ERROR] {msg}")
                    return {"ok": False, "reason": msg, "warnings": warnings, "sep_type": sep_id, "output_format": fmt_id}

    return {
        "ok": True,
        "reason": "Request verified Free-Tier Safe." if free_tier_safe else "Free-Tier Safe Mode disabled (Pro/Credits mode).",
        "warnings": warnings,
        "sep_type": sep_id,
        "output_format": fmt_id,
    }


# ==============================================================================
# FUNCTION 2: STAGE PASS STEMS & ISOLATE DUPLICATES OUTSIDE WORKSPACE
# ==============================================================================
def stage_pass_stems(
    song_workspace_dir,
    unused_root_dir,
    pass_id,
    downloaded_files,
    keep_keywords,
    exclude_keywords=None,
    log_callback=print,
):
    """
    Moves only the target stems for a given pass into song_workspace_dir and moves
    redundant stems into a sibling unused_root_dir so os.walk() inside HMS Stem
    Cleaner never double-sums overlapping vocals or drums across passes.
    """
    exclude_keywords = exclude_keywords or []
    kept = []
    archived = []
    isolated_drums = None

    try:
        os.makedirs(song_workspace_dir, exist_ok=True)
        pass_unused_dir = os.path.join(unused_root_dir, pass_id)
        os.makedirs(pass_unused_dir, exist_ok=True)

        # Expand any downloaded ZIP archives into a temporary list of individual audio files
        expanded_files = []
        for item in downloaded_files:
            if not item or not os.path.isfile(item):
                continue
            if item.lower().endswith(".zip"):
                extract_tmp = os.path.join(pass_unused_dir, "_zip_extract")
                os.makedirs(extract_tmp, exist_ok=True)
                with zipfile.ZipFile(item, "r") as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        safe_name = os.path.basename(member.filename)
                        if not safe_name:
                            continue
                        dst = os.path.join(extract_tmp, safe_name)
                        with zf.open(member) as src_f, open(dst, "wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)
                        expanded_files.append(dst)
                # Keep original zip out of the active workspace
                shutil.move(item, os.path.join(pass_unused_dir, os.path.basename(item)))
            else:
                expanded_files.append(item)

        for src_path in expanded_files:
            fname = os.path.basename(src_path)
            lower_name = fname.lower()

            # Check whether this stem matches the keeper rules for this pass
            matches_keep = (not keep_keywords) or any(k in lower_name for k in keep_keywords)
            matches_exclude = any(ex in lower_name for ex in exclude_keywords)

            if matches_keep and not matches_exclude:
                dest_path = os.path.join(song_workspace_dir, f"{pass_id}_{fname}")
                shutil.move(src_path, dest_path)
                kept.append(dest_path)
                log_callback(f"[SUCCESS] [{pass_id}] Kept stem -> {os.path.basename(dest_path)}")
                if "drum" in lower_name and pass_id != "pass4_drumsep":
                    isolated_drums = dest_path
            else:
                arch_path = os.path.join(pass_unused_dir, fname)
                shutil.move(src_path, arch_path)
                archived.append(arch_path)
                log_callback(f"[INFO] [{pass_id}] Archived duplicate stem -> {pass_id}/{fname}")

        return {"kept": kept, "archived": archived, "isolated_drums": isolated_drums}

    except Exception:
        log_callback(f"[ERROR] Failed staging stems for {pass_id}:")
        log_callback(traceback.format_exc())
        return {"kept": kept, "archived": archived, "isolated_drums": isolated_drums}


# ==============================================================================
# HELPER: LOSSLESS WAV -> FLAC PRE-COMPRESSION (KEEPS UPLOADS UNDER 100 MB CAP)
# ==============================================================================
def _prepare_upload_audio(file_path, log_callback=print):
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".wav" or size_mb <= 15.0:
        mime = "audio/flac" if ext == ".flac" else "audio/wav"
        return file_path, False, mime
    try:
        import soundfile as sf
        log_callback(f"[RUN] Pre-compressing {os.path.basename(file_path)} ({size_mb:.1f} MB WAV -> lossless FLAC)...")
        data, sr = sf.read(file_path, dtype="float32", always_2d=True)
        fd, tmp_flac = tempfile.mkstemp(suffix=".flac", prefix="hms_mp_upload_")
        os.close(fd)
        sf.write(tmp_flac, data, sr, format="FLAC", subtype="PCM_16")
        new_mb = os.path.getsize(tmp_flac) / (1024 * 1024)
        log_callback(f"[SUCCESS] Lossless upload ready: {size_mb:.1f} MB -> {new_mb:.1f} MB")
        return tmp_flac, True, "audio/flac"
    except Exception as ex:
        log_callback(f"[INFO] FLAC pre-compression skipped ({ex}); uploading original WAV.")
        return file_path, False, "audio/wav"


# ==============================================================================
# CLASS: SEQUENTIAL 1-AT-A-TIME MVSEP MULTI-PASS QUEUE RUNNER
# ==============================================================================
class SequentialMVSepQueueRunner:
    """
    Executes multi-pass MVSep cloud jobs strictly sequentially (max 1 concurrent job)
    so Registered Free Tier accounts never trigger concurrent-job rejections.
    """

    def __init__(self):
        self._job_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._state_lock = threading.Lock()
        self._state = {
            "running": False,
            "free_tier_safe": True,
            "current_pass_index": 0,
            "total_passes": 0,
            "current_pass_label": "",
            "song_workspace_dir": "",
            "error": "",
            "logs": [],
        }

    def _log(self, msg):
        print(msg)
        with self._state_lock:
            self._state["logs"].append(msg)
            # Cap in-memory UI log buffer at last 250 lines
            if len(self._state["logs"]) > 250:
                self._state["logs"] = self._state["logs"][-250:]

    def get_status(self):
        with self._state_lock:
            return dict(self._state, logs=list(self._state["logs"]))

    def cancel(self):
        self._cancel_event.set()
        self._log("[INFO] Cancellation requested. Stopping after active HTTP call returns.")
        return {"status": "ok", "message": "Cancellation signal sent."}

    def start_multipass(
        self,
        api_token,
        song_file_path,
        pass_ids=None,
        output_format=1,
        free_tier_safe=True,
        auto_clean=True,
        mix_style="auto",
    ):
        """
        Validates all requested passes upfront, acquires the single-job concurrency
        lock, and starts the sequential background worker thread.
        """
        selected_passes = pass_ids or ["pass1_vocals", "pass2_music", "pass3_rhythm"]
        if not api_token or not str(api_token).strip():
            return {"status": "error", "message": "Missing MVSep API token."}
        if not song_file_path or not os.path.isfile(song_file_path):
            return {"status": "error", "message": f"Audio file not found: {song_file_path}"}

        # Validate every requested pass BEFORE acquiring lock or uploading anything
        resolved_plan = []
        for pid in selected_passes:
            spec = HMS_FREE_MULTIPASS_RECIPE.get(pid)
            if not spec:
                return {"status": "error", "message": f"Unknown recipe pass ID: {pid}"}
            check = validate_mvsep_free_tier_request(
                sep_type=spec["sep_type"],
                output_format=output_format,
                file_path=song_file_path,
                free_tier_safe=free_tier_safe,
            )
            if not check["ok"]:
                return {"status": "error", "message": check["reason"]}
            resolved_plan.append((pid, spec, check["warnings"]))

        # Enforce strictly 1 concurrent MVSep cloud job at a time
        if not self._job_lock.acquire(blocking=False):
            msg = "MVSep Free-Tier Concurrency Lock: Another job is already running (max 1 concurrent job)."
            self._log(f"[ERROR] {msg}")
            return {"status": "error", "message": msg}

        self._cancel_event.clear()
        with self._state_lock:
            self._state.update({
                "running": True,
                "free_tier_safe": bool(free_tier_safe),
                "current_pass_index": 0,
                "total_passes": len(resolved_plan),
                "current_pass_label": "Initializing sequential queue...",
                "song_workspace_dir": "",
                "error": "",
                "logs": [f"[RUN] Queued {len(resolved_plan)} sequential MVSep pass(es) (Free-Tier Safe={free_tier_safe})."],
            })

        worker = threading.Thread(
            target=self._run_queue_worker,
            args=(api_token.strip(), song_file_path, resolved_plan, int(output_format), auto_clean, mix_style),
            daemon=True,
        )
        worker.start()
        return {"status": "ok", "total_passes": len(resolved_plan), "message": "Sequential multi-pass queue started."}

    def _execute_single_cloud_pass(self, api_token, audio_path, sep_type, output_format, add_opt1, download_dir):
        """Uploads, polls every 10s, and downloads all files for a single sequential pass."""
        upload_path, is_temp, mime = _prepare_upload_audio(audio_path, self._log)
        try:
            payload = {
                "api_token": api_token,
                "sep_type": str(sep_type),
                "output_format": str(output_format),
            }
            if add_opt1 is not None and str(add_opt1).strip() != "":
                payload["add_opt1"] = str(add_opt1)

            base = os.path.splitext(os.path.basename(audio_path))[0]
            ext = os.path.splitext(upload_path)[1].lower()
            with open(upload_path, "rb") as f:
                resp = requests.post(
                    API_CREATE_URL,
                    data=payload,
                    files={"audiofile": (f"{base}{ext}", f, mime)},
                    timeout=UPLOAD_SOCKET_TIMEOUT,
                )
            if resp.status_code != 200:
                raise RuntimeError(f"MVSep create HTTP {resp.status_code}: {resp.text[:300]}")
            res_json = resp.json()
            if not res_json.get("success"):
                raise RuntimeError(res_json.get("data", {}).get("message", "MVSep rejected separation creation."))

            job_hash = res_json["data"]["hash"]
            self._log(f"[SUCCESS] Job accepted (hash={job_hash}). Polling GPU queue every {POLL_INTERVAL_SECONDS}s...")

            while not self._cancel_event.is_set():
                if self._cancel_event.wait(POLL_INTERVAL_SECONDS):
                    return []
                poll = requests.get(API_GET_URL, params={"hash": job_hash}, timeout=REQUEST_TIMEOUT)
                if poll.status_code != 200:
                    self._log(f"[INFO] Poll warning HTTP {poll.status_code}; retrying...")
                    continue
                pj = poll.json()
                status = pj.get("status", "unknown")
                data_block = pj.get("data", {})
                if status == "waiting":
                    self._log(f"[INFO] Queue WAITING (order={data_block.get('current_order', '?')}, ahead={data_block.get('queue_count', '?')})")
                elif status in ("processing", "distributing", "merging"):
                    self._log(f"[INFO] GPU Status: {status.upper()}...")
                elif status == "done":
                    os.makedirs(download_dir, exist_ok=True)
                    saved = []
                    files_list = data_block.get("files") or []
                    if files_list:
                        for entry in files_list:
                            url = entry.get("url") or entry.get("link")
                            if not url:
                                continue
                            raw_name = entry.get("name") or unquote(urlparse(url).path.rsplit("/", 1)[-1])
                            safe_name = os.path.basename(str(raw_name).replace("\\", "/"))
                            out_path = os.path.join(download_dir, safe_name)
                            with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as dr:
                                dr.raise_for_status()
                                with open(out_path, "wb") as out_f:
                                    for chunk in dr.iter_content(chunk_size=16384):
                                        if chunk:
                                            out_f.write(chunk)
                            saved.append(out_path)
                    elif data_block.get("link"):
                        z_url = data_block["link"]
                        z_out = os.path.join(download_dir, "stems.zip")
                        with requests.get(z_url, stream=True, timeout=REQUEST_TIMEOUT) as dr:
                            dr.raise_for_status()
                            with open(z_out, "wb") as out_f:
                                for chunk in dr.iter_content(chunk_size=16384):
                                    if chunk:
                                        out_f.write(chunk)
                        saved.append(z_out)
                    return saved
                elif status in ("failed", "not_found"):
                    raise RuntimeError(data_block.get("message", f"MVSep job ended with status={status}"))
            return []
        finally:
            if is_temp and os.path.isfile(upload_path):
                try:
                    os.remove(upload_path)
                except OSError:
                    pass

    def _run_queue_worker(self, api_token, song_file_path, resolved_plan, output_format, auto_clean, mix_style):
        try:
            parent_dir = os.path.dirname(os.path.abspath(song_file_path))
            raw_base = os.path.splitext(os.path.basename(song_file_path))[0]
            clean_song = "".join("_" if c in '<>:"/\\|?* ' else c for c in raw_base).strip("_") or "MVSep_Song"

            workspace_dir = os.path.join(parent_dir, f"{clean_song}_Stems")
            unused_sibling_dir = os.path.join(parent_dir, f"{clean_song}_Stems_Unused_Passes")
            os.makedirs(workspace_dir, exist_ok=True)
            isolated_drums_path = None

            with self._state_lock:
                self._state["song_workspace_dir"] = workspace_dir

            for idx, (pid, spec, warns) in enumerate(resolved_plan, start=1):
                if self._cancel_event.is_set():
                    self._log("[INFO] Sequential queue stopped by user cancellation.")
                    return

                with self._state_lock:
                    self._state["current_pass_index"] = idx
                    self._state["current_pass_label"] = spec["label"]

                self._log("=" * 65)
                self._log(f"[RUN] Starting {idx}/{len(resolved_plan)}: {spec['label']}")
                for w in warns:
                    self._log(f"[INFO] {w}")

                # Pass 4 (DrumSep) feeds the isolated Drums stem rather than the full mix
                pass_input = song_file_path
                if spec.get("input_source") == "isolated_drums":
                    if isolated_drums_path and os.path.isfile(isolated_drums_path):
                        pass_input = isolated_drums_path
                        self._log(f"[INFO] Feeding isolated Drums stem into DrumSep: {os.path.basename(pass_input)}")
                    else:
                        self._log("[ERROR] Skipping Pass 4 DrumSep: no isolated Drums WAV from earlier passes.")
                        continue

                tmp_dl_dir = os.path.join(unused_sibling_dir, f"_dl_{pid}")
                downloaded = self._execute_single_cloud_pass(
                    api_token=api_token,
                    audio_path=pass_input,
                    sep_type=spec["sep_type"],
                    output_format=output_format,
                    add_opt1=spec.get("add_opt1"),
                    download_dir=tmp_dl_dir,
                )
                if self._cancel_event.is_set():
                    return

                staged = stage_pass_stems(
                    song_workspace_dir=workspace_dir,
                    unused_root_dir=unused_sibling_dir,
                    pass_id=pid,
                    downloaded_files=downloaded,
                    keep_keywords=spec["keep_keywords"],
                    exclude_keywords=spec["exclude_keywords"],
                    log_callback=self._log,
                )
                if staged.get("isolated_drums"):
                    isolated_drums_path = staged["isolated_drums"]

                # If DrumSep succeeded, archive the unsplit Drums stem so HMS doesn't double-sum drums
                if pid == "pass4_drumsep" and staged.get("kept") and isolated_drums_path and os.path.isfile(isolated_drums_path):
                    shutil.move(isolated_drums_path, os.path.join(unused_sibling_dir, os.path.basename(isolated_drums_path)))
                    self._log("[INFO] Archived unsplit Drums WAV (replaced by DrumSep kit stems).")

                if idx < len(resolved_plan) and not self._cancel_event.is_set():
                    self._log(f"[INFO] Free-Tier 1-job cooldown ({INTER_PASS_COOLDOWN_SECONDS}s) before Pass {idx + 1}...")
                    self._cancel_event.wait(INTER_PASS_COOLDOWN_SECONDS)

            self._log(f"[SUCCESS] All sequential MVSep passes finished! Stems ready in: {workspace_dir}")

            # Optional automatic HMS VST3 Clean + 24-Bit Master Mixdown
            if auto_clean and not self._cancel_event.is_set():
                self._log("[RUN] Triggering HMS Stem Cleaner VST3 Auto-Clean + 24-Bit Master...")
                try:
                    import hms_stem_cleaner_app as hms
                    hms.execute_stem_cleanup(
                        source_dir=workspace_dir,
                        dest_root=None,
                        dry_run=False,
                        move_source_files=False,
                        render_master=True,
                    )
                    self._log("[SUCCESS] HMS Auto-Clean & 24-Bit Master Mixdown complete!")
                except Exception:
                    self._log("[ERROR] Post-pass HMS Auto-Clean failed:")
                    self._log(traceback.format_exc())

        except Exception as ex:
            with self._state_lock:
                self._state["error"] = str(ex)
            self._log(f"[ERROR] Sequential multi-pass queue halted: {ex}")
            self._log(traceback.format_exc())
        finally:
            with self._state_lock:
                self._state["running"] = False
            self._job_lock.release()


# Shared singleton instance used by both PyWebView and REST API (:8765)
SHARED_MULTIPASS_RUNNER = SequentialMVSepQueueRunner()


# ==============================================================================
# ISOLATED VERIFICATION TEST DRIVER (--self-test)
# ==============================================================================
if __name__ == "__main__":
    print("=== Running Isolated Verification for hms_mvsep_multipass.py ===")
    try:
        # Test 1: Premium Ensemble model MUST be blocked in Free-Tier Safe mode
        t1 = validate_mvsep_free_tier_request(sep_type=26, output_format=1, free_tier_safe=True)
        assert not t1["ok"], "Expected sep_type=26 to be blocked!"
        print(f"[SUCCESS] Test 1 Passed (Blocked Ensemble 26): {t1['reason']}")

        # Test 2: 24-bit FLAC (5) and 32-bit WAV (4) MUST be blocked in Free-Tier Safe mode
        t2a = validate_mvsep_free_tier_request(sep_type=63, output_format=5, free_tier_safe=True)
        t2b = validate_mvsep_free_tier_request(sep_type=63, output_format=4, free_tier_safe=True)
        assert not t2a["ok"] and not t2b["ok"], "Expected 24-bit/32-bit formats to be blocked!"
        print("[SUCCESS] Test 2 Passed (Blocked FLAC 24-bit & WAV 32-bit).")

        # Test 3: All 4 HMS recipe passes with WAV 16-bit (1) MUST pass Free-Tier validation
        for pid, spec in HMS_FREE_MULTIPASS_RECIPE.items():
            chk = validate_mvsep_free_tier_request(spec["sep_type"], output_format=1, free_tier_safe=True)
            assert chk["ok"], f"Expected {pid} to pass Free-Tier validation!"
        print("[SUCCESS] Test 3 Passed (All 4 HMS recipe passes verified Free-Tier Safe with WAV 16-bit).")

        # Test 4: Sibling stem staging isolates duplicates outside <Song>_Stems
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "TestSong_Stems")
            unused = os.path.join(tmp, "TestSong_Stems_Unused_Passes")
            dl_dir = os.path.join(tmp, "dl")
            os.makedirs(dl_dir, exist_ok=True)
            fake_files = []
            for fn in ("vocals.wav", "guitar.wav", "drums.wav", "bass.wav"):
                p = os.path.join(dl_dir, fn)
                with open(p, "wb") as f:
                    f.write(b"RIFFtest")
                fake_files.append(p)
            res = stage_pass_stems(ws, unused, "pass3_rhythm", fake_files, ["drum", "bass"], ["vocal", "other"])
            assert len(res["kept"]) == 2 and len(res["archived"]) == 2 and res["isolated_drums"]
            print(f"[SUCCESS] Test 4 Passed (Kept 2 Rhythm stems, isolated 2 duplicates outside workspace).")

        # Test 5: Concurrency lock rejects overlapping 2nd job immediately
        runner = SequentialMVSepQueueRunner()
        assert runner._job_lock.acquire(blocking=False)
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                dummy_wav = tf.name
            dup = runner.start_multipass("dummy_token", dummy_wav, ["pass1_vocals"], output_format=1, free_tier_safe=True)
            assert dup["status"] == "error" and "Concurrency Lock" in dup["message"]
            print("[SUCCESS] Test 5 Passed (1-Concurrent-Job Free-Tier Lock enforced).")
        finally:
            runner._job_lock.release()
            if os.path.isfile(dummy_wav):
                os.remove(dummy_wav)

        print("\n[SUCCESS] ALL 5 ISOLATED TESTS PASSED! Ready for Step 2 (Web-DAW Recipe Card UI & Bridge Patch).")
    except Exception:
        print("[ERROR] Isolated verification failed:")
        print(traceback.format_exc())
        sys.exit(1)