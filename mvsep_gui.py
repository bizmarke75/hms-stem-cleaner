import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==============================================================================
# MVSEP API, GEMINI TUNER & HMS STEM CLEANER CONFIGURATION
# ==============================================================================
API_CREATE_URL = "https://mvsep.com/api/separation/create"
API_GET_URL = "https://mvsep.com/api/separation/get"
ICON_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "mvsep.ico"

# Persistent user-level config file (stored in C:\Users\<Username>\.mvsep_hms_config.json)
CONFIG_FILE_PATH = Path.home() / ".mvsep_hms_config.json"

# Separate timeouts: single float 600.0s for uploads so ssl.sendall() never aborts at 20s!
REQUEST_TIMEOUT = (15, 120)
UPLOAD_SOCKET_TIMEOUT = 600.0
MAX_UPLOAD_RETRIES = 3
POLL_INTERVAL = 10
MAX_POLL_SECONDS = 6 * 60 * 60

# Paths to your HMS Stem Cleaner repository, Gemini Tuner, and standalone EXE
HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
HMS_APP_SCRIPT = os.path.join(HMS_REPO_DIR, "hms_stem_cleaner_app.py")
HMS_GEMINI_SCRIPT = os.path.join(HMS_REPO_DIR, "hms_gemini_tuner.py")
HMS_EXE_PATH = os.path.join(HMS_REPO_DIR, "dist", "HMS_Stem_Cleaner.exe")

if HMS_REPO_DIR not in sys.path and os.path.isdir(HMS_REPO_DIR):
    sys.path.insert(0, HMS_REPO_DIR)
try:
    import hms_ai_api_bridge as ai_bridge
except Exception:
    ai_bridge = None


