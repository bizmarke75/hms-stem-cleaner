# Save as: C:\github\projects\hms-stem-cleaner\upgrade_and_build_all.py
# Run in PowerShell: python.exe .\upgrade_and_build_all.py

import os
import py_compile
import subprocess
import sys
import traceback

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
HMS_APP_SCRIPT = os.path.join(HMS_REPO_DIR, "hms_stem_cleaner_app.py")
HMS_BUILD_SCRIPT = os.path.join(HMS_REPO_DIR, "build_standalone_exe.py")


# ==============================================================================
# FUNCTION 1: INJECT MIX STYLE MODE SWITCH INTO HMS_STEM_CLEANER_APP.PY
# ==============================================================================
def inject_mix_mode_into_hms_gui(app_script_path=HMS_APP_SCRIPT):
    """
    Adds the Mix Style Mode Switch (Auto-Detect, Acoustic / Dynamic Rock,
    Heavy Metal / Industrial) into hms_stem_cleaner_app.py and wires it to
    both the GUI sliders and the Mid/Side vocal-bleed processor.
    """
    print("=" * 75)
    print(f"[RUN] Adding Mix Style Mode Switch to: {app_script_path}")
    print("=" * 75)

    if not os.path.isfile(app_script_path):
        print(f"[ERROR] Target script not found: {app_script_path}")
        return False

    try:
        with open(app_script_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check if already patched
        if "HMS_MIX_STYLE_ACTIVE" in code:
            print("[INFO] Mix Style Mode Switch is already present in hms_stem_cleaner_app.py.")
            return True

        # 1. Inject global mode state + auto-detector helper right before suppress_vocal_bleed_in_music
        helper_block = '''
# ==============================================================================
# MIX STYLE MODE SWITCH (AUTO / ACOUSTIC DYNAMIC ROCK / HEAVY METAL)
# ==============================================================================
HMS_MIX_STYLE_ACTIVE = "auto"
HMS_MIX_MODES = {
    "Auto-Detect (Smart Telemetry)": "auto",
    "Acoustic / Dynamic Rock (Preserve Center Guitars)": "acoustic",
    "Heavy Metal / Industrial (Nu-Metal Wall & Mid/Side Pocket)": "heavy",
}


def resolve_hms_mix_style(song_dir, requested_mode=None):
    """
    Resolves 'auto' mode into either 'acoustic' or 'heavy' by checking the song
    folder name and measuring Mid vs. Side energy on Guitar/Music stems.
    """
    mode = (requested_mode or HMS_MIX_STYLE_ACTIVE or "auto").lower()
    if mode in ("acoustic", "heavy"):
        return mode

    if song_dir and os.path.isdir(song_dir):
        lower_dir = os.path.basename(os.path.normpath(song_dir)).lower()
        if any(k in lower_dir for k in ("acoustic", "unplugged", "solo", "ballad", "folk")):
            print("[INFO] [MODE AUTO-DETECT] Filename keyword matched -> ACOUSTIC / DYNAMIC ROCK mode.")
            return "acoustic"

        try:
            for r, _, files in os.walk(song_dir):
                for fn in files:
                    if fn.lower().endswith(".wav") and any(
                        g in fn.lower() for g in ("guitar", "other", "music", "acoustic")
                    ):
                        with AudioFile(os.path.join(r, fn)) as af:
                            buf = af.read(min(af.frames, int(af.samplerate * 60)))
                        if buf.shape[0] >= 2:
                            mid_rms = np.sqrt(np.mean((0.5 * (buf[0] + buf[1])) ** 2) + 1e-12)
                            side_rms = np.sqrt(np.mean((0.5 * (buf[0] - buf[1])) ** 2) + 1e-12)
                            if float(20.0 * np.log10(mid_rms / side_rms)) > 3.5:
                                print("[INFO] [MODE AUTO-DETECT] Center-dominant Guitar stem -> ACOUSTIC / DYNAMIC ROCK mode.")
                                return "acoustic"
        except Exception:
            pass

    print("[INFO] [MODE AUTO-DETECT] Wide stereo Guitar/Music wall -> HEAVY METAL / INDUSTRIAL mode.")
    return "heavy"
'''

        if "def suppress_vocal_bleed_in_music(" in code:
            code = code.replace(
                "def suppress_vocal_bleed_in_music(",
                helper_block + "\n\ndef suppress_vocal_bleed_in_music(",
                1,
            )
            # Make suppress_vocal_bleed_in_music bypass center carving when in 'acoustic' mode
            code = code.replace(
                "def suppress_vocal_bleed_in_music(music_buf, vocals_buf, sr):",
                "def suppress_vocal_bleed_in_music(music_buf, vocals_buf, sr):\n"
                "    if HMS_MIX_STYLE_ACTIVE == 'acoustic':\n"
                "        print('[INFO] [ACOUSTIC MODE] Bypassing Mid-channel guitar carve to preserve centered guitars & solos.')\n"
                "        return music_buf",
                1,
            )
            print("[SUCCESS] Injected resolve_hms_mix_style() and Acoustic bypass into suppress_vocal_bleed_in_music().")

        # 2. Add Mix Style Mode selector into the GUI slider frame if present
        gui_Reset_anchor = "        btn_reset_sliders = tk.Button("
        gui_mode_widget = '''        # Row 2: Mix Style Mode Selector (Auto / Acoustic / Heavy Metal)
        tk.Label(slider_frame, text="Mix Style Mode      :", bg="#1e1e1e", fg="#c678dd", font=("Consolas", 9, "bold")).grid(row=2, column=0, sticky="w", padx=(2, 6), pady=(4, 2))
        self.mix_style_var = tk.StringVar(value=list(HMS_MIX_MODES.keys())[0])
        self.mix_style_menu = tk.OptionMenu(
            slider_frame, self.mix_style_var, *list(HMS_MIX_MODES.keys()), command=self.on_mix_style_changed
        )
        self.mix_style_menu.configure(bg="#222222", fg="#00ff88", activebackground="#333333", activeforeground="#ffffff", font=("Consolas", 9), highlightthickness=0)
        self.mix_style_menu.grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=(4, 2))

'''
        if gui_Reset_anchor in code:
            code = code.replace(gui_Reset_anchor, gui_mode_widget + gui_Reset_anchor, 1)

        # 3. Add on_mix_style_changed handler right before reset_slider_defaults
        method_anchor = "    def reset_slider_defaults(self):"
        method_block = '''    def on_mix_style_changed(self, selected_label):
        """Updates HMS_MIX_STYLE_ACTIVE and pre-sets sliders for Acoustic vs. Heavy mode."""
        global HMS_MIX_STYLE_ACTIVE
        mode_key = HMS_MIX_MODES.get(selected_label, "auto")
        HMS_MIX_STYLE_ACTIVE = mode_key
        if mode_key == "acoustic":
            self.vocals_weight_var.set(0.90)
            self.rhythm_weight_var.set(1.02)
            self.music_weight_var.set(0.98)
            self.vocal_gate_db_var.set(-38.0)
            self.vst_overrides = {"mjuc_compress": 14.0, "mjuc_makeup": 0.5, "nova_music_pocket_db": -1.0}
            self.log_status("[INFO] Switched to ACOUSTIC / DYNAMIC ROCK: Vocals=0.90, Rhythm=1.02, Music=0.98, Gate=-38dB (Center Guitars Preserved)\\n")
        elif mode_key == "heavy":
            self.vocals_weight_var.set(1.05)
            self.rhythm_weight_var.set(1.00)
            self.music_weight_var.set(0.92)
            self.vocal_gate_db_var.set(-36.0)
            self.vst_overrides = {"mjuc_compress": 18.0, "mjuc_makeup": 1.0, "nova_music_pocket_db": -3.2}
            self.log_status("[INFO] Switched to HEAVY METAL / INDUSTRIAL: Vocals=1.05, Rhythm=1.00, Music=0.92, Gate=-36dB (Mid/Side Pocket Active)\\n")
        else:
            self.log_status("[INFO] Switched to AUTO-DETECT mode (evaluates song folder & stem telemetry on run).\\n")

'''
        if method_anchor in code:
            code = code.replace(method_anchor, method_block + method_anchor, 1)
            print("[SUCCESS] Added Mix Style Mode selector and slider preset handler to HMS GUI.")

        # 4. Resolve 'auto' mode inside execute_stem_cleanup before processing stems
        exec_anchor = "def execute_stem_cleanup("
        if exec_anchor in code:
            code = code.replace(
                "    print(\"=\" * 75)\n    print(f\"[RUN] Starting HMS Stem Cleanup",
                "    global HMS_MIX_STYLE_ACTIVE\n"
                "    HMS_MIX_STYLE_ACTIVE = resolve_hms_mix_style(source_dir, HMS_MIX_STYLE_ACTIVE)\n"
                "    print(\"=\" * 75)\n    print(f\"[RUN] Starting HMS Stem Cleanup",
                1,
            )

        # Write atomically and verify Python syntax
        temp_path = f"{app_script_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(code)
        py_compile.compile(temp_path, doraise=True)
        os.replace(temp_path, app_script_path)
        print(f"[SUCCESS] Syntax verified and saved: {app_script_path}")
        return True

    except Exception:
        print("[ERROR] Failed injecting Mix Style Mode into hms_stem_cleaner_app.py:")
        print(traceback.format_exc())
        return False


# ==============================================================================
# FUNCTION 2: LOCATE MVSEP_GUI.PY & REBUILD BOTH STANDALONE .EXE FILES
# ==============================================================================
def find_mvsep_gui_script():
    """Finds mvsep_gui.py across your common project directories."""
    candidates = [
        os.path.join(HMS_REPO_DIR, "mvsep_gui.py"),
        r"C:\github\projects\mvsep_gui.py",
        r"H:\suno projects\mvsep_gui.py",
        os.path.expanduser(r"~\Desktop\mvsep_gui.py"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # Search C:\github\projects and H:\suno projects
    for search_root in (r"C:\github\projects", r"H:\suno projects"):
        if os.path.isdir(search_root):
            for r, dirs, files in os.walk(search_root):
                dirs[:] = [d for d in dirs if d not in {".git", "build", "dist", "__pycache__", ".venv", "venv"}]
                if "mvsep_gui.py" in files:
                    return os.path.join(r, "mvsep_gui.py")
    return None


def compile_both_standalone_executables(mvsep_custom_path=None):
    """
    Compiles both dist\\HMS_Stem_Cleaner.exe and dist\\MVSep_Stem_Separator.exe
    using PyInstaller and reports their final sizes and paths.
    """
    results = {"hms_exe": None, "mvsep_exe": None}

    # --- Build 1: HMS_Stem_Cleaner.exe ---
    print("\n" + "=" * 75)
    print("[RUN] Building Standalone Executable 1/2: HMS_Stem_Cleaner.exe")
    print("=" * 75)
    try:
        subprocess.run([sys.executable, HMS_BUILD_SCRIPT], cwd=HMS_REPO_DIR, check=True)
        hms_exe = os.path.join(HMS_REPO_DIR, "dist", "HMS_Stem_Cleaner.exe")
        if os.path.isfile(hms_exe):
            results["hms_exe"] = hms_exe
    except Exception:
        print("[ERROR] Failed building HMS_Stem_Cleaner.exe:")
        print(traceback.format_exc())

    # --- Build 2: MVSep_Stem_Separator.exe ---
    mvsep_script = mvsep_custom_path or find_mvsep_gui_script()
    print("\n" + "=" * 75)
    print(f"[RUN] Building Standalone Executable 2/2: MVSep_Stem_Separator.exe (Source: {mvsep_script})")
    print("=" * 75)

    if not mvsep_script or not os.path.isfile(mvsep_script):
        print(
            "[INFO] Could not auto-locate mvsep_gui.py. Pass its path as an argument if it lives in another folder:\n"
            "       python.exe .\\upgrade_and_build_all.py \"C:\\path\\to\\mvsep_gui.py\""
        )
        return results

    try:
        mvsep_dir = os.path.dirname(os.path.abspath(mvsep_script))
        icon_path = os.path.join(mvsep_dir, "assets", "mvsep.ico")

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name", "MVSep_Stem_Separator",
            "--collect-all", "soundfile",
        ]
        if os.path.isfile(icon_path):
            cmd.extend(["--icon", icon_path, "--add-data", f"{icon_path};assets"])
        cmd.append(mvsep_script)

        subprocess.run(cmd, cwd=mvsep_dir, check=True)
        mvsep_exe = os.path.join(mvsep_dir, "dist", "MVSep_Stem_Separator.exe")
        if os.path.isfile(mvsep_exe):
            size_mb = round(os.path.getsize(mvsep_exe) / (1024 * 1024), 2)
            print("=" * 75)
            print(f"[SUCCESS] MVSep_Stem_Separator.exe BUILT SUCCESSFULLY! ({size_mb} MB)")
            print(f"          Executable Path: {mvsep_exe}")
            print("=" * 75)
            results["mvsep_exe"] = mvsep_exe
    except Exception:
        print("[ERROR] Failed building MVSep_Stem_Separator.exe:")
        print(traceback.format_exc())

    return results


if __name__ == "__main__":
    mvsep_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    patch_only = "--patch-only" in sys.argv

    if inject_mix_mode_into_hms_gui():
        if patch_only:
            print("[SUCCESS] --patch-only complete. Run without flags to compile both .exe files!")
        else:
            compile_both_standalone_executables(mvsep_arg)