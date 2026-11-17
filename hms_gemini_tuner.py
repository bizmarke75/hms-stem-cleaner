# Save as: C:\github\projects\hms-stem-cleaner\hms_gemini_tuner.py
# CLI Usage (Stem Folder) : python.exe C:\github\projects\hms-stem-cleaner\hms_gemini_tuner.py --target "C:\path\to\Song_Stems"
# CLI Usage (Master WAV)  : python.exe C:\github\projects\hms-stem-cleaner\hms_gemini_tuner.py --target "C:\path\to\Song_MASTER_MIX.wav"

import argparse
import base64
import io
import json
import os
import re
import sys
import traceback
import wave
from pathlib import Path
import numpy as np
import requests

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
if HMS_REPO_DIR not in sys.path and os.path.isdir(HMS_REPO_DIR):
    sys.path.insert(0, HMS_REPO_DIR)

try:
    from pedalboard import Pedalboard, HighpassFilter, PeakFilter, Compressor, Limiter
    from pedalboard.io import AudioFile
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

CONFIG_FILE_PATH = Path.home() / ".mvsep_hms_config.json"


def _classify_stem_bus(raw_filename, parent_folder_name=""):
    """Routes a filename into 'Vocals', 'Rhythm', or 'Music' to match HMS Stem Cleaner."""
    lower_name = os.path.splitext(raw_filename)[0].lower()
    lower_parent = parent_folder_name.lower()

    if any(k in lower_name for k in ["vocal", "vox", "lead", "backing", "choir", "acapella"]) or lower_parent == "vocals":
        return "Vocals"
    if any(k in lower_name for k in ["drum", "bass", "kick", "snare", "perc", "rhythm", "sub"]) or lower_parent == "rhythm":
        return "Rhythm"
    return "Music"


def _read_wav_stereo_float32(wav_path):
    """Reads a WAV file into a (2, frames) float32 numpy array and returns (buffer, samplerate)."""
    if HAS_PEDALBOARD:
        with AudioFile(wav_path) as af:
            sr = int(af.samplerate)
            buf = af.read(af.frames)
    else:
        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            raw_bytes = wf.readframes(wf.getnframes())
            if sampwidth == 2:
                data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            elif sampwidth == 4:
                data = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                data = np.zeros(sr, dtype=np.float32)
            buf = data.reshape(-1, n_ch).T

    if buf.ndim == 1 or buf.shape[0] == 1:
        buf = np.vstack([buf, buf])
    elif buf.shape[0] > 2:
        buf = buf[:2, :]
    return np.ascontiguousarray(buf, dtype=np.float32), sr


def _write_wav_safe(target_wav_path, stereo_buf, sr):
    """Writes a 24-bit WAV atomically via temp file replacement."""
    tmp_path = f"{target_wav_path}.tmp.wav"
    stereo_buf = np.ascontiguousarray(np.clip(stereo_buf, -1.0, 1.0), dtype=np.float32)
    if HAS_PEDALBOARD:
        with AudioFile(tmp_path, "w", int(sr), 2, bit_depth=24) as af:
            af.write(stereo_buf)
    else:
        pcm16 = (stereo_buf.T * 32767.0).astype(np.int16).ravel()
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(int(sr))
            wf.writeframes(pcm16.tobytes())
    os.replace(tmp_path, target_wav_path)
    return target_wav_path


def _encode_16khz_mono_snippet_b64(stereo_buf, sr, clip_duration_sec=12.0):
    """
    Finds the loudest active window of stereo_buf, downsamples it to 16 kHz mono
    16-bit PCM WAV in memory, and returns a base64 string for Gemini inlineData.
    """
    mono = 0.5 * (stereo_buf[0] + stereo_buf[1])
    total_frames = len(mono)
    clip_frames = min(total_frames, max(sr, int(sr * clip_duration_sec)))

    if total_frames > clip_frames:
        stride = max(1, sr)
        best_start = 0
        best_energy = -1.0
        for start_idx in range(0, total_frames - clip_frames, stride):
            segment = mono[start_idx : start_idx + stride]
            energy = float(np.mean(segment ** 2))
            if energy > best_energy:
                best_energy = energy
                best_start = start_idx
        excerpt = mono[best_start : best_start + clip_frames]
    else:
        excerpt = mono

    target_sr = 16000
    if sr != target_sr and len(excerpt) > 1:
        duration_s = len(excerpt) / float(sr)
        target_len = max(1, int(duration_s * target_sr))
        x_old = np.linspace(0.0, 1.0, len(excerpt), endpoint=False)
        x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
        excerpt_16k = np.interp(x_new, x_old, excerpt)
    else:
        excerpt_16k = excerpt

    peak = float(np.max(np.abs(excerpt_16k)) + 1e-9)
    if peak > 1.0:
        excerpt_16k = excerpt_16k / peak
    pcm16 = (np.clip(excerpt_16k, -1.0, 1.0) * 32767.0).astype(np.int16)

    mem_wav = io.BytesIO()
    with wave.open(mem_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_sr)
        wf.writeframes(pcm16.tobytes())

    return base64.b64encode(mem_wav.getvalue()).decode("ascii")


def _compute_buffer_metrics(stereo_buf, sr):
    """Computes RMS, Peak, Crest Factor, P25/P85 50ms window distribution, and Mid/Side ratio."""
    rms_lin = float(np.sqrt(np.mean(stereo_buf.astype(np.float64) ** 2)))
    rms_db = round(float(20.0 * np.log10(rms_lin + 1e-9)), 2)

    peak_lin = float(np.max(np.abs(stereo_buf)))
    peak_db = round(float(20.0 * np.log10(peak_lin + 1e-9)), 2)
    crest_db = round(peak_db - rms_db, 2)

    mid = 0.5 * (stereo_buf[0] + stereo_buf[1])
    side = 0.5 * (stereo_buf[0] - stereo_buf[1])
    mid_rms = float(np.sqrt(np.mean(mid.astype(np.float64) ** 2)) + 1e-9)
    side_rms = float(np.sqrt(np.mean(side.astype(np.float64) ** 2)) + 1e-9)
    mid_side_db = round(float(20.0 * np.log10(mid_rms / side_rms)), 2)

    win_size = max(1, int(sr * 0.05))
    n_wins = len(mid) // win_size
    if n_wins > 6:
        framed = mid[: n_wins * win_size].reshape(n_wins, win_size)
        win_rms_db = 20.0 * np.log10(np.sqrt(np.mean(framed ** 2, axis=1)) + 1e-9)
        active_wins = win_rms_db[win_rms_db > -55.0]
        if len(active_wins) > 3:
            p25_tail_db = round(float(np.percentile(active_wins, 25)), 2)
            p85_body_db = round(float(np.percentile(active_wins, 85)), 2)
        else:
            p25_tail_db, p85_body_db = -48.0, rms_db
    else:
        p25_tail_db, p85_body_db = -48.0, rms_db

    return {
        "rms_db": rms_db,
        "peak_db": peak_db,
        "crest_db": crest_db,
        "p25_tail_db": p25_tail_db,
        "p85_body_db": p85_body_db,
        "tail_spread_db": round(p85_body_db - p25_tail_db, 2),
        "mid_side_db": mid_side_db,
    }


# ==============================================================================
# FUNCTION 1: AUDIO SNIPPET & TELEMETRY EXTRACTOR (STEMS OR MASTER WAV)
# ==============================================================================
def extract_audio_snippet_and_telemetry(target_path, clip_duration_sec=12.0, log_callback=print):
    """
    Extracts acoustic telemetry AND a 16kHz base64 audio preview snippet from either:
      1. A song stem folder (while combining/cleaning stems), OR
      2. A single Master Mix .wav file (for on-the-fly master tuning).
    """
    norm_path = os.path.normpath(target_path)
    log_callback("=" * 72)
    log_callback(f"[RUN] Extracting Gemini On-the-Fly Telemetry & Audio Snippet: {norm_path}")

    payload = {
        "target_path": norm_path,
        "mode": None,
        "song_name": "",
        "buses": {},
        "inline_audio_b64": None,
    }

    if not os.path.exists(norm_path):
        log_callback(f"[ERROR] Target path does not exist: {norm_path}")
        return payload

    try:
        if os.path.isfile(norm_path) and norm_path.lower().endswith(".wav"):
            payload["mode"] = "master_wav"
            raw_base = os.path.splitext(os.path.basename(norm_path))[0]
            payload["song_name"] = re.sub(
                r"(_MASTER_MIX|_VOCAL_TUCKED_MASTER|_GEMINI_TUNED_MASTER)$",
                "",
                raw_base,
                flags=re.IGNORECASE,
            )

            buf, sr = _read_wav_stereo_float32(norm_path)
            metrics = _compute_buffer_metrics(buf, sr)
            metrics["primary_file"] = os.path.basename(norm_path)
            payload["buses"]["Master"] = metrics
            payload["inline_audio_b64"] = _encode_16khz_mono_snippet_b64(buf, sr, clip_duration_sec)

            log_callback(
                f"[SUCCESS] [Master WAV] '{metrics['primary_file']}' -> "
                f"RMS: {metrics['rms_db']} dB | Peak: {metrics['peak_db']} dB | "
                f"Mid/Side: {metrics['mid_side_db']} dB | Snippet: {len(payload['inline_audio_b64']) // 1024} KB b64"
            )
            return payload

        payload["mode"] = "stems"
        payload["song_name"] = os.path.basename(norm_path)

        bus_preview_buffers = {}
        preview_sr = None
        max_preview_frames = 0

        for root, _, files in os.walk(norm_path):
            parent_folder = os.path.basename(root)
            for fname in sorted(files):
                upper_f = fname.upper()
                if not upper_f.endswith(".WAV"):
                    continue
                if any(
                    upper_f.endswith(t)
                    for t in ["_GLUED.WAV", "_MASTER_MIX.WAV", "_VOCAL_TUCKED_MASTER.WAV", "_GEMINI_TUNED_MASTER.WAV"]
                ):
                    continue

                wav_path = os.path.join(root, fname)
                bus_cat = _classify_stem_bus(fname, parent_folder)
                buf, sr = _read_wav_stereo_float32(wav_path)
                metrics = _compute_buffer_metrics(buf, sr)

                if metrics["rms_db"] < -50.0:
                    log_callback(f"[INFO]   Skipping ghost/silent stem '{fname}' ({metrics['rms_db']} dB)")
                    continue

                metrics["primary_file"] = fname
                prev = payload["buses"].get(bus_cat)
                if prev is None or metrics["rms_db"] > prev["rms_db"]:
                    payload["buses"][bus_cat] = metrics
                    bus_preview_buffers[bus_cat] = buf
                    preview_sr = sr
                    max_preview_frames = max(max_preview_frames, buf.shape[1])

                log_callback(
                    f"[INFO]   + [{bus_cat:<6}] '{fname}' -> RMS: {metrics['rms_db']} dB | "
                    f"Tail(P25): {metrics['p25_tail_db']} dB | Mid/Side: {metrics['mid_side_db']} dB"
                )

        if bus_preview_buffers and preview_sr and max_preview_frames > 0:
            rough_sum = np.zeros((2, max_preview_frames), dtype=np.float32)
            for b_buf in bus_preview_buffers.values():
                n_f = min(b_buf.shape[1], max_preview_frames)
                rough_sum[:, :n_f] += b_buf[:, :n_f] * 0.707
            payload["inline_audio_b64"] = _encode_16khz_mono_snippet_b64(
                rough_sum, preview_sr, clip_duration_sec
            )
            log_callback(
                f"[SUCCESS] Extracted {len(payload['buses'])} bus(es) + "
                f"{len(payload['inline_audio_b64']) // 1024} KB combined audio snippet for '{payload['song_name']}'."
            )
        else:
            log_callback(f"[ERROR] No active stems (> -50 dB RMS) found in: {norm_path}")

        return payload

    except Exception:
        log_callback(f"[ERROR] Failed extracting telemetry and audio snippet from {norm_path}:")
        log_callback(traceback.format_exc())
        return payload


# ==============================================================================
# FUNCTION 2: GEMINI MULTIMODAL LIVE TUNING ENGINE (WITH LOCAL DSP FALLBACK)
# ==============================================================================
def load_or_save_gemini_key(new_key=None, config_path=CONFIG_FILE_PATH, log_callback=print):
    """
    Loads or atomically saves 'gemini_api_key' in ~/.mvsep_hms_config.json
    while preserving existing MVSep token and mix_mode_label keys.
    """
    try:
        data = {}
        if config_path.is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        if new_key is not None and str(new_key).strip():
            data["gemini_api_key"] = str(new_key).strip()
            tmp_path = config_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, config_path)
            log_callback(f"[SUCCESS] Saved Gemini API Key to: {config_path}")

        resolved = str(data.get("gemini_api_key", "")).strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        return resolved
    except Exception:
        log_callback("[ERROR] Failed reading/saving Gemini API key config:")
        log_callback(traceback.format_exc())
        return os.environ.get("GEMINI_API_KEY", "").strip()


def _clamp(val, low, high, decimals=2):
    """Clamps a float to [low, high] and rounds to decimals."""
    return round(float(max(low, min(high, float(val)))), decimals)


def _compute_local_baseline_profile(telemetry_payload, current_params=None, log_callback=print):
    """
    Computes a deterministic local DSP tuning profile from telemetry_payload
    so the pipeline always has safe parameters even if offline or without an API key.
    """
    cur = current_params or {}
    cur_weights = cur.get("bus_weights", {})

    profile = {
        "source": "local-dsp-fallback",
        "mix_style": "heavy",
        "bus_weights": {
            "Vocals": float(cur_weights.get("Vocals", 1.15)),
            "Rhythm": float(cur_weights.get("Rhythm", 0.92)),
            "Music": float(cur_weights.get("Music", 0.78)),
        },
        "vocal_gate_db": float(cur.get("vocal_gate_db", -36.0)),
        "vst_overrides": {
            "mjuc_compress": 20.0,
            "mjuc_makeup": 2.0,
            "chow_rhythm_drive": 0.35,
            "nova_music_pocket_db": -2.8,
        },
        "needs_master_reglue": False,
        "ai_notes": [],
        "suno_tags": "industrial rock, dynamic modern studio mix, punchy drums, clear vocals",
    }

    mode = telemetry_payload.get("mode")
    buses = telemetry_payload.get("buses", {})

    if mode == "stems":
        vox = buses.get("Vocals")
        mus = buses.get("Music")

        if vox:
            tail_db = vox["p25_tail_db"]
            spread_db = vox["tail_spread_db"]
            if tail_db > -34.0 or spread_db < 11.5:
                profile["vocal_gate_db"] = _clamp(tail_db + 2.5, -32.0, -22.0, 1)
                profile["vst_overrides"]["mjuc_compress"] = 11.0
                profile["vst_overrides"]["mjuc_makeup"] = 1.0
                profile["ai_notes"].append(
                    f"High vocal tail floor ({tail_db} dB) -> raised Gate to {profile['vocal_gate_db']} dB, lowered MJUCjr to 11.0."
                )
            else:
                profile["vocal_gate_db"] = _clamp(tail_db + 1.5, -40.0, -30.0, 1)
                profile["vst_overrides"]["mjuc_compress"] = 22.0
                profile["vst_overrides"]["mjuc_makeup"] = 2.0

        if mus and vox:
            rms_diff = mus["rms_db"] - vox["rms_db"]
            if mus["mid_side_db"] > 4.5 or rms_diff < -1.5:
                profile["mix_style"] = "acoustic"
                profile["bus_weights"] = {"Vocals": 1.02, "Rhythm": 0.94, "Music": 0.90}
                profile["vst_overrides"]["nova_music_pocket_db"] = -1.5
                profile["ai_notes"].append(
                    f"Detected Acoustic/Dynamic balance (Music Mid/Side: {mus['mid_side_db']} dB, Diff: {rms_diff:.1f} dB) -> "
                    "preserved centered instruments (Vocals=1.02, Music=0.90)."
                )
            elif rms_diff > 2.0:
                profile["mix_style"] = "heavy"
                profile["bus_weights"] = {"Vocals": 1.22, "Rhythm": 0.92, "Music": 0.74}
                profile["vst_overrides"]["nova_music_pocket_db"] = -3.8
                profile["ai_notes"].append(
                    f"Heavy Music bus (+{rms_diff:.1f} dB over Vocals) -> pushed Vocals=1.22, tucked Music=0.74."
                )

    elif mode == "master_wav":
        master = buses.get("Master")
        if master:
            if master["mid_side_db"] > 7.5:
                profile["mix_style"] = "acoustic"
                profile["bus_weights"]["Vocals"] = _clamp(profile["bus_weights"]["Vocals"] - 0.14, 0.85, 1.35)
                profile["bus_weights"]["Music"] = _clamp(profile["bus_weights"]["Music"] + 0.10, 0.65, 1.15)
                profile["needs_master_reglue"] = True
                profile["ai_notes"].append(
                    f"Master WAV is center-heavy (Mid/Side: {master['mid_side_db']} dB). Tucked Vocals to "
                    f"{profile['bus_weights']['Vocals']} and lifted Music to {profile['bus_weights']['Music']}."
                )
            elif master["mid_side_db"] < 1.0:
                profile["mix_style"] = "heavy"
                profile["bus_weights"]["Vocals"] = _clamp(profile["bus_weights"]["Vocals"] + 0.10, 0.85, 1.40)
                profile["bus_weights"]["Music"] = _clamp(profile["bus_weights"]["Music"] - 0.06, 0.60, 1.10)
                profile["needs_master_reglue"] = True
                profile["ai_notes"].append(
                    f"Master WAV stereo sides overpower center vocals (Mid/Side: {master['mid_side_db']} dB). "
                    f"Boosted Vocals to {profile['bus_weights']['Vocals']}."
                )
            else:
                profile["ai_notes"].append(
                    f"Master WAV center-to-stereo balance is locked in (Mid/Side: {master['mid_side_db']} dB, Peak: {master['peak_db']} dB)."
                )

    return profile


def request_gemini_live_tuning(
    telemetry_payload,
    current_params=None,
    api_key="",
    log_callback=print,
):
    """
    Sends the telemetry metrics AND the 16kHz base64 WAV audio snippet to
    Gemini 2.5 Flash for real-time mix tuning while combining stems or
    auditing a rendered Master Mix WAV. Automatically falls back to local
    DSP telemetry rules if no API key is configured or offline.
    """
    song_name = telemetry_payload.get("song_name", "Unknown_Song")
    mode = telemetry_payload.get("mode", "stems")
    log_callback("-" * 72)
    log_callback(f"[RUN] Running Gemini On-the-Fly Tuner for '{song_name}' (mode={mode})...")

    profile = _compute_local_baseline_profile(telemetry_payload, current_params, log_callback)

    resolved_key = (api_key or "").strip() or load_or_save_gemini_key(log_callback=lambda _: None)
    if not resolved_key:
        log_callback(
            "[INFO] No Gemini API key configured; using verified Local HMS Acoustic Telemetry profile."
        )
        for note in profile["ai_notes"]:
            log_callback(f"[INFO]   * {note}")
        return profile

    try:
        telemetry_clean = {
            "song_name": song_name,
            "mode": mode,
            "buses": telemetry_payload.get("buses", {}),
            "current_baseline": {
                "mix_style": profile["mix_style"],
                "bus_weights": profile["bus_weights"],
                "vocal_gate_db": profile["vocal_gate_db"],
                "vst_overrides": profile["vst_overrides"],
            },
        }

        prompt_text = (
            "You are an expert studio mix & mastering engineer integrated into HMS Stem Cleaner.\n"
            "Listen to the attached 16kHz audio excerpt and inspect the acoustic telemetry JSON.\n"
            f"Telemetry & Baseline JSON: {json.dumps(telemetry_clean)}\n\n"
            "Tune the mix parameters on the fly so vocals sit naturally inside the band without "
            "slapback echo or harshness, and centered acoustic guitars are never hollowed out.\n"
            "Return strictly valid JSON with this exact schema:\n"
            "{\n"
            '  "mix_style": "acoustic" or "heavy",\n'
            '  "bus_weights": {"Vocals": float (0.75..1.35), "Rhythm": float (0.75..1.15), "Music": float (0.65..1.10)},\n'
            '  "vocal_gate_db": float (-42.0..-22.0),\n'
            '  "vst_overrides": {\n'
            '    "mjuc_compress": float (8.0..26.0),\n'
            '    "mjuc_makeup": float (0.5..3.5),\n'
            '    "chow_rhythm_drive": float (0.15..0.55),\n'
            '    "nova_music_pocket_db": float (-4.5..-1.0)\n'
            "  },\n"
            '  "needs_master_reglue": bool,\n'
            '  "ai_notes": ["concise adjustment reason 1", "concise adjustment reason 2"],\n'
            '  "suno_tags": "comma-separated Suno v6 style tags under 200 chars"\n'
            "}"
        )

        parts = [{"text": prompt_text}]
        audio_b64 = telemetry_payload.get("inline_audio_b64")
        if audio_b64:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "audio/wav",
                        "data": audio_b64,
                    }
                }
            )

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={resolved_key}"
        )
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json"},
        }

        log_callback("[RUN] Sending telemetry + inline WAV audio slice to gemini-2.5-flash...")
        resp = requests.post(url, json=body, timeout=25)
        resp.raise_for_status()
        raw_json_str = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        ai_data = json.loads(raw_json_str)

        profile["source"] = "gemini-2.5-flash"
        if ai_data.get("mix_style") in ("acoustic", "heavy"):
            profile["mix_style"] = ai_data["mix_style"]

        bw = ai_data.get("bus_weights", {})
        if isinstance(bw, dict):
            profile["bus_weights"]["Vocals"] = _clamp(bw.get("Vocals", profile["bus_weights"]["Vocals"]), 0.75, 1.35)
            profile["bus_weights"]["Rhythm"] = _clamp(bw.get("Rhythm", profile["bus_weights"]["Rhythm"]), 0.75, 1.15)
            profile["bus_weights"]["Music"] = _clamp(bw.get("Music", profile["bus_weights"]["Music"]), 0.65, 1.10)

        if "vocal_gate_db" in ai_data:
            profile["vocal_gate_db"] = _clamp(ai_data["vocal_gate_db"], -42.0, -22.0, 1)

        vo = ai_data.get("vst_overrides", {})
        if isinstance(vo, dict):
            profile["vst_overrides"]["mjuc_compress"] = _clamp(
                vo.get("mjuc_compress", profile["vst_overrides"]["mjuc_compress"]), 8.0, 26.0, 1
            )
            profile["vst_overrides"]["mjuc_makeup"] = _clamp(
                vo.get("mjuc_makeup", profile["vst_overrides"]["mjuc_makeup"]), 0.5, 3.5, 1
            )
            profile["vst_overrides"]["chow_rhythm_drive"] = _clamp(
                vo.get("chow_rhythm_drive", profile["vst_overrides"]["chow_rhythm_drive"]), 0.15, 0.55, 2
            )
            profile["vst_overrides"]["nova_music_pocket_db"] = _clamp(
                vo.get("nova_music_pocket_db", profile["vst_overrides"]["nova_music_pocket_db"]), -4.5, -1.0, 1
            )

        if "needs_master_reglue" in ai_data:
            profile["needs_master_reglue"] = bool(ai_data["needs_master_reglue"])

        if isinstance(ai_data.get("ai_notes"), list) and ai_data["ai_notes"]:
            profile["ai_notes"] = [str(n) for n in ai_data["ai_notes"]]
        if ai_data.get("suno_tags"):
            profile["suno_tags"] = str(ai_data["suno_tags"]).strip()

        log_callback(
            f"[SUCCESS] Gemini 2.5 Flash Live Tuning Complete -> Style: {profile['mix_style'].upper()} | "
            f"Vocals={profile['bus_weights']['Vocals']} | Rhythm={profile['bus_weights']['Rhythm']} | "
            f"Music={profile['bus_weights']['Music']} | Gate={profile['vocal_gate_db']} dB"
        )
        for note in profile["ai_notes"]:
            log_callback(f"[INFO]   [GEMINI] {note}")
        return profile

    except Exception as ex:
        log_callback(f"[INFO] Cloud Gemini pass unavailable ({ex}); using verified Local DSP Fallback profile.")
        return profile


# ==============================================================================
# FUNCTION 3: ON-THE-FLY STEM COMBINER & MASTER MIX WAV TUNER LOOP
# ==============================================================================
def tune_standalone_master_wav_in_place(master_wav_path, tuning_profile, log_callback=print):
    """
    Applies Mid/Side vocal-to-stereo re-weighting and surgical EQ directly to a
    standalone Master WAV file when no separated stem folders exist alongside it.
    """
    log_callback(f"[RUN] Applying On-the-Fly Mid/Side Master Polish to standalone WAV: {master_wav_path}")
    try:
        buf, sr = _read_wav_stereo_float32(master_wav_path)
        bw = tuning_profile.get("bus_weights", {"Vocals": 1.0, "Music": 1.0})

        # Decompose into Mid (center vocals/snare) and Side (stereo guitars/synths)
        mid = 0.5 * (buf[0] + buf[1])
        side = 0.5 * (buf[0] - buf[1])

        # Scale Mid vs Side gently based on Gemini's Vocals vs Music weight ratio
        mid_gain = _clamp(bw.get("Vocals", 1.0) / 1.08, 0.82, 1.18)
        side_gain = _clamp(bw.get("Music", 0.88) / 0.88, 0.85, 1.20)
        mid *= mid_gain
        side *= side_gain

        reconstructed = np.vstack([mid + side, mid - side]).astype(np.float32)

        if HAS_PEDALBOARD:
            pocket_db = float(tuning_profile.get("vst_overrides", {}).get("nova_music_pocket_db", -2.0))
            polish_chain = Pedalboard(
                [
                    HighpassFilter(cutoff_frequency_hz=28.0),
                    PeakFilter(cutoff_frequency_hz=360.0, gain_db=-1.5, q=1.6),
                    PeakFilter(cutoff_frequency_hz=2400.0, gain_db=max(-2.5, pocket_db * 0.5), q=1.4),
                    Compressor(threshold_db=-12.0, ratio=1.8, attack_ms=25.0, release_ms=110.0),
                    Limiter(threshold_db=-0.3, release_ms=40.0),
                ]
            )
            reconstructed = polish_chain(reconstructed, sr)

        base_no_ext = os.path.splitext(master_wav_path)[0]
        if not base_no_ext.upper().endswith("_GEMINI_TUNED_MASTER"):
            out_wav = f"{base_no_ext}_GEMINI_TUNED_MASTER.wav"
        else:
            out_wav = master_wav_path

        _write_wav_safe(out_wav, reconstructed, sr)
        log_callback(
            f"[SUCCESS] Wrote Gemini-Tuned Master WAV (Mid x{mid_gain}, Side x{side_gain}) -> {out_wav}"
        )
        return out_wav
    except Exception:
        log_callback("[ERROR] Failed tuning standalone Master WAV:")
        log_callback(traceback.format_exc())
        return master_wav_path