# Commonly used MVSep Separation Types (sep_type)
MODELS = {
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

# MVSep Output Format IDs (output_format)
FORMATS = {
    "WAV (Uncompressed, 16-bit)": 1,
    "FLAC (Lossless, 16-bit)": 2,
    "FLAC (Lossless, 24-bit)": 5,
    "MP3 (320 kbps)": 0,
    "WAV (Uncompressed, 32-bit)": 4,
}

# HMS Mix Style Mode Switch Options
MIX_MODES = {
    "Auto-Detect (Gemini / Mid-Side Telemetry)": "auto",
    "Acoustic / Dynamic Rock (Preserve Center Guitars & Natural Vocals)": "acoustic",
    "Heavy Metal / Industrial (Nu-Metal Wall & Mid/Side Pocket)": "heavy",
}


# ==============================================================================
# HELPER: UNIFIED API KEYS & MIX MODE PERSISTENCE (LOAD & SAVE)
# ==============================================================================
def load_saved_config(config_path=CONFIG_FILE_PATH, log_callback=print):
    """
    Loads the saved MVSep API token, Gemini API key, and last Mix Style mode from
    C:\\Users\\<User>\\.mvsep_hms_config.json with environment variable fallback.
    """
    cfg = {
        "mvsep_api_token": os.environ.get("MVSEP_API_TOKEN", "").strip(),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", "").strip(),
        "mix_mode_label": list(MIX_MODES.keys())[0],
    }
    try:
        if config_path.is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mvsep_tok = str(data.get("mvsep_api_token", "")).strip()
            if mvsep_tok:
                cfg["mvsep_api_token"] = mvsep_tok
                log_callback(f"[INFO] Loaded saved MVSep API token from: {config_path}")

            gem_key = str(data.get("gemini_api_key", "")).strip()
            if gem_key:
                cfg["gemini_api_key"] = gem_key
                log_callback(f"[INFO] Loaded saved Gemini API key from: {config_path}")

            saved_mode = str(data.get("mix_mode_label", "")).strip()
            if saved_mode in MIX_MODES:
                cfg["mix_mode_label"] = saved_mode
    except Exception:
        log_callback("[ERROR] Could not read saved config:")
        log_callback(traceback.format_exc())

    return cfg


def save_config_to_disk(
    mvsep_key=None,
    gemini_key=None,
    mix_mode_label=None,
    config_path=CONFIG_FILE_PATH,
    log_callback=print,
):
    """
    Atomically merges and writes the MVSep API token, Gemini API key, and selected
    Mix Mode to C:\\Users\\<User>\\.mvsep_hms_config.json so neither key is lost.
    """
    try:
        payload = {}
        if config_path.is_file():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                payload = {}

        if mvsep_key is not None and str(mvsep_key).strip():
            payload["mvsep_api_token"] = str(mvsep_key).strip()
        if gemini_key is not None and str(gemini_key).strip():
            payload["gemini_api_key"] = str(gemini_key).strip()
        if mix_mode_label and mix_mode_label in MIX_MODES:
            payload["mix_mode_label"] = mix_mode_label

        temp_path = config_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(temp_path, config_path)
        log_callback(f"[SUCCESS] Saved API credentials & settings to: {config_path}")
        return True
    except Exception:
        log_callback("[ERROR] Failed to save API config:")
        log_callback(traceback.format_exc())
        return False


# ==============================================================================
# HELPER: RESOLVE REAL PYTHON.EXE WHEN COMPILED WITH PYINSTALLER
# ==============================================================================
def resolve_python_interpreter():
    """Returns the real python.exe path even when mvsep_gui.py is frozen into an .exe."""
    if not getattr(sys, "frozen", False):
        return sys.executable

    found_py = shutil.which("python") or shutil.which("python3")
    if found_py:
        return found_py

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    programs_py = os.path.join(local_app_data, "Programs", "Python")
    if os.path.isdir(programs_py):
        for folder in sorted(os.listdir(programs_py), reverse=True):
            candidate = os.path.join(programs_py, folder, "python.exe")
            if os.path.isfile(candidate):
                return candidate

    return "python.exe"


# ==============================================================================
# HELPER: LOSSLESS WAV -> FLAC PRE-COMPRESSOR + 600s SOCKET WRITE UPLOADER
# ==============================================================================
def prepare_fast_upload_audio(file_path, log_callback=print):
    """
    Losslessly compresses large uncompressed WAV files (>15 MB) into a temporary
    FLAC file before uploading to MVSep so 46 MB WAVs shrink to ~14 MB and upload
    3x faster with zero audio quality loss.
    """
    orig_size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
    ext = os.path.splitext(file_path)[1].lower()

    if ext != ".wav" or orig_size_mb <= 15.0:
        mime = "audio/flac" if ext == ".flac" else "audio/wav"
        return file_path, False, mime

    try:
        import soundfile as sf

        log_callback(
            f"[RUN] Losslessly compressing '{os.path.basename(file_path)}' ({orig_size_mb} MB WAV -> FLAC) for faster upload..."
        )
        t0 = time.monotonic()
        data, samplerate = sf.read(file_path, dtype="float32", always_2d=True)

        fd, temp_flac_path = tempfile.mkstemp(suffix=".flac", prefix="mvsep_upload_")
        os.close(fd)

        sf.write(temp_flac_path, data, samplerate, format="FLAC", subtype="PCM_16")

        new_size_mb = round(os.path.getsize(temp_flac_path) / (1024 * 1024), 2)
        elapsed = round(time.monotonic() - t0, 1)
        savings_pct = round((1.0 - (new_size_mb / max(orig_size_mb, 0.01))) * 100, 1)

        log_callback(
            f"[SUCCESS] Lossless FLAC ready in {elapsed}s: {orig_size_mb} MB -> {new_size_mb} MB ({savings_pct}% smaller!)"
        )
        return temp_flac_path, True, "audio/flac"

    except Exception as ex:
        log_callback(
            f"[INFO] FLAC pre-compression skipped ({ex}); uploading original WAV directly."
        )
        return file_path, False, "audio/wav"


def upload_audio_to_mvsep_with_retry(
    api_key,
    file_path,
    sep_type,
    output_format,
    cancel_event,
    log_callback=print,
):
    """
    Uploads audio to MVSep with a single-float 600s socket write timeout and automatic
    3-attempt retry so SSL write operations never abort at 20 seconds.
    """
    upload_path, is_temp, mime_type = prepare_fast_upload_audio(file_path, log_callback)

    try:
        file_size_mb = round(os.path.getsize(upload_path) / (1024 * 1024), 2)
        base_stem = os.path.splitext(os.path.basename(file_path))[0]
        upload_ext = os.path.splitext(upload_path)[1].lower()
        remote_filename = f"{base_stem}{upload_ext}"

        log_callback(
            f"[RUN] Uploading '{remote_filename}' ({file_size_mb} MB) to MVSep "
            f"(Socket Write Timeout: {int(UPLOAD_SOCKET_TIMEOUT)}s, Max Attempts: {MAX_UPLOAD_RETRIES})..."
        )

        payload = {
            "api_token": api_key,
            "sep_type": str(sep_type),
            "output_format": str(output_format),
        }

        for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
            if cancel_event.is_set():
                log_callback("[INFO] Upload cancelled by user.")
                return None

            t0 = time.monotonic()
            try:
                log_callback(f"[INFO] Upload Attempt {attempt}/{MAX_UPLOAD_RETRIES} in progress...")
                with requests.Session() as session:
                    with open(upload_path, "rb") as audio_file:
                        files = {
                            "audiofile": (remote_filename, audio_file, mime_type)
                        }
                        resp = session.post(
                            API_CREATE_URL,
                            data=payload,
                            files=files,
                            timeout=UPLOAD_SOCKET_TIMEOUT,
                        )

                elapsed = round(time.monotonic() - t0, 1)

                if resp.status_code != 200:
                    log_callback(f"[ERROR] MVSep returned HTTP {resp.status_code} after {elapsed}s:")
                    log_callback(resp.text[:500])
                    if attempt < MAX_UPLOAD_RETRIES:
                        log_callback("[INFO] Retrying upload in 5 seconds...")
                        if cancel_event.wait(5):
                            return None
                        continue
                    return None

                res_data = resp.json()
                log_callback(f"[SUCCESS] Upload completed in {elapsed}s!")
                return res_data

            except (requests.Timeout, requests.ConnectionError, TimeoutError, OSError) as ex:
                elapsed = round(time.monotonic() - t0, 1)
                log_callback(
                    f"[ERROR] Attempt {attempt}/{MAX_UPLOAD_RETRIES} timed out/dropped after {elapsed}s: {ex}"
                )
                if attempt < MAX_UPLOAD_RETRIES:
                    log_callback("[INFO] Waiting 5 seconds before retrying upload...")
                    if cancel_event.wait(5):
                        return None
                else:
                    log_callback("[ERROR] All upload attempts failed:")
                    log_callback(traceback.format_exc())
                    return None
            except Exception:
                log_callback("[ERROR] Unexpected exception during MVSep upload:")
                log_callback(traceback.format_exc())
                return None

        return None

    finally:
        if is_temp and os.path.isfile(upload_path):
            try:
                os.remove(upload_path)
                log_callback(f"[INFO] Cleaned up temporary upload file: {os.path.basename(upload_path)}")
            except OSError:
                pass


# ==============================================================================
# BRIDGE FUNCTION 1: STAGE DOWNLOADED STEMS INTO A DEDICATED SONG FOLDER
# ==============================================================================
def prepare_hms_song_workspace(input_audio_path, downloaded_paths, log_callback=print):
    """
    Organizes downloaded MVSep stem files (or extracts a downloaded MVSep ZIP)
    into a dedicated song folder (<Parent_Dir>/<Song_Name>_Stems/) so HMS Stem
    Cleaner can accurately derive the song title and scan only that song's stems.
    """
    log_callback("=" * 65)
    log_callback(f"[RUN] Preparing HMS Song Workspace for: {input_audio_path}")

    if not input_audio_path or not downloaded_paths:
        log_callback("[ERROR] Missing input_audio_path or downloaded_paths list is empty.")
        return None

    try:
        parent_dir = os.path.dirname(os.path.abspath(input_audio_path))
        raw_base = os.path.splitext(os.path.basename(input_audio_path))[0]
        clean_song_name = "".join(
            "_" if c in '<>:"/\\|?* ' else c for c in raw_base
        ).strip("_") or "MVSep_Song"

        song_workspace_dir = os.path.join(parent_dir, f"{clean_song_name}_Stems")
        os.makedirs(song_workspace_dir, exist_ok=True)
        log_callback(f"[INFO] Target HMS Song Folder: {song_workspace_dir}")

        staged_wav_count = 0

        for item_path in downloaded_paths:
            if not item_path or not os.path.isfile(item_path):
                log_callback(f"[INFO] Skipping missing path: {item_path}")
                continue

            ext = os.path.splitext(item_path)[1].lower()

            if ext == ".zip":
                log_callback(f"[RUN] Extracting MVSep ZIP archive: {os.path.basename(item_path)}")
                with zipfile.ZipFile(item_path, "r") as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        safe_name = os.path.basename(member.filename)
                        if not safe_name:
                            continue
                        dest_member_path = os.path.join(song_workspace_dir, safe_name)
                        with zf.open(member) as src_f, open(dest_member_path, "wb") as dst_f:
                            shutil.copyfileobj(src_f, dst_f)
                        staged_wav_count += 1
                        log_callback(f"[INFO] Extracted stem -> {dest_member_path}")
            else:
                dest_file_path = os.path.join(song_workspace_dir, os.path.basename(item_path))
                if os.path.abspath(item_path) != os.path.abspath(dest_file_path):
                    shutil.move(item_path, dest_file_path)
                staged_wav_count += 1
                log_callback(f"[INFO] Staged stem ({staged_wav_count}) -> {dest_file_path}")

        if staged_wav_count == 0:
            log_callback("[ERROR] Zero stem files were staged into the HMS workspace folder.")
            return None

        log_callback(
            f"[SUCCESS] HMS Workspace Ready ({staged_wav_count} stem(s)) -> {song_workspace_dir}"
        )
        return song_workspace_dir

    except Exception:
        log_callback("[ERROR] Failed preparing HMS Song Workspace:")
        log_callback(traceback.format_exc())
        return None


# ==============================================================================
# BRIDGE FUNCTION 2: INVOKE HMS STEM CLEANER + GEMINI ON-THE-FLY TUNER
# ==============================================================================
def invoke_hms_stem_cleaner_bridge(
    target_path,
    mode="live",
    mix_style="auto",
    gemini_api_key="",
    dest_root=None,
    log_callback=print,
    hms_script_path=HMS_APP_SCRIPT,
    hms_exe_path=HMS_EXE_PATH,
):
    """
    Executes HMS Stem Cleaner or the Gemini On-the-Fly Tuner against either:
      - A stem folder (mode='dry_run' or mode='live' while combining stems)
      - A Master Mix WAV file (mode='tune_master_wav' for on-the-fly master tuning)
      - Standalone GUI launch (mode='launch_gui')
    """
    log_callback("=" * 65)
    log_callback(
        f"[RUN] Invoking HMS + Gemini Bridge (mode='{mode}', mix_style='{mix_style}')"
    )

    try:
        python_bin = resolve_python_interpreter()

        if mode == "launch_gui":
            if os.path.isfile(hms_exe_path):
                log_callback(f"[INFO] Launching standalone EXE: {hms_exe_path}")
                subprocess.Popen([hms_exe_path], cwd=os.path.dirname(hms_exe_path))
                log_callback("[SUCCESS] HMS_Stem_Cleaner.exe GUI launched.")
                return True
            elif os.path.isfile(hms_script_path):
                log_callback(f"[INFO] Launching Python GUI: {hms_script_path}")
                subprocess.Popen(
                    [python_bin, hms_script_path],
                    cwd=os.path.dirname(hms_script_path),
                )
                log_callback("[SUCCESS] hms_stem_cleaner_app.py GUI launched.")
                return True
            else:
                log_callback(
                    f"[ERROR] Neither {hms_exe_path} nor {hms_script_path} was found on disk."
                )
                return False

        if not target_path or not os.path.exists(target_path):
            log_callback(f"[ERROR] Invalid or missing target path: {target_path}")
            return False

        repo_dir = os.path.dirname(os.path.abspath(hms_script_path))

        # Use hms_gemini_tuner.py for live stem combining (when auto/Gemini enabled) and master WAV tuning
        if mode in ("live", "tune_master_wav") and os.path.isfile(HMS_GEMINI_SCRIPT):
            runner_code = (
                "import sys, os\n"
                f"sys.path.insert(0, {repo_dir!r})\n"
                "import hms_gemini_tuner as gt\n"
                "import hms_stem_cleaner_app as hms\n"
                f"target_path = {os.path.abspath(target_path)!r}\n"
                f"dest_root = {os.path.abspath(dest_root) if dest_root else None!r}\n"
                f"api_key = {gemini_api_key!r}\n"
                f"mix_style = {mix_style!r}\n"
                "if mix_style in ('acoustic', 'heavy') and hasattr(hms, 'HMS_MIX_STYLE_ACTIVE'):\n"
                "    hms.HMS_MIX_STYLE_ACTIVE = mix_style\n"
                "res = gt.run_on_the_fly_gemini_mix_loop(\n"
                "    target_path=target_path,\n"
                "    dest_root=dest_root,\n"
                "    api_key=api_key,\n"
                "    auto_reglue_master=True,\n"
                ")\n"
                "print(f'[SUCCESS] Gemini On-the-Fly Master Ready -> {res.get(\"master_wav_path\")}')\n"
            )
        else:
            is_dry_run = mode == "dry_run"
            runner_code = (
                "import sys, os\n"
                f"sys.path.insert(0, {repo_dir!r})\n"
                "import hms_stem_cleaner_app as hms\n"
                f"song_dir = {os.path.abspath(target_path)!r}\n"
                f"dest_root = {os.path.abspath(dest_root) if dest_root else None!r}\n"
                f"dry_run = {is_dry_run!r}\n"
                "res = hms.execute_stem_cleanup(\n"
                "    source_dir=song_dir,\n"
                "    dest_root=dest_root,\n"
                "    dry_run=dry_run,\n"
                "    move_source_files=False,\n"
                "    render_master=True,\n"
                ")\n"
                "print(f'[SUCCESS] HMS Bridge Finished: {res.get(\"status\", \"done\")}')\n"
            )

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        process = subprocess.Popen(
            [python_bin, "-u", "-c", runner_code],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )

        for raw_line in process.stdout:
            clean_line = raw_line.rstrip("\r\n")
            if clean_line:
                log_callback(clean_line)

        return_code = process.wait()
        if return_code == 0:
            log_callback(f"[SUCCESS] HMS + Gemini Bridge ({mode}) completed cleanly!")
            return True
        else:
            log_callback(f"[ERROR] HMS + Gemini Bridge exited with code: {return_code}")
            return False

    except Exception:
        log_callback("[ERROR] Exception inside invoke_hms_stem_cleaner_bridge:")
        log_callback(traceback.format_exc())
        return False


# ==============================================================================
# MAIN MVSEP TKINTER GUI APPLICATION
# ==============================================================================
class MVSepGUIApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MVSep Audio Stem Separator + HMS Gemini On-the-Fly Tuner")
        self.root.geometry("780x800")
        self.root.minsize(700, 680)
        if os.name == "nt" and ICON_PATH.is_file():
            self.root.iconbitmap(str(ICON_PATH))

        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.ui_events = queue.Queue()
        self.cancel_event = threading.Event()
        self.last_prepared_song_dir = None

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.process_ui_events)

    def on_close(self):
        self.cancel_event.set()
        self.root.destroy()
        os._exit(0)

    def create_widgets(self):
        padding = {"padx": 10, "pady": 5}

        # --- 1. Authentication & AI API Keys Section (MVSep + Gemini) ---
        api_frame = ttk.LabelFrame(self.root, text=" 1. Authentication & Saved API Keys (MVSep + Gemini) ")
        api_frame.pack(fill="x", **padding)

        ttk.Label(api_frame, text="MVSep API Token:").grid(row=0, column=0, sticky="w", **padding)
        self.api_entry = ttk.Entry(api_frame, width=44, show="*")
        self.api_entry.grid(row=0, column=1, sticky="ew", **padding)

        ttk.Label(api_frame, text="Gemini API Key:").grid(row=1, column=0, sticky="w", **padding)
        self.gemini_entry = ttk.Entry(api_frame, width=44, show="*")
        self.gemini_entry.grid(row=1, column=1, sticky="ew", **padding)

        self.show_key_var = tk.BooleanVar(value=False)
        show_cb = ttk.Checkbutton(
            api_frame,
            text="Show Keys",
            variable=self.show_key_var,
            command=self.toggle_key_visibility,
        )
        show_cb.grid(row=0, column=2, rowspan=2, sticky="w", padx=(4, 6), pady=5)

        save_token_btn = ttk.Button(
            api_frame, text="💾 Save API Keys", command=self.save_token_clicked
        )
        save_token_btn.grid(row=0, column=3, rowspan=2, sticky="ns", padx=(2, 10), pady=6)
        api_frame.columnconfigure(1, weight=1)

        # --- 2. File Selection Section ---
        file_frame = ttk.LabelFrame(self.root, text=" 2. Audio File Selection ")
        file_frame.pack(fill="x", **padding)

        ttk.Label(file_frame, text="WAV File Path:").grid(row=0, column=0, sticky="w", **padding)
        self.file_entry = ttk.Entry(file_frame, width=50)
        self.file_entry.grid(row=0, column=1, sticky="ew", **padding)

        browse_btn = ttk.Button(file_frame, text="Browse...", command=self.browse_file)
        browse_btn.grid(row=0, column=2, **padding)
        file_frame.columnconfigure(1, weight=1)

        # --- 3. Separation Options (Dropdowns) ---
        opts_frame = ttk.LabelFrame(self.root, text=" 3. Separation Parameters ")
        opts_frame.pack(fill="x", **padding)

        ttk.Label(opts_frame, text="Separation Model:").grid(row=0, column=0, sticky="w", **padding)
        self.model_combo = ttk.Combobox(
            opts_frame, values=list(MODELS.keys()), state="readonly", width=48
        )
        self.model_combo.set(list(MODELS.keys())[0])
        self.model_combo.grid(row=0, column=1, sticky="ew", **padding)

        ttk.Label(opts_frame, text="Output Format:").grid(row=1, column=0, sticky="w", **padding)
        self.format_combo = ttk.Combobox(
            opts_frame, values=list(FORMATS.keys()), state="readonly", width=48
        )
        self.format_combo.set(list(FORMATS.keys())[0])
        self.format_combo.grid(row=1, column=1, sticky="ew", **padding)
        opts_frame.columnconfigure(1, weight=1)

        # --- 4. HMS Stem Cleaner & Gemini On-the-Fly Tuner Panel ---
        hms_frame = ttk.LabelFrame(
            self.root,
            text=" 4. HMS Stem Cleaner & Gemini On-the-Fly Tuner (Stems & Master WAV) ",
        )
        hms_frame.pack(fill="x", **padding)

        self.auto_hms_var = tk.BooleanVar(value=True)
        auto_hms_cb = ttk.Checkbutton(
            hms_frame,
            text="Auto-Clean, Combine & Gemini-Tune 24-Bit Master Automatically After MVSep Download",
            variable=self.auto_hms_var,
        )
        auto_hms_cb.grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 2))

        ttk.Label(hms_frame, text="HMS Mix Style Mode:").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        self.mix_mode_combo = ttk.Combobox(
            hms_frame, values=list(MIX_MODES.keys()), state="readonly", width=48
        )
        self.mix_mode_combo.set(list(MIX_MODES.keys())[0])
        self.mix_mode_combo.grid(row=1, column=1, columnspan=3, sticky="ew", padx=10, pady=4)

        hms_btn_row = ttk.Frame(hms_frame)
        hms_btn_row.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(4, 6))

        self.hms_dry_btn = ttk.Button(
            hms_btn_row,
            text="HMS Dry-Run Folder...",
            command=lambda: self.run_manual_hms_folder(mode="dry_run"),
        )
        self.hms_dry_btn.pack(side="left", padx=(0, 5))

        self.hms_manual_btn = ttk.Button(
            hms_btn_row,
            text="Combine & Tune Stems Folder...",
            command=lambda: self.run_manual_hms_folder(mode="live"),
        )
        self.hms_manual_btn.pack(side="left", padx=5)

        self.hms_master_wav_btn = ttk.Button(
            hms_btn_row,
            text="✨ Tune Master Mix WAV...",
            command=self.run_tune_master_wav_clicked,
        )
        self.hms_master_wav_btn.pack(side="left", padx=5)

        self.hms_gui_btn = ttk.Button(
            hms_btn_row,
            text="Launch HMS GUI",
            command=lambda: invoke_hms_stem_cleaner_bridge(
                target_path=None, mode="launch_gui", log_callback=self.log
            ),
        )
        self.hms_gui_btn.pack(side="left", padx=5)

        self.api_srv_btn = ttk.Button(
            hms_btn_row,
            text="Start Local API (:8765)",
            command=self.toggle_local_api_server,
        )
        self.api_srv_btn.pack(side="left", padx=6)
        hms_frame.columnconfigure(1, weight=1)

        # --- 5. Process Control ---
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", **padding)

        self.start_btn = ttk.Button(
            action_frame, text="🚀 Start Stem Separation", command=self.start_separation_thread
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.cancel_btn = ttk.Button(
            action_frame, text="Cancel", command=self.cancel_separation, state="disabled"
        )
        self.cancel_btn.pack(side="right")

        # --- 6. Status Log Display ---
        log_frame = ttk.LabelFrame(self.root, text=" Status & Progress Log ")
        log_frame.pack(fill="both", expand=True, **padding)

        self.log_area = scrolledtext.ScrolledText(log_frame, wrap="word", height=12)
        self.log_area.pack(fill="both", expand=True, padx=5, pady=5)
        self.log("Ready. API keys load automatically from ~/.mvsep_hms_config.json.")

        # Auto-load persisted MVSep API token, Gemini API key & Mix Style Mode on startup
        saved_cfg = load_saved_config(log_callback=self.log)
        if saved_cfg.get("mvsep_api_token"):
            self.api_entry.insert(0, saved_cfg["mvsep_api_token"])
        if saved_cfg.get("gemini_api_key"):
            self.gemini_entry.insert(0, saved_cfg["gemini_api_key"])
        if saved_cfg.get("mix_mode_label") in MIX_MODES:
            self.mix_mode_combo.set(saved_cfg["mix_mode_label"])

    def get_selected_mix_style(self):
        label = self.mix_mode_combo.get()
        return MIX_MODES.get(label, "auto")

    def save_token_clicked(self):
        mvsep_token = self.api_entry.get().strip()
        gemini_key = self.gemini_entry.get().strip()
        if not mvsep_token and not gemini_key:
            messagebox.showwarning(
                "Empty Keys",
                "Please enter your MVSep API Token and/or Gemini API Key before saving.",
            )
            return
        if save_config_to_disk(
            mvsep_key=mvsep_token,
            gemini_key=gemini_key,
            mix_mode_label=self.mix_mode_combo.get(),
            log_callback=self.log,
        ):
            messagebox.showinfo(
                "API Keys Saved",
                f"Your MVSep API Token and Gemini API Key have been saved to:\n{CONFIG_FILE_PATH}\n\n"
                "Both apps will load them automatically on startup.",
            )

    def toggle_local_api_server(self):
        if getattr(self, "_hms_api_srv", None):
            self._hms_api_srv.shutdown()
            self._hms_api_srv = None
            self.api_srv_btn.config(text="Start Local API (:8765)")
            self.log("[INFO] Stopped Local HMS REST API Server.")
        elif ai_bridge:
            srv, _ = ai_bridge.start_local_hms_api_server(port=8765, log_callback=self.log)
            if srv:
                self._hms_api_srv = srv
                self.api_srv_btn.config(text="Stop Local API (:8765)")

    def toggle_key_visibility(self):
        char = "" if self.show_key_var.get() else "*"
        self.api_entry.config(show=char)
        self.gemini_entry.config(show=char)

    def browse_file(self):
        selected_file = filedialog.askopenfilename(
            title="Select WAV Audio File",
            filetypes=[
                ("WAV Audio Files", "*.wav"),
                ("All Audio Files", "*.wav *.flac *.mp3 *.m4a"),
                ("All Files", "*.*"),
            ],
        )
        if selected_file:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, selected_file)

    def _set_buttons_busy(self, busy=True):
        state = "disabled" if busy else "normal"
        self.start_btn.config(state=state)
        self.hms_dry_btn.config(state=state)
        self.hms_manual_btn.config(state=state)
        self.hms_master_wav_btn.config(state=state)

    def run_manual_hms_folder(self, mode="live"):
        picked_dir = filedialog.askdirectory(title="Select Folder Containing Raw WAV Stems")
        if not picked_dir:
            return
        chosen_style = self.get_selected_mix_style()
        mvsep_token = self.api_entry.get().strip()
        gemini_key = self.gemini_entry.get().strip()
        save_config_to_disk(mvsep_token, gemini_key, self.mix_mode_combo.get(), log_callback=self.log)

        self._set_buttons_busy(True)

        def _worker():
            try:
                invoke_hms_stem_cleaner_bridge(
                    target_path=picked_dir,
                    mode=mode,
                    mix_style=chosen_style,
                    gemini_api_key=gemini_key,
                    log_callback=self.log,
                )
            finally:
                self.finish_process()

        threading.Thread(target=_worker, daemon=True).start()

    def run_tune_master_wav_clicked(self):
        """Lets the user pick any Master Mix WAV file to tune on the fly with Gemini."""
        initial_wav = self.file_entry.get().strip()
        init_dir = os.path.dirname(initial_wav) if initial_wav and os.path.exists(initial_wav) else ""
        picked_wav = filedialog.askopenfilename(
            title="Select Master Mix WAV to Tune On the Fly",
            initialdir=init_dir,
            filetypes=[("WAV Audio Files", "*.wav"), ("All Files", "*.*")],
        )
        if not picked_wav:
            return

        chosen_style = self.get_selected_mix_style()
        mvsep_token = self.api_entry.get().strip()
        gemini_key = self.gemini_entry.get().strip()
        save_config_to_disk(mvsep_token, gemini_key, self.mix_mode_combo.get(), log_callback=self.log)

        self._set_buttons_busy(True)

        def _worker():
            try:
                invoke_hms_stem_cleaner_bridge(
                    target_path=picked_wav,
                    mode="tune_master_wav",
                    mix_style=chosen_style,
                    gemini_api_key=gemini_key,
                    log_callback=self.log,
                )
            finally:
                self.finish_process()

        threading.Thread(target=_worker, daemon=True).start()

    def log(self, message):
        self.ui_events.put(("log", message))

    def process_ui_events(self):
        while True:
            try:
                event, value = self.ui_events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self.log_area.insert(tk.END, f"{value}\n")
                self.log_area.see(tk.END)
            elif event == "finished":
                self._set_buttons_busy(False)
                self.cancel_btn.config(state="disabled")

        self.root.after(100, self.process_ui_events)

    def cancel_separation(self):
        self.cancel_event.set()
        self.cancel_btn.config(state="disabled")
        self.log(
            "Cancellation requested. The current HTTP request may finish first; "
            "this does not cancel a job already submitted to MVSep."
        )

    def start_separation_thread(self):
        api_key = self.api_entry.get().strip()
        gemini_key = self.gemini_entry.get().strip()
        file_path = self.file_entry.get().strip()

        if not api_key:
            messagebox.showwarning("Missing API Token", "Please enter your MVSep API token.")
            return

        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("Invalid File", "Please select a valid audio file.")
            return

        # Automatically persist both MVSep and Gemini API keys whenever a job starts
        save_config_to_disk(
            mvsep_key=api_key,
            gemini_key=gemini_key,
            mix_mode_label=self.mix_mode_combo.get(),
            log_callback=self.log,
        )

        model_name = self.model_combo.get()
        format_name = self.format_combo.get()
        auto_clean = self.auto_hms_var.get()
        chosen_style = self.get_selected_mix_style()

        self.cancel_event.clear()
        self._set_buttons_busy(True)
        self.cancel_btn.config(state="normal")

        thread = threading.Thread(
            target=self.run_separation_pipeline,
            args=(api_key, gemini_key, file_path, model_name, format_name, auto_clean, chosen_style),
            daemon=True,
        )
        thread.start()

    def run_separation_pipeline(
        self, api_key, gemini_key, file_path, model_name, format_name, auto_clean, chosen_style
    ):
        try:
            if self.cancel_event.is_set():
                self.log("Cancelled before the audio upload started.")
                return

            sep_type = MODELS[model_name]
            output_format = FORMATS[format_name]

            filename = os.path.basename(file_path)
            self.log(f"\n--- Starting Job for: {filename} ---")
            self.log(f"• Model: {model_name} (sep_type={sep_type})")
            self.log(f"• Format: {format_name} (output_format={output_format})")
            self.log(f"• HMS Mix Style: {chosen_style.upper()}")

            res_data = upload_audio_to_mvsep_with_retry(
                api_key=api_key,
                file_path=file_path,
                sep_type=sep_type,
                output_format=output_format,
                cancel_event=self.cancel_event,
                log_callback=self.log,
            )

            if not res_data:
                self.log("❌ Upload failed after maximum retries.")
                return

            if not res_data.get("success"):
                err_msg = res_data.get("data", {}).get("message", "Unknown error")
                self.log(f"❌ Creation Failed: {err_msg}")
                return

            job_hash = res_data["data"]["hash"]
            self.log(f"✅ Job accepted by MVSep! Hash ID: {job_hash}")
            self.log("Waiting in GPU processing queue...")

            deadline = time.monotonic() + MAX_POLL_SECONDS
            while True:
                if self.cancel_event.is_set():
                    self.log("Stopped waiting for the job. The remote MVSep job may continue.")
                    return

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.log("❌ Stopped polling: the six-hour wait limit was reached.")
                    return

                if self.cancel_event.wait(min(POLL_INTERVAL, remaining)):
                    self.log("Stopped waiting for the job. The remote MVSep job may continue.")
                    return

                poll_resp = requests.get(
                    API_GET_URL,
                    params={"hash": job_hash},
                    timeout=REQUEST_TIMEOUT,
                )
                if poll_resp.status_code != 200:
                    self.log(f"⚠️ Status check warning: HTTP {poll_resp.status_code}")
                    continue

                poll_json = poll_resp.json()
                if not poll_json.get("success"):
                    self.log("❌ Separation status query failed.")
                    return

                status = poll_json.get("status", "unknown")
                data_block = poll_json.get("data", {})

                if status == "waiting":
                    q_count = data_block.get("queue_count", "?")
                    q_order = data_block.get("current_order", "?")
                    self.log(f"⏳ Status: WAITING (Queue Position: {q_order}, Total Ahead: {q_count})")
                elif status in ["processing", "distributing", "merging"]:
                    self.log(f"⚡ Status: {status.upper()} (GPU active)...")
                elif status == "done":
                    self.log("🎉 Separation Complete!")
                    saved_paths = self.download_results(data_block, os.path.dirname(file_path))

                    # --- AUTOMATIC HMS STEM CLEANER + GEMINI ON-THE-FLY HOOK ---
                    if saved_paths and not self.cancel_event.is_set():
                        song_workspace = prepare_hms_song_workspace(
                            input_audio_path=file_path,
                            downloaded_paths=saved_paths,
                            log_callback=self.log,
                        )
                        self.last_prepared_song_dir = song_workspace
                        if auto_clean and song_workspace:
                            ok_hms = invoke_hms_stem_cleaner_bridge(
                                target_path=song_workspace,
                                mode="live",
                                mix_style=chosen_style,
                                gemini_api_key=gemini_key,
                                log_callback=self.log,
                            )
                            if ok_hms and ai_bridge:
                                report = ai_bridge.generate_ai_mix_and_suno_report(
                                    song_name=os.path.basename(song_workspace),
                                    telemetry={"workspace": song_workspace, "model": model_name, "mix_style": chosen_style},
                                    mix_style=chosen_style,
                                    api_key=gemini_key,
                                    log_callback=self.log,
                                )
                                rep_path = os.path.join(song_workspace, "AI_MIX_AND_SUNO_REPORT.json")
                                with open(rep_path, "w", encoding="utf-8") as _rf:
                                    json.dump(report, _rf, indent=2)
                                self.log(f"[SUCCESS] Saved AI Mix & Suno Report -> {rep_path}")
                    return
                elif status in ["failed", "not_found"]:
                    reason = data_block.get("message", "Job processing failed.")
                    self.log(f"❌ Separation Failed: {reason}")
                    return
                else:
                    self.log(f"❌ Unexpected separation status: {status!r}. Stopping polling.")
                    return

        except requests.RequestException as ex:
            self.log(f"❌ Network error: {ex}")
        except (OSError, ValueError, KeyError, TypeError) as ex:
            self.log(f"❌ Could not process the MVSep response or audio file: {ex}")
        except Exception as ex:
            self.log(f"❌ Unexpected error: {ex}")
        finally:
            self.finish_process()

    @staticmethod
    def output_path(download_dir, file_name):
        file_name = os.path.basename(str(file_name).replace("\\", "/"))
        invalid_chars = '<>:"/\\|?*'
        file_name = "".join(
            "_" if char in invalid_chars or ord(char) < 32 else char
            for char in file_name
        ).rstrip(" .")
        if not file_name or file_name in {".", ".."}:
            return None

        stem, extension = os.path.splitext(file_name)
        target_path = os.path.join(download_dir, file_name)
        suffix = 1
        while os.path.exists(target_path):
            target_path = os.path.join(download_dir, f"{stem} ({suffix}){extension}")
            suffix += 1
        return target_path

    def download_results(self, data_block, download_dir):
        files_list = data_block.get("files", [])
        zip_link = data_block.get("link")
        downloads = []
        saved_paths = []

        if isinstance(files_list, list) and files_list:
            self.log(f"Found {len(files_list)} output stem file(s). Downloading...")
            for item in files_list:
                if not isinstance(item, dict):
                    self.log("⚠️ Skipping an invalid output file entry.")
                    downloads.append(False)
                    continue
                download_url = item.get("url") or item.get("link")
                file_name = item.get("name")
                if not file_name and download_url:
                    file_name = unquote(urlparse(download_url).path.rsplit("/", 1)[-1])
                target_path = self.output_path(download_dir, file_name or "")

                if not download_url or not target_path:
                    self.log("⚠️ Skipping an output entry without a valid URL or filename.")
                    downloads.append(False)
                    continue

                self.log(f"Downloading: {os.path.basename(target_path)}...")
                ok = self.stream_download(download_url, target_path)
                downloads.append(ok)
                if ok:
                    saved_paths.append(target_path)
        elif zip_link:
            file_name = unquote(urlparse(zip_link).path.rsplit("/", 1)[-1]) or "stems.zip"
            target_path = self.output_path(download_dir, file_name)
            if not target_path:
                self.log("⚠️ The ZIP response did not contain a valid filename.")
                downloads.append(False)
            else:
                self.log(f"Downloading ZIP archive: {os.path.basename(target_path)}...")
                ok = self.stream_download(zip_link, target_path)
                downloads.append(ok)
                if ok:
                    saved_paths.append(target_path)
        else:
            self.log("⚠️ No direct download links found in response.")
            return []

        succeeded = sum(downloads)
        failed = len(downloads) - succeeded
        if failed:
            self.log(f"⚠️ Downloads finished with {succeeded} successful and {failed} failed.")
        else:
            self.log(f"✨ All {succeeded} download(s) completed successfully.")

        return saved_paths

    def stream_download(self, url, save_path):
        if self.cancel_event.is_set():
            self.log(f"Download cancelled before starting: {os.path.basename(save_path)}")
            return False

        created_file = False
        completed = False
        try:
            with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                with open(save_path, "xb") as output_file:
                    created_file = True
                    for chunk in response.iter_content(chunk_size=16384):
                        if self.cancel_event.is_set():
                            raise InterruptedError("Download cancelled.")
                        if chunk:
                            output_file.write(chunk)
                    if self.cancel_event.is_set():
                        raise InterruptedError("Download cancelled.")
            completed = True
            self.log(f"Saved -> {save_path}")
            return True
        except InterruptedError:
            self.log(f"Download cancelled: {os.path.basename(save_path)}")
        except (requests.RequestException, OSError) as ex:
            self.log(f"❌ Error downloading {os.path.basename(save_path)}: {ex}")
        finally:
            if created_file and not completed:
                try:
                    os.remove(save_path)
                except FileNotFoundError:
                    pass
                except OSError as ex:
                    self.log(f"⚠️ Could not remove incomplete file {os.path.basename(save_path)}: {ex}")

        return False

    def finish_process(self):
        self.ui_events.put(("finished", None))


def main():
    root = tk.Tk()
    app = MVSepGUIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()