# Save as: C:\github\projects\hms-stem-cleaner\hms_unified_studio_app.py
# Run in PowerShell: python.exe C:\github\projects\hms-stem-cleaner\hms_unified_studio_app.py

import os
import queue
import shutil
import sys
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
# REPOSITORY PATHS & GLOBAL CONSTANTS
# ==============================================================================
HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
MVSEP_REPO_DIR = r"C:\github\projects\mvsep-api-gui"

for p in (HMS_REPO_DIR, MVSEP_REPO_DIR):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

API_CREATE_URL = "https://mvsep.com/api/separation/create"
API_GET_URL = "https://mvsep.com/api/separation/get"
REQUEST_TIMEOUT = (15, 600)
POLL_INTERVAL = 10
MAX_POLL_SECONDS = 6 * 60 * 60

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

FORMATS = {
    "WAV (Uncompressed, 16-bit)": 1,
    "FLAC (Lossless, 16-bit)": 2,
    "FLAC (Lossless, 24-bit)": 5,
    "MP3 (320 kbps)": 0,
    "WAV (Uncompressed, 32-bit)": 4,
}

MIX_STYLE_OPTIONS = {
    "Auto-Detect (Telemetry Driven)": "auto",
    "Heavy Metal / Industrial (Mid-Side Vocal Carve)": "heavy",
    "Acoustic / Dynamic Rock (Preserve Center Guitars/Solos)": "acoustic",
}


# ==============================================================================
# FUNCTION 1: MODULE & CREDENTIAL LOADER
# ==============================================================================
def load_unified_studio_modules(hms_dir=HMS_REPO_DIR, mvsep_dir=MVSEP_REPO_DIR, log_callback=print):
    """
    Loads hms_stem_cleaner_app, hms_mix_json_manager, hms_gemini_tuner, and
    hms_ai_api_bridge with explicit diagnostic boundaries.
    """
    log_callback("=" * 70)
    log_callback("[RUN] Initializing 337 West Unified Studio Suite Modules...")
    mods = {
        "hms": None,
        "json_mgr": None,
        "gemini_tuner": None,
        "ai_bridge": None,
    }

    for key, mod_name in (
        ("hms", "hms_stem_cleaner_app"),
        ("json_mgr", "hms_mix_json_manager"),
        ("gemini_tuner", "hms_gemini_tuner"),
        ("ai_bridge", "hms_ai_api_bridge"),
    ):
        try:
            mods[key] = __import__(mod_name)
            log_callback(f"[SUCCESS] Loaded module: {mod_name}")
        except Exception as ex:
            log_callback(f"[INFO] Optional/Sub-module '{mod_name}' not loaded ({ex})")

    return mods


# ==============================================================================
# FUNCTION 2: MVSEP CLOUD SEPARATION + AUTOMATIC HANDOFF TO TAB 2
# ==============================================================================
def stage_downloaded_stems_into_folder(input_audio_path, downloaded_paths, log_callback=print):
    """
    Moves downloaded MVSep stems (or extracts a downloaded MVSep .zip archive)
    into <Parent_Dir>/<Song_Name>_Stems/ for clean HMS processing.
    """
    log_callback(f"[RUN] Staging downloaded stems for: {os.path.basename(input_audio_path)}")
    try:
        parent_dir = os.path.dirname(os.path.abspath(input_audio_path))
        raw_base = os.path.splitext(os.path.basename(input_audio_path))[0]
        clean_name = "".join("_" if c in '<>:"/\\|?* ' else c for c in raw_base).strip("_") or "MVSep_Song"
        workspace_dir = os.path.join(parent_dir, f"{clean_name}_Stems")
        os.makedirs(workspace_dir, exist_ok=True)

        staged = 0
        for p in downloaded_paths:
            if not p or not os.path.isfile(p):
                continue
            if p.lower().endswith(".zip"):
                with zipfile.ZipFile(p, "r") as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        safe_name = os.path.basename(member.filename)
                        if not safe_name:
                            continue
                        dst = os.path.join(workspace_dir, safe_name)
                        with zf.open(member) as sf, open(dst, "wb") as df:
                            shutil.copyfileobj(sf, df)
                        staged += 1
            else:
                dst = os.path.join(workspace_dir, os.path.basename(p))
                if os.path.abspath(p) != os.path.abspath(dst):
                    shutil.move(p, dst)
                staged += 1

        log_callback(f"[SUCCESS] Staged {staged} stem(s) into -> {workspace_dir}")
        return workspace_dir if staged > 0 else None
    except Exception:
        log_callback("[ERROR] Failed staging MVSep stems:")
        log_callback(traceback.format_exc())
        return None