def run_on_the_fly_gemini_mix_loop(
    target_path,
    dest_root=None,
    api_key="",
    auto_reglue_master=True,
    gui_slider_callback=None,
    log_callback=print,
):
    """
    Closed-loop Gemini On-the-Fly Connector for both:
      1. Stem Folders (tunes VST3 levers & sliders BEFORE combining stems, then audits
         the rendered Master WAV and re-glues if vocal balance needs trimming), OR
      2. Master Mix WAV files (audits the Master WAV directly and either re-glues
         from the adjacent cleaned bus stems or polishes the stereo WAV in place).
    """
    norm_target = os.path.normpath(target_path)
    summary = {
        "mode": None,
        "song_name": "",
        "tuning_profile": None,
        "master_wav_path": None,
        "reglued": False,
        "report_json_path": None,
    }

    try:
        import hms_stem_cleaner_app as hms
    except ImportError:
        hms = None
        log_callback("[INFO] hms_stem_cleaner_app not found on sys.path; running in standalone WAV mode.")

    # Step 1: Extract Telemetry + 16kHz Audio Preview Slice
    telemetry = extract_audio_snippet_and_telemetry(norm_target, log_callback=log_callback)
    if not telemetry.get("mode"):
        return summary

    summary["mode"] = telemetry["mode"]
    summary["song_name"] = telemetry["song_name"]

    # Step 2: Request Live Gemini Tuning Profile
    profile = request_gemini_live_tuning(telemetry, api_key=api_key, log_callback=log_callback)
    summary["tuning_profile"] = profile

    # Snap GUI sliders live if called from hms_stem_cleaner_app.py or mvsep_gui.py
    if callable(gui_slider_callback):
        try:
            gui_slider_callback(profile)
        except Exception:
            pass

    # CASE A: Target is a Stem Folder (Tune while combining stems + Post-Master Audit)
    if telemetry["mode"] == "stems" and hms is not None:
        if hasattr(hms, "HMS_MIX_STYLE_ACTIVE"):
            hms.HMS_MIX_STYLE_ACTIVE = profile["mix_style"]

        log_callback(
            f"[RUN] Executing HMS Stem Cleanup with Gemini Live Levers (Style={profile['mix_style'].upper()})..."
        )
        res = hms.execute_stem_cleanup(
            source_dir=norm_target,
            dest_root=dest_root,
            dry_run=False,
            move_source_files=False,
            render_master=True,
            vocal_gate_db=profile["vocal_gate_db"],
            bus_weights=profile["bus_weights"],
            vst_overrides=profile["vst_overrides"],
        )
        master_wav = res.get("master_wav_path")
        dest_song_dir = res.get("dest_song_dir") or norm_target
        summary["master_wav_path"] = master_wav

        # Closed-Loop Post-Render Audit on the freshly combined Master WAV
        if auto_reglue_master and master_wav and os.path.isfile(master_wav):
            log_callback("[RUN] Performing Post-Combine Gemini Audit on rendered Master Mix WAV...")
            post_tel = extract_audio_snippet_and_telemetry(master_wav, log_callback=log_callback)
            post_prof = request_gemini_live_tuning(
                post_tel,
                current_params=profile,
                api_key=api_key,
                log_callback=log_callback,
            )
            if post_prof.get("needs_master_reglue"):
                log_callback(
                    f"[RUN] Gemini requested on-the-fly Master Re-Glue -> New Weights: {post_prof['bus_weights']}"
                )
                vst_status = hms.resolve_vst3_binary_path()
                reglue_res = hms.render_master_mixdown(
                    dest_song_dir=dest_song_dir,
                    song_name=res.get("song_name", summary["song_name"]),
                    vst3_status=vst_status,
                    bus_weights=post_prof["bus_weights"],
                )
                summary["master_wav_path"] = reglue_res.get("master_wav_path", master_wav)
                summary["tuning_profile"] = post_prof
                summary["reglued"] = True
                if callable(gui_slider_callback):
                    try:
                        gui_slider_callback(post_prof)
                    except Exception:
                        pass

        # Save JSON tuning report in destination folder
        report_dir = dest_song_dir if os.path.isdir(dest_song_dir) else norm_target
        report_path = os.path.join(report_dir, f"{summary['song_name']}_GEMINI_TUNING_REPORT.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary["tuning_profile"], f, indent=2)
        summary["report_json_path"] = report_path
        log_callback(f"[SUCCESS] Saved Gemini Tuning Report -> {report_path}")
        return summary

    # CASE B: Target is an existing Master Mix WAV file (On-the-Fly Master Tuning)
    elif telemetry["mode"] == "master_wav":
        parent_dir = os.path.dirname(norm_target)
        has_cleaned_buses = any(
            os.path.isdir(os.path.join(parent_dir, b)) for b in ("Vocals", "Rhythm", "Music")
        )

        # If the Master WAV sits right inside a cleaned song folder with Vocals/Rhythm/Music buses,
        # re-glue the buses directly with the new Gemini weights!
        if has_cleaned_buses and hms is not None and auto_reglue_master:
            log_callback(
                f"[RUN] Found cleaned bus subfolders in {parent_dir}; re-gluing Master Mix WAV with Gemini weights..."
            )
            if hasattr(hms, "HMS_MIX_STYLE_ACTIVE"):
                hms.HMS_MIX_STYLE_ACTIVE = profile["mix_style"]
            vst_status = hms.resolve_vst3_binary_path()
            reglue_res = hms.render_master_mixdown(
                dest_song_dir=parent_dir,
                song_name=summary["song_name"],
                vst3_status=vst_status,
                bus_weights=profile["bus_weights"],
            )
            summary["master_wav_path"] = reglue_res.get("master_wav_path", norm_target)
            summary["reglued"] = True
        else:
            # Standalone WAV file without stem subfolders: polish in-place via Mid/Side + EQ
            summary["master_wav_path"] = tune_standalone_master_wav_in_place(
                norm_target, profile, log_callback=log_callback
            )
            summary["reglued"] = True

        report_path = os.path.join(parent_dir, f"{summary['song_name']}_GEMINI_TUNING_REPORT.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
        summary["report_json_path"] = report_path
        log_callback(f"[SUCCESS] On-the-Fly Master WAV Tuning Complete -> {summary['master_wav_path']}")
        return summary

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HMS Gemini On-the-Fly Tuner (Stem Combiner & Master Mix WAV Controller)"
    )
    parser.add_argument(
        "--target",
        type=str,
        required=True,
        help="Path to a stem folder (while combining stems) OR a Master Mix .wav file",
    )
    parser.add_argument("--dest", type=str, default=None, help="Optional destination root folder")
    parser.add_argument("--api-key", type=str, default="", help="Optional Gemini API Key (saves to config)")
    parser.add_argument("--no-reglue", action="store_true", help="Disable automatic post-render Master re-glue")
    args = parser.parse_args()

    if args.api_key:
        load_or_save_gemini_key(args.api_key)

    run_on_the_fly_gemini_mix_loop(
        target_path=args.target,
        dest_root=args.dest,
        api_key=args.api_key,
        auto_reglue_master=(not args.no_reglue),
    )