# ==============================================================================
# UNIFIED STUDIO SUITE DARK-MODE TABBED GUI
# ==============================================================================
class HMSUnifiedStudioGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("337 West Productions — Unified MVSep Cloud Splitter & HMS 9-Slider VST3 Studio (v1.2)")
        self.root.geometry("1040x860")
        self.root.minsize(960, 780)
        self.root.configure(bg="#121212")

        self.ui_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.api_server_running = False

        # Load backend modules
        self.mods = load_unified_studio_modules(log_callback=self.enqueue_log)
        self.hms = self.mods["hms"]
        self.json_mgr = self.mods["json_mgr"]
        self.gemini_tuner = self.mods["gemini_tuner"]
        self.ai_bridge = self.mods["ai_bridge"]

        self._setup_dark_styles()
        self._build_top_credentials_bar()
        self._build_notebook_tabs()
        self._build_shared_log_console()
        self._load_saved_credentials()

        # Redirect print statements from hms_stem_cleaner_app into our shared log console
        self._install_stdout_redirector()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll_ui_queue)

    def _setup_dark_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TNotebook", background="#121212", borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background="#1f1f1f",
            foreground="#aaaaaa",
            padding=[16, 8],
            font=("Consolas", 10, "bold"),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", "#1e4620")],
            foreground=[("selected", "#00ff88")],
        )

    def _build_top_credentials_bar(self):
        top_bar = tk.LabelFrame(
            self.root,
            text=" 🔑 Shared Studio Credentials & Local REST API (~/.mvsep_hms_config.json) ",
            bg="#1a1a1a",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5,
        )
        top_bar.pack(fill="x", padx=12, pady=(8, 4))
        top_bar.columnconfigure(1, weight=1)
        top_bar.columnconfigure(3, weight=1)

        tk.Label(top_bar, text="MVSep Token:", bg="#1a1a1a", fg="#cccccc", font=("Consolas", 9)).grid(row=0, column=0, sticky="w", padx=4)
        self.mvsep_key_var = tk.StringVar()
        self.mvsep_entry = tk.Entry(top_bar, textvariable=self.mvsep_key_var, show="*", bg="#111111", fg="#00ff88", insertbackground="#00ff88", font=("Consolas", 9))
        self.mvsep_entry.grid(row=0, column=1, sticky="ew", padx=4)

        tk.Label(top_bar, text="Gemini API Key:", bg="#1a1a1a", fg="#cccccc", font=("Consolas", 9)).grid(row=0, column=2, sticky="w", padx=4)
        self.gemini_key_var = tk.StringVar()
        self.gemini_entry = tk.Entry(top_bar, textvariable=self.gemini_key_var, show="*", bg="#111111", fg="#61afef", insertbackground="#61afef", font=("Consolas", 9))
        self.gemini_entry.grid(row=0, column=3, sticky="ew", padx=4)

        self.show_keys_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            top_bar,
            text="Show",
            variable=self.show_keys_var,
            command=self._toggle_keys,
            bg="#1a1a1a",
            fg="#cccccc",
            selectcolor="#111111",
            activebackground="#1a1a1a",
            font=("Consolas", 8),
        ).grid(row=0, column=4, padx=4)

        tk.Button(
            top_bar,
            text="💾 Save Keys",
            command=self.save_credentials_clicked,
            bg="#1e4620",
            fg="#ffffff",
            font=("Consolas", 8, "bold"),
            padx=8,
            pady=2,
        ).grid(row=0, column=5, padx=4)

        self.api_btn = tk.Button(
            top_bar,
            text="🌐 Start API (:8765)",
            command=self.toggle_local_api_server,
            bg="#2c3e50",
            fg="#89b4fa",
            font=("Consolas", 8, "bold"),
            padx=8,
            pady=2,
        )
        self.api_btn.grid(row=0, column=6, padx=4)

    def _build_notebook_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="x", padx=12, pady=4)

        self.tab_mvsep = tk.Frame(self.notebook, bg="#161616")
        self.tab_hms = tk.Frame(self.notebook, bg="#161616")

        self.notebook.add(self.tab_mvsep, text=" ☁️ TAB 1: MVSep Cloud Stem Splitter ")
        self.notebook.add(self.tab_hms, text=" 🎛️ TAB 2: HMS 9-Slider VST3 Cleaner & Master Mixer ")

        self._populate_tab1_mvsep()
        self._populate_tab2_hms_mixer()

        # Default to Tab 2 if user launches directly for mixing, or click Tab 1 anytime
        self.notebook.select(self.tab_hms)

    def _populate_tab1_mvsep(self):
        pad = {"padx": 12, "pady": 6}
        f_frame = tk.LabelFrame(
            self.tab_mvsep,
            text=" 1. Select Master Song WAV / FLAC / MP3 for MVSep Separation ",
            bg="#1c1c1c",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=8,
        )
        f_frame.pack(fill="x", **pad)
        f_frame.columnconfigure(1, weight=1)

        tk.Label(f_frame, text="Audio File:", bg="#1c1c1c", fg="#dddddd", font=("Consolas", 9)).grid(row=0, column=0, sticky="w", padx=6)
        self.mvsep_file_var = tk.StringVar()
        tk.Entry(f_frame, textvariable=self.mvsep_file_var, bg="#111111", fg="#ffffff", insertbackground="#ffffff", font=("Consolas", 9)).grid(row=0, column=1, sticky="ew", padx=6)
        tk.Button(f_frame, text="Browse...", command=self._browse_mvsep_audio, bg="#333333", fg="#ffffff", font=("Consolas", 9, "bold"), padx=10).grid(row=0, column=2, padx=6)

        o_frame = tk.LabelFrame(
            self.tab_mvsep,
            text=" 2. Cloud Separation Model & Automatic Tab 2 Handoff ",
            bg="#1c1c1c",
            fg="#61afef",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=8,
        )
        o_frame.pack(fill="x", **pad)
        o_frame.columnconfigure(1, weight=1)

        tk.Label(o_frame, text="Separation Model:", bg="#1c1c1c", fg="#dddddd", font=("Consolas", 9)).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.model_combo = ttk.Combobox(o_frame, values=list(MODELS.keys()), state="readonly")
        self.model_combo.set(list(MODELS.keys())[0])
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        tk.Label(o_frame, text="Output Format   :", bg="#1c1c1c", fg="#dddddd", font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.format_combo = ttk.Combobox(o_frame, values=list(FORMATS.keys()), state="readonly")
        self.format_combo.set("FLAC (Lossless, 24-bit)")
        self.format_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        self.auto_handoff_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            o_frame,
            text="Automatically switch to Tab 2, AI Auto-Tune, Clean Stems & Render 24-Bit Master when download finishes",
            variable=self.auto_handoff_var,
            bg="#1c1c1c",
            fg="#00ff88",
            selectcolor="#111111",
            activebackground="#1c1c1c",
            font=("Consolas", 9, "bold"),
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=6)

        act_row = tk.Frame(self.tab_mvsep, bg="#161616")
        act_row.pack(fill="x", padx=12, pady=8)

        self.btn_start_mvsep = tk.Button(
            act_row,
            text="🚀 START MVSEP CLOUD SEPARATION",
            command=self.start_mvsep_job,
            bg="#1e4620",
            fg="#ffffff",
            font=("Consolas", 10, "bold"),
            pady=6,
        )
        self.btn_start_mvsep.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_cancel_mvsep = tk.Button(
            act_row,
            text="✖ Cancel Poll",
            command=self.cancel_mvsep_job,
            state="disabled",
            bg="#5a1e1e",
            fg="#ffffff",
            font=("Consolas", 10, "bold"),
             padx=14,
            pady=6,
        )
        self.btn_cancel_mvsep.pack(side="right")

    def _populate_tab2_hms_mixer(self):
        # 1. Directories & Mix Style Mode
        dir_frame = tk.LabelFrame(
            self.tab_hms,
            text=" Active Song Stem Directory & Mix Style Mode ",
            bg="#1c1c1c",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5,
        )
        dir_frame.pack(fill="x", padx=10, pady=(6, 3))
        dir_frame.columnconfigure(1, weight=1)

        tk.Label(dir_frame, text="Source Song Dir:", bg="#1c1c1c", fg="#dddddd", font=("Consolas", 9)).grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.source_dir_var = tk.StringVar()
        tk.Entry(dir_frame, textvariable=self.source_dir_var, bg="#111111", fg="#00ff88", insertbackground="#00ff88", font=("Consolas", 9)).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        tk.Button(dir_frame, text="Browse", command=self._browse_hms_source, bg="#333333", fg="#ffffff", font=("Consolas", 8, "bold"), padx=8).grid(row=0, column=2, padx=4)

        tk.Label(dir_frame, text="Dest Root Dir  :", bg="#1c1c1c", fg="#dddddd", font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=4, pady=2)
        default_dest = r"C:\Users\racer\OneDrive\Documents\Image-Line\FL Studio\Projects"
        self.dest_dir_var = tk.StringVar(value=default_dest if os.path.isdir(default_dest) else "")
        tk.Entry(dir_frame, textvariable=self.dest_dir_var, bg="#111111", fg="#00ff88", insertbackground="#00ff88", font=("Consolas", 9)).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        tk.Button(dir_frame, text="Browse", command=self._browse_hms_dest, bg="#333333", fg="#ffffff", font=("Consolas", 8, "bold"), padx=8).grid(row=1, column=2, padx=4)

        tk.Label(dir_frame, text="Mix Style Mode :", bg="#1c1c1c", fg="#f9e2af", font=("Consolas", 9, "bold")).grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.mix_style_label_var = tk.StringVar(value=list(MIX_STYLE_OPTIONS.keys())[0])
        self.mix_style_combo = ttk.Combobox(dir_frame, textvariable=self.mix_style_label_var, values=list(MIX_STYLE_OPTIONS.keys()), state="readonly")
        self.mix_style_combo.grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        self.mix_style_combo.bind("<<ComboboxSelected>>", self._on_mix_style_changed)

        self.move_files_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            dir_frame,
            text="Move Raw Stems (Backed up in Rollback Vault)",
            variable=self.move_files_var,
            bg="#1c1c1c",
            fg="#cccccc",
            selectcolor="#111111",
            activebackground="#1c1c1c",
            font=("Consolas", 8),
        ).grid(row=2, column=2, padx=4)

        # 2. All 9 Live Sliders (4 Balance/Gate + 5 VST3/Limiter Levers)
        s_frame = tk.LabelFrame(
            self.tab_hms,
            text=" 🎚️ 9-Slider Live Mix Balance, Anti-Echo Gate & C++ VST3 Bus Levers (Auto-Saved to JSON) ",
            bg="#1c1c1c",
            fg="#f9e2af",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5,
        )
        s_frame.pack(fill="x", padx=10, pady=3)
        s_frame.columnconfigure(1, weight=1)
        s_frame.columnconfigure(3, weight=1)

        self.vocals_weight_var = tk.DoubleVar(value=1.08)
        self.rhythm_weight_var = tk.DoubleVar(value=1.04)
        self.music_weight_var = tk.DoubleVar(value=0.90)
        self.vocal_gate_db_var = tk.DoubleVar(value=-33.0)
        self.nova_pocket_db_var = tk.DoubleVar(value=-2.5)
        self.mjuc_compress_var = tk.DoubleVar(value=18.0)
        self.mjuc_makeup_var = tk.DoubleVar(value=1.5)
        self.chow_drive_var = tk.DoubleVar(value=0.35)
        self.master_ceiling_var = tk.DoubleVar(value=-0.3)

        # Row 0: Vocals & Rhythm
        tk.Label(s_frame, text="Vocals Level (Green):", bg="#1c1c1c", fg="#00ff88", font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", padx=4)
        tk.Scale(s_frame, variable=self.vocals_weight_var, from_=0.40, to=1.60, resolution=0.02, orient="horizontal", bg="#1c1c1c", fg="#00ff88", troughcolor="#111111", highlightthickness=0, length=160).grid(row=0, column=1, sticky="ew", padx=4)

        tk.Label(s_frame, text="Rhythm Level (Red)  :", bg="#1c1c1c", fg="#ff5555", font=("Consolas", 9, "bold")).grid(row=0, column=2, sticky="w", padx=8)
        tk.Scale(s_frame, variable=self.rhythm_weight_var, from_=0.40, to=1.60, resolution=0.02, orient="horizontal", bg="#1c1c1c", fg="#ff5555", troughcolor="#111111", highlightthickness=0, length=160).grid(row=0, column=3, sticky="ew", padx=4)

        # Row 1: Music & Vocal Gate
        tk.Label(s_frame, text="Music Level (Blue)  :", bg="#1c1c1c", fg="#61afef", font=("Consolas", 9, "bold")).grid(row=1, column=0, sticky="w", padx=4)
        tk.Scale(s_frame, variable=self.music_weight_var, from_=0.40, to=1.60, resolution=0.02, orient="horizontal", bg="#1c1c1c", fg="#61afef", troughcolor="#111111", highlightthickness=0, length=160).grid(row=1, column=1, sticky="ew", padx=4)

        tk.Label(s_frame, text="Vocal Gate (dB)     :", bg="#1c1c1c", fg="#f39c12", font=("Consolas", 9, "bold")).grid(row=1, column=2, sticky="w", padx=8)
        tk.Scale(s_frame, variable=self.vocal_gate_db_var, from_=-48.0, to=-18.0, resolution=0.5, orient="horizontal", bg="#1c1c1c", fg="#f39c12", troughcolor="#111111", highlightthickness=0, length=160).grid(row=1, column=3, sticky="ew", padx=4)

        # Row 2: Vocal Pocket & MJUCjr Compress
        tk.Label(s_frame, text="Vocal Pocket (dB)   :", bg="#1c1c1c", fg="#ff88aa", font=("Consolas", 9, "bold")).grid(row=2, column=0, sticky="w", padx=4)
        tk.Scale(s_frame, variable=self.nova_pocket_db_var, from_=-6.0, to=0.0, resolution=0.1, orient="horizontal", bg="#1c1c1c", fg="#ff88aa", troughcolor="#111111", highlightthickness=0, length=160).grid(row=2, column=1, sticky="ew", padx=4)

        tk.Label(s_frame, text="Vocal Comp (MJUCjr) :", bg="#1c1c1c", fg="#ff88aa", font=("Consolas", 9, "bold")).grid(row=2, column=2, sticky="w", padx=8)
        tk.Scale(s_frame, variable=self.mjuc_compress_var, from_=0.0, to=40.0, resolution=0.5, orient="horizontal", bg="#1c1c1c", fg="#ff88aa", troughcolor="#111111", highlightthickness=0, length=160).grid(row=2, column=3, sticky="ew", padx=4)

        # Row 3: Vocal Makeup & Rhythm Tape Drive
        tk.Label(s_frame, text="Vocal Makeup (dB)   :", bg="#1c1c1c", fg="#fab387", font=("Consolas", 9, "bold")).grid(row=3, column=0, sticky="w", padx=4)
        tk.Scale(s_frame, variable=self.mjuc_makeup_var, from_=0.0, to=6.0, resolution=0.1, orient="horizontal", bg="#1c1c1c", fg="#fab387", troughcolor="#111111", highlightthickness=0, length=160).grid(row=3, column=1, sticky="ew", padx=4)

        tk.Label(s_frame, text="Rhythm Tape Drive   :", bg="#1c1c1c", fg="#fab387", font=("Consolas", 9, "bold")).grid(row=3, column=2, sticky="w", padx=8)
        tk.Scale(s_frame, variable=self.chow_drive_var, from_=0.0, to=1.0, resolution=0.02, orient="horizontal", bg="#1c1c1c", fg="#fab387", troughcolor="#111111", highlightthickness=0, length=160).grid(row=3, column=3, sticky="ew", padx=4)

        # Row 4: Master Ceiling + Preset & AI Tuning Buttons
        tk.Label(s_frame, text="Master Ceiling (dB) :", bg="#1c1c1c", fg="#a6e3a1", font=("Consolas", 9, "bold")).grid(row=4, column=0, sticky="w", padx=4)
        tk.Scale(s_frame, variable=self.master_ceiling_var, from_=-2.0, to=-0.1, resolution=0.1, orient="horizontal", bg="#1c1c1c", fg="#a6e3a1", troughcolor="#111111", highlightthickness=0, length=160).grid(row=4, column=1, sticky="ew", padx=4)

        p_row = tk.Frame(s_frame, bg="#1c1c1c")
        p_row.grid(row=4, column=2, columnspan=2, sticky="ew", padx=6, pady=3)

        tk.Button(p_row, text="0. AI AUTO-TUNE", command=self.run_ai_autotune_clicked, bg="#5b2c6f", fg="#ffffff", font=("Consolas", 8, "bold"), padx=6, pady=3).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(p_row, text="💾 Save JSON", command=self.save_mix_json_clicked, bg="#1e4620", fg="#ffffff", font=("Consolas", 8, "bold"), padx=6, pady=3).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(p_row, text="📂 Load JSON", command=self.load_mix_json_clicked, bg="#1b3a57", fg="#ffffff", font=("Consolas", 8, "bold"), padx=6, pady=3).pack(side="left", expand=True, fill="x", padx=2)
        tk.Button(p_row, text="↺ Reset 9", command=self.reset_all_9_sliders, bg="#333333", fg="#ffffff", font=("Consolas", 8, "bold"), padx=6, pady=3).pack(side="left", expand=True, fill="x", padx=2)

        # 3. Primary Execution & Gemini Master WAV Tuning Bar
        exec_frame = tk.LabelFrame(
            self.tab_hms,
            text=" 🚀 Headless 64-Bit VST3 Execution, Instant Bus Re-Glue & Gemini Master Tuner ",
            bg="#1c1c1c",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6,
        )
        exec_frame.pack(fill="x", padx=10, pady=(2, 6))

        b_row = tk.Frame(exec_frame, bg="#1c1c1c")
        b_row.pack(fill="x")

        tk.Button(b_row, text="1. DRY-RUN AUDIT", command=lambda: self.run_hms_pipeline(dry_run=True), bg="#1b3a57", fg="#ffffff", font=("Consolas", 9, "bold"), pady=5).pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(b_row, text="2. FULL LIVE CLEAN + MASTER", command=lambda: self.run_hms_pipeline(dry_run=False), bg="#1e5631", fg="#ffffff", font=("Consolas", 9, "bold"), pady=5).pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(b_row, text="3. GLUE BUSES & MASTER ONLY (3s)", command=self.run_glue_master_only, bg="#7d4e00", fg="#ffffff", font=("Consolas", 9, "bold"), pady=5).pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(b_row, text="✨ GEMINI TUNE MASTER WAV", command=self.run_gemini_tune_master_wav, bg="#4a235a", fg="#00ff88", font=("Consolas", 9, "bold"), pady=5).pack(side="left", expand=True, fill="x", padx=3)
        tk.Button(b_row, text="4. ROLLBACK", command=self.run_rollback_clicked, bg="#6e1414", fg="#ffffff", font=("Consolas", 9, "bold"), pady=5).pack(side="left", padx=3)

    def _build_shared_log_console(self):
        log_frame = tk.LabelFrame(
            self.root,
            text=" 📜 Live Studio Telemetry & VST3 / MVSep Progress Console ",
            bg="#121212",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=4,
        )
        log_frame.pack(fill="both", expand=True, padx=12, pady=(2, 10))

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            height=10,
            bg="#0b0b0b",
            fg="#00ff88",
            insertbackground="#00ff88",
            font=("Consolas", 9),
        )
        self.log_box.pack(fill="both", expand=True)
        self.enqueue_log("[INFO] 337 West Unified Studio Suite Ready! Switch between Tab 1 (MVSep) and Tab 2 (HMS 9-Slider Mixer) anytime.")

    # ==========================================================================
    # LOGGING & CREDENTIALS HELPERS
    # ==========================================================================
    def _install_stdout_redirector(self):
        orig_out = sys.__stdout__
        gui_ref = self

        class _Redirector:
            def write(self, text):
                if orig_out:
                    try:
                        orig_out.write(text)
                    except Exception:
                        pass
                if text and text.strip():
                    for line in text.rstrip().splitlines():
                        gui_ref.enqueue_log(line)

            def flush(self):
                if orig_out:
                    try:
                        orig_out.flush()
                    except Exception:
                        pass

        sys.stdout = _Redirector()

    def enqueue_log(self, msg):
        self.ui_queue.put(("log", str(msg)))

    def _poll_ui_queue(self):
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_box.insert(tk.END, payload + "\n")
                self.log_box.see(tk.END)
            elif kind == "mvsep_done":
                self.btn_start_mvsep.config(state="normal")
                self.btn_cancel_mvsep.config(state="disabled")
        self.root.after(80, self._poll_ui_queue)

    def _toggle_keys(self):
        ch = "" if self.show_keys_var.get() else "*"
        self.mvsep_entry.config(show=ch)
        self.gemini_entry.config(show=ch)

    def _load_saved_credentials(self):
        if self.ai_bridge and hasattr(self.ai_bridge, "load_ai_credentials"):
            creds = self.ai_bridge.load_ai_credentials(log_callback=self.enqueue_log)
            if creds.get("mvsep_api_token"):
                self.mvsep_key_var.set(creds["mvsep_api_token"])
            if creds.get("gemini_api_key"):
                self.gemini_key_var.set(creds["gemini_api_key"])

    def save_credentials_clicked(self):
        if self.ai_bridge and hasattr(self.ai_bridge, "save_ai_credentials"):
            ok = self.ai_bridge.save_ai_credentials(
                mvsep_token=self.mvsep_key_var.get().strip(),
                gemini_key=self.gemini_key_var.get().strip(),
                log_callback=self.enqueue_log,
            )
            if ok:
                messagebox.showinfo("Credentials Saved", "Saved MVSep Token & Gemini API Key to ~/.mvsep_hms_config.json!")

    def toggle_local_api_server(self):
        if not self.ai_bridge:
            return
        if not self.api_server_running:
            ok = self.ai_bridge.start_local_hms_api_server(port=8765, log_callback=self.enqueue_log)
            if ok:
                self.api_server_running = True
                self.api_btn.config(text="🛑 Stop API (:8765)", bg="#5a1e1e")
        else:
            self.ai_bridge.stop_local_hms_api_server(log_callback=self.enqueue_log)
            self.api_server_running = False
            self.api_btn.config(text="🌐 Start API (:8765)", bg="#2c3e50")

    # ==========================================================================
    # TAB 2: 9-SLIDER & JSON PRESET ACTIONS
    # ==========================================================================
    def get_bus_weights(self):
        return {
            "Vocals": round(float(self.vocals_weight_var.get()), 3),
            "Rhythm": round(float(self.rhythm_weight_var.get()), 3),
            "Music": round(float(self.music_weight_var.get()), 3),
        }

    def get_vst_overrides(self):
        return {
            "nova_music_pocket_db": round(float(self.nova_pocket_db_var.get()), 2),
            "mjuc_compress": round(float(self.mjuc_compress_var.get()), 2),
            "mjuc_makeup": round(float(self.mjuc_makeup_var.get()), 2),
            "chow_rhythm_drive": round(float(self.chow_drive_var.get()), 3),
            "master_ceiling_db": round(float(self.master_ceiling_var.get()), 2),
        }

    def get_active_mix_style_key(self):
        return MIX_STYLE_OPTIONS.get(self.mix_style_label_var.get(), "auto")

    def _on_mix_style_changed(self, _event=None):
        mode = self.get_active_mix_style_key()
        if self.hms:
            setattr(self.hms, "HMS_MIX_STYLE_ACTIVE", mode)
        if mode == "acoustic":
            self.vocals_weight_var.set(0.92)
            self.rhythm_weight_var.set(0.96)
            self.music_weight_var.set(1.02)
            self.vocal_gate_db_var.set(-34.0)
            self.nova_pocket_db_var.set(0.0)
        elif mode == "heavy":
            self.vocals_weight_var.set(1.08)
            self.rhythm_weight_var.set(1.04)
            self.music_weight_var.set(0.90)
            self.vocal_gate_db_var.set(-33.0)
            self.nova_pocket_db_var.set(-2.8)
        self.enqueue_log(f"[INFO] Switched Mix Style Mode -> '{mode}'")

    def apply_preset_dict(self, preset):
        if not isinstance(preset, dict):
            return
        bw = preset.get("bus_weights", {})
        if "Vocals" in bw:
            self.vocals_weight_var.set(round(float(bw["Vocals"]), 2))
        if "Rhythm" in bw:
            self.rhythm_weight_var.set(round(float(bw["Rhythm"]), 2))
        if "Music" in bw:
            self.music_weight_var.set(round(float(bw["Music"]), 2))
        if "vocal_gate_db" in preset:
            self.vocal_gate_db_var.set(round(float(preset["vocal_gate_db"]), 1))

        vst = preset.get("vst_overrides", {})
        if "nova_music_pocket_db" in vst:
            self.nova_pocket_db_var.set(round(float(vst["nova_music_pocket_db"]), 2))
        if "mjuc_compress" in vst:
            self.mjuc_compress_var.set(round(float(vst["mjuc_compress"]), 2))
        if "mjuc_makeup" in vst:
            self.mjuc_makeup_var.set(round(float(vst["mjuc_makeup"]), 2))
        if "chow_rhythm_drive" in vst:
            self.chow_drive_var.set(round(float(vst["chow_rhythm_drive"]), 3))
        if "master_ceiling_db" in vst:
            self.master_ceiling_var.set(round(float(vst["master_ceiling_db"]), 2))

    def reset_all_9_sliders(self):
        self.vocals_weight_var.set(1.08)
        self.rhythm_weight_var.set(1.04)
        self.music_weight_var.set(0.90)
        self.vocal_gate_db_var.set(-33.0)
        self.nova_pocket_db_var.set(-2.5)
        self.mjuc_compress_var.set(18.0)
        self.mjuc_makeup_var.set(1.5)
        self.chow_drive_var.set(0.35)
        self.master_ceiling_var.set(-0.3)
        self.enqueue_log("[INFO] Reset all 9 sliders to studio defaults.")

    def _browse_hms_source(self):
        chosen = filedialog.askdirectory(title="Select Song Folder Containing WAV Stems")
        if chosen:
            self.source_dir_var.set(chosen)
            if self.json_mgr:
                existing = self.json_mgr.load_song_mix_json(chosen, log_callback=lambda m: None)
                if existing:
                    self.apply_preset_dict(existing)
                    self.enqueue_log(f"[INFO] Auto-loaded saved JSON preset: {os.path.basename(existing['json_path'])}")

    def _browse_hms_dest(self):
        chosen = filedialog.askdirectory(title="Select Destination Root Folder")
        if chosen:
            self.dest_dir_var.set(chosen)

    def save_mix_json_clicked(self):
        if not self.json_mgr:
            return
        target_dir = self.source_dir_var.get().strip() or filedialog.askdirectory(title="Select Song Folder")
        if not target_dir:
            return
        saved = self.json_mgr.save_song_mix_json(
            song_dir=target_dir,
            bus_weights=self.get_bus_weights(),
            vocal_gate_db=float(self.vocal_gate_db_var.get()),
            mix_style=self.get_active_mix_style_key(),
            vst_overrides=self.get_vst_overrides(),
            log_callback=self.enqueue_log,
        )
        if saved:
            messagebox.showinfo("Mix JSON Saved", f"Saved 9-slider preset to:\n{saved}")

    def load_mix_json_clicked(self):
        if not self.json_mgr:
            return
        f_path = filedialog.askopenfilename(
            title="Select Song Mix Settings JSON",
            filetypes=[("Mix Settings JSON", "*_MIX_SETTINGS.json *.json"), ("All Files", "*.*")],
        )
        if not f_path:
            return
        loaded = self.json_mgr.load_song_mix_json(f_path, log_callback=self.enqueue_log)
        if loaded:
            self.apply_preset_dict(loaded)

    def run_ai_autotune_clicked(self):
        src = self.source_dir_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Select Source Folder", "Please select a valid Source Song Dir first.")
            return

        def _worker():
            try:
                if self.gemini_tuner and hasattr(self.gemini_tuner, "extract_audio_snippet_and_telemetry"):
                    tele = self.gemini_tuner.extract_audio_snippet_and_telemetry(src, log_callback=self.enqueue_log)
                    tune = self.gemini_tuner.request_gemini_live_tuning(
                        tele,
                        api_key=self.gemini_key_var.get().strip(),
                        log_callback=self.enqueue_log,
                    )
                    self.root.after(0, lambda: self.apply_preset_dict(tune))
                elif self.hms and hasattr(self.hms, "analyze_and_autotune_song"):
                    tune = self.hms.analyze_and_autotune_song(src)
                    self.root.after(0, lambda: self.apply_preset_dict(tune))
            except Exception:
                self.enqueue_log(traceback.format_exc())

        threading.Thread(target=_worker, daemon=True).start()

    def run_hms_pipeline(self, dry_run=False):
        src = self.source_dir_var.get().strip()
        dst = self.dest_dir_var.get().strip() or None
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Missing Source Dir", "Please select a valid Source Song Dir.")
            return

        weights = self.get_bus_weights()
        gate_db = float(self.vocal_gate_db_var.get())
        vst_ov = self.get_vst_overrides()
        move_raw = bool(self.move_files_var.get())
        setattr(self.hms, "HMS_MIX_STYLE_ACTIVE", self.get_active_mix_style_key())

        def _worker():
            try:
                res = self.hms.execute_stem_cleanup(
                    source_dir=src,
                    dest_root=dst,
                    dry_run=dry_run,
                    move_source_files=move_raw,
                    render_master=True,
                    vocal_gate_db=gate_db,
                    bus_weights=weights,
                    vst_overrides=vst_ov,
                )
                out_dir = res.get("dest_song_dir") or src
                if not dry_run and self.json_mgr and os.path.isdir(out_dir):
                    self.json_mgr.save_song_mix_json(
                        song_dir=out_dir,
                        bus_weights=weights,
                        vocal_gate_db=gate_db,
                        mix_style=self.get_active_mix_style_key(),
                        vst_overrides=vst_ov,
                        log_callback=self.enqueue_log,
                    )
            except Exception:
                self.enqueue_log(traceback.format_exc())

        threading.Thread(target=_worker, daemon=True).start()

    def run_glue_master_only(self):
        src = self.source_dir_var.get().strip()
        dst = self.dest_dir_var.get().strip()
        target_dir = src
        if dst and src:
            candidate = os.path.join(dst, os.path.basename(os.path.normpath(src)))
            if os.path.isdir(candidate):
                target_dir = candidate

        if not target_dir or not os.path.isdir(target_dir):
            messagebox.showwarning("Missing Cleaned Song Dir", "Select a cleaned song folder containing Vocals, Rhythm, and Music subfolders.")
            return

        weights = self.get_bus_weights()
        gate_db = float(self.vocal_gate_db_var.get())
        vst_ov = self.get_vst_overrides()

        def _worker():
            try:
                self.hms.render_master_mixdown(
                    dest_song_dir=target_dir,
                    bus_weights=weights,
                    vocal_gate_db=gate_db,
                    vst_overrides=vst_ov,
                )
                if self.json_mgr:
                    self.json_mgr.save_song_mix_json(
                        song_dir=target_dir,
                        bus_weights=weights,
                        vocal_gate_db=gate_db,
                        mix_style=self.get_active_mix_style_key(),
                        vst_overrides=vst_ov,
                        log_callback=self.enqueue_log,
                    )
            except Exception:
                self.enqueue_log(traceback.format_exc())

        threading.Thread(target=_worker, daemon=True).start()

    def run_gemini_tune_master_wav(self):
        wav_file = filedialog.askopenfilename(
            title="Select Rendered MASTER_MIX.wav for On-the-Fly Gemini Tuning",
            filetypes=[("WAV Audio", "*.wav"), ("All Files", "*.*")],
        )
        if not wav_file or not self.gemini_tuner:
            return

        def _worker():
            try:
                res = self.gemini_tuner.run_on_the_fly_gemini_mix_loop(
                    target_path=wav_file,
                    api_key=self.gemini_key_var.get().strip(),
                    log_callback=self.enqueue_log,
                )
                if isinstance(res, dict) and "tuning" in res:
                    self.root.after(0, lambda: self.apply_preset_dict(res["tuning"]))
            except Exception:
                self.enqueue_log(traceback.format_exc())

        threading.Thread(target=_worker, daemon=True).start()

    def run_rollback_clicked(self):
        src = self.source_dir_var.get().strip()
        if not src:
            messagebox.showwarning("Select Song Dir", "Select the song folder you wish to restore from the Rollback Vault.")
            return
        song_name = os.path.basename(os.path.normpath(src))
        if hasattr(self.hms, "restore_song_checkpoint"):
            threading.Thread(target=lambda: self.hms.restore_song_checkpoint(song_name), daemon=True).start()

    # ==========================================================================
    # TAB 1: MVSEP CLOUD SPLITTER ACTIONS
    # ==========================================================================
    def _browse_mvsep_audio(self):
        f = filedialog.askopenfilename(
            title="Select Master Song File to Split",
            filetypes=[("Audio Files", "*.wav *.flac *.mp3 *.m4a"), ("All Files", "*.*")],
        )
        if f:
            self.mvsep_file_var.set(f)

    def cancel_mvsep_job(self):
        self.cancel_event.set()
        self.enqueue_log("[INFO] Cancellation requested for active MVSep poll loop.")

    def start_mvsep_job(self):
        token = self.mvsep_key_var.get().strip()
        audio_path = self.mvsep_file_var.get().strip()
        if not token:
            messagebox.showwarning("Missing MVSep Token", "Enter your MVSep API token in the top bar.")
            return
        if not audio_path or not os.path.isfile(audio_path):
            messagebox.showwarning("Missing Audio File", "Select a valid audio file to upload.")
            return

        self.save_credentials_clicked()
        self.cancel_event.clear()
        self.btn_start_mvsep.config(state="disabled")
        self.btn_cancel_mvsep.config(state="normal")

        sep_type = MODELS[self.model_combo.get()]
        out_fmt = FORMATS[self.format_combo.get()]
        auto_handoff = bool(self.auto_handoff_var.get())

        threading.Thread(
            target=self._mvsep_worker,
            args=(token, audio_path, sep_type, out_fmt, auto_handoff),
            daemon=True,
        ).start()

    def _mvsep_worker(self, token, audio_path, sep_type, out_fmt, auto_handoff):
        try:
            self.enqueue_log("=" * 70)
            self.enqueue_log(f"[RUN] Uploading '{os.path.basename(audio_path)}' to MVSep (sep_type={sep_type})...")
            with open(audio_path, "rb") as f_obj:
                resp = requests.post(
                    API_CREATE_URL,
                    data={"api_token": token, "sep_type": sep_type, "output_format": out_fmt},
                    files={"audiofile": f_obj},
                    timeout=REQUEST_TIMEOUT,
                )
            res_json = resp.json()
            if not res_json.get("success"):
                self.enqueue_log(f"[ERROR] MVSep Create Failed: {res_json}")
                return

            job_hash = res_json["data"]["hash"]
            self.enqueue_log(f"[SUCCESS] MVSep Job Accepted! Hash: {job_hash}")

            deadline = time.monotonic() + MAX_POLL_SECONDS
            while time.monotonic() < deadline and not self.cancel_event.is_set():
                if self.cancel_event.wait(POLL_INTERVAL):
                    break
                p_resp = requests.get(API_GET_URL, params={"hash": job_hash}, timeout=(15, 60))
                p_json = p_resp.json()
                status = p_json.get("status", "unknown")
                data_block = p_json.get("data", {})

                if status in ("waiting", "processing", "distributing", "merging"):
                    self.enqueue_log(f"[INFO] MVSep Status: {status.upper()}...")
                elif status == "done":
                    self.enqueue_log("[SUCCESS] MVSep Separation Complete! Downloading stems...")
                    dl_dir = os.path.dirname(os.path.abspath(audio_path))
                    saved_files = []
                    for item in data_block.get("files", []):
                        url = item.get("url") or item.get("link")
                        fname = item.get("name") or unquote(urlparse(url).path.rsplit("/", 1)[-1])
                        target = os.path.join(dl_dir, os.path.basename(fname))
                        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
                            r.raise_for_status()
                            with open(target, "wb") as out_f:
                                for chunk in r.iter_content(chunk_size=32768):
                                    if chunk:
                                        out_f.write(chunk)
                        saved_files.append(target)
                        self.enqueue_log(f"[INFO] Downloaded -> {os.path.basename(target)}")

                    staged_dir = stage_downloaded_stems_into_folder(audio_path, saved_files, log_callback=self.enqueue_log)
                    if staged_dir:
                        self.root.after(0, lambda: self.source_dir_var.set(staged_dir))
                        self.root.after(0, lambda: self.notebook.select(self.tab_hms))
                        if auto_handoff:
                            self.enqueue_log("[RUN] Auto-Handoff -> Running AI Auto-Tune & Full 9-Slider VST3 Clean...")
                            self.root.after(200, lambda: self.run_hms_pipeline(dry_run=False))
                    return
                else:
                    self.enqueue_log(f"[ERROR] MVSep stopped with status: {status}")
                    return
        except Exception:
            self.enqueue_log(traceback.format_exc())
        finally:
            self.ui_queue.put(("mvsep_done", None))

    def _on_close(self):
        self.cancel_event.set()
        sys.stdout = sys.__stdout__
        self.root.destroy()
        os._exit(0)


def main():
    if "--self-test" in sys.argv:
        mods = load_unified_studio_modules()
        assert mods["hms"] is not None, "hms_stem_cleaner_app failed to load!"
        assert mods["json_mgr"] is not None, "hms_mix_json_manager failed to load!"
        print("[SUCCESS] Unified Studio Suite headless self-test passed 100%!")
        return

    root = tk.Tk()
    HMSUnifiedStudioGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()