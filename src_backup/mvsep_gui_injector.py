# Save as: H:\suno projects\mvsep_gui_injector.py
# Run in PowerShell: python.exe .\mvsep_gui_injector.py

import os
import re
import sys
import shutil
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

# Import both the full pipeline and the standalone Master Mixdown engine
from hms_headless_dsp import execute_stem_cleanup, render_master_mixdown

BASE_OUTPUT_DIR = Path(r"C:\Users\racer\OneDrive\Documents\Image-Line\FL Studio\Projects")


class StatusBoxRedirector:
    """
    Intercepts print() logs from hms_headless_dsp.py and streams them live
    into MVSepGUIInjector.status_box while preserving PowerShell console output.
    """
    def __init__(self, text_widget, orig_stdout):
        self.text_widget = text_widget
        self.orig_stdout = orig_stdout

    def write(self, message):
        if self.orig_stdout:
            self.orig_stdout.write(message)
            self.orig_stdout.flush()
        if self.text_widget and message:
            self.text_widget.after(0, self._append, message)

    def _append(self, message):
        try:
            tag = "INFO"
            if "[ERROR]" in message:
                tag = "ERROR"
            elif "[SUCCESS]" in message:
                tag = "SUCCESS"
            elif "[DRY-RUN]" in message:
                tag = "DRYRUN"
            elif "[RUN]" in message:
                tag = "RUN"

            self.text_widget.insert(tk.END, message, tag)
            self.text_widget.see(tk.END)
        except Exception:
            pass

    def flush(self):
        if self.orig_stdout:
            self.orig_stdout.flush()


class MVSepGUIInjector:
    def __init__(self, root):
        self.root = root
        self.root.title("337 West - MVSep Stem Injector & Headless VST3 Master Engine")
        self.root.geometry("860x760")
        self.root.configure(bg="#1e1e1e")

        self.active_source_var = tk.StringVar(value="")
        self.dest_root_var = tk.StringVar(value=str(BASE_OUTPUT_DIR))
        self.move_files_var = tk.BooleanVar(value=False)

        # Mix Balance & Gate Slider Variables (Pre-tuned from Sensory Bleed analysis)
        self.vocals_weight_var = tk.DoubleVar(value=1.18)
        self.rhythm_weight_var = tk.DoubleVar(value=0.92)
        self.music_weight_var = tk.DoubleVar(value=0.76)
        self.vocal_gate_db_var = tk.DoubleVar(value=-36.0)

        title_label = tk.Label(
            root,
            text="337 West - MVSep Stem Sorter & Headless VST3 Master Engine",
            fg="#00ff00",
            bg="#1e1e1e",
            font=("Arial", 13, "bold")
        )
        title_label.pack(pady=(10, 2))

        desc_label = tk.Label(
            root,
            text="Routes stems to <Dest>\\<Song_Name>\\<Vocals|Rhythm|Music>, cleans via VST3, and renders 24-bit Master.",
            fg="#cccccc",
            bg="#1e1e1e",
            font=("Arial", 9)
        )
        desc_label.pack(pady=(0, 8))

        # --- SECTION 1: DIRECTORY PATHS ---
        path_frame = tk.LabelFrame(
            root,
            text=" Active Directories ",
            bg="#1e1e1e",
            fg="#00ff88",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        path_frame.pack(fill="x", padx=14, pady=4)

        tk.Label(path_frame, text="Source Song Dir:", bg="#1e1e1e", fg="#ffffff", font=("Consolas", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(path_frame, textvariable=self.active_source_var, width=72, bg="#111111", fg="#00ff00", insertbackground="#ffffff", font=("Consolas", 9)).grid(row=0, column=1, padx=6, pady=3)
        tk.Button(path_frame, text="Browse", command=self.browse_source_only, bg="#333333", fg="#ffffff", font=("Arial", 8)).grid(row=0, column=2)

        tk.Label(path_frame, text="Dest Root Dir  :", bg="#1e1e1e", fg="#ffffff", font=("Consolas", 9)).grid(row=1, column=0, sticky="w")
        tk.Entry(path_frame, textvariable=self.dest_root_var, width=72, bg="#111111", fg="#00ff00", insertbackground="#ffffff", font=("Consolas", 9)).grid(row=1, column=1, padx=6, pady=3)
        tk.Button(path_frame, text="Browse", command=self.browse_dest_only, bg="#333333", fg="#ffffff", font=("Arial", 8)).grid(row=1, column=2)

        # --- SECTION 2: QUICK FILE / FOLDER SORTER (NO DSP) ---
        sort_frame = tk.LabelFrame(
            root,
            text=" Quick File Rename & Subfolder Sort Only (No VST3 Render) ",
            bg="#1e1e1e",
            fg="#aaaaaa",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        sort_frame.pack(fill="x", padx=14, pady=4)

        btn_files = tk.Button(
            sort_frame,
            text="Select Multiple WAV Files (Quick Sort)",
            command=self.select_files,
            bg="#333333",
            fg="#ffffff",
            font=("Arial", 9),
            width=40
        )
        btn_files.pack(side="left", padx=8, pady=4)

        btn_folder = tk.Button(
            sort_frame,
            text="Select Entire Folder (Quick Sort)",
            command=self.select_folder,
            bg="#333333",
            fg="#ffffff",
            font=("Arial", 9),
            width=40
        )
        btn_folder.pack(side="left", padx=8, pady=4)

        # --- SECTION 3: LIVE MIX BALANCE & VOCAL GATE SLIDERS ---
        slider_frame = tk.LabelFrame(
            root,
            text=" Live Mix Balance & Anti-Echo Gate Levers (Used by Buttons 2 & 3) ",
            bg="#1e1e1e",
            fg="#00d4ff",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6
        )
        slider_frame.pack(fill="x", padx=14, pady=4)

        # Row 0: Vocals Weight (Green) & Rhythm Weight (Red)
        tk.Label(slider_frame, text="Vocals Level (Green):", bg="#1e1e1e", fg="#00ff66", font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(2, 6))
        tk.Scale(
            slider_frame, variable=self.vocals_weight_var, from_=0.50, to=1.60, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#00ff66", highlightthickness=0, troughcolor="#111111"
        ).grid(row=0, column=1, padx=4, pady=2)

        tk.Label(slider_frame, text="Rhythm Level (Red):", bg="#1e1e1e", fg="#ff5555", font=("Consolas", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(16, 6))
        tk.Scale(
            slider_frame, variable=self.rhythm_weight_var, from_=0.50, to=1.50, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#ff5555", highlightthickness=0, troughcolor="#111111"
        ).grid(row=0, column=3, padx=4, pady=2)

        # Row 1: Music Weight (Blue) & Vocal Gate Threshold (dB)
        tk.Label(slider_frame, text="Music Level (Blue)  :", bg="#1e1e1e", fg="#5bc0de", font=("Consolas", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(2, 6))
        tk.Scale(
            slider_frame, variable=self.music_weight_var, from_=0.40, to=1.40, resolution=0.02,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#5bc0de", highlightthickness=0, troughcolor="#111111"
        ).grid(row=1, column=1, padx=4, pady=2)

        tk.Label(slider_frame, text="Vocal Gate (dB)   :", bg="#1e1e1e", fg="#f0ad4e", font=("Consolas", 9, "bold")).grid(row=1, column=2, sticky="w", padx=(16, 6))
        tk.Scale(
            slider_frame, variable=self.vocal_gate_db_var, from_=-60.0, to=-18.0, resolution=1.0,
            orient="horizontal", length=210, bg="#1e1e1e", fg="#f0ad4e", highlightthickness=0, troughcolor="#111111"
        ).grid(row=1, column=3, padx=4, pady=2)

        btn_reset_sliders = tk.Button(
            slider_frame,
            text="Reset Defaults",
            command=self.reset_slider_defaults,
            bg="#333333",
            fg="#ffffff",
            font=("Consolas", 8),
            padx=6,
            pady=4
        )
        btn_reset_sliders.grid(row=0, column=4, rowspan=2, padx=(14, 2))

        # --- SECTION 4: HEADLESS VST3 CLEANUP & MASTER ENGINE ---
        dsp_frame = tk.LabelFrame(
            root,
            text=" Headless VST3 Cleanup & Master Mixdown Engine (Pedalboard) ",
            bg="#1e1e1e",
            fg="#00ff00",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=8
        )
        dsp_frame.pack(fill="x", padx=14, pady=4)

        top_ctrl = tk.Frame(dsp_frame, bg="#1e1e1e")
        top_ctrl.pack(fill="x", pady=(0, 6))

        chk_move = tk.Checkbutton(
            top_ctrl,
            text="Move Raw Stems (instead of Copy)",
            variable=self.move_files_var,
            bg="#1e1e1e",
            fg="#dddddd",
            selectcolor="#111111",
            activebackground="#1e1e1e",
            activeforeground="#ffffff",
            font=("Consolas", 9)
        )
        chk_move.pack(side="left", padx=4)

        btn_row = tk.Frame(dsp_frame, bg="#1e1e1e")
        btn_row.pack(fill="x")

        self.btn_dry_run = tk.Button(
            btn_row,
            text="1. DRY-RUN AUDIT",
            command=lambda: self.run_headless_dsp(dry_run=True),
            bg="#2d5a88",
            fg="#ffffff",
            activebackground="#3d7ab8",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5
        )
        self.btn_dry_run.pack(side="left", padx=4)

        self.btn_live_clean = tk.Button(
            btn_row,
            text="2. FULL LIVE CLEAN + MASTER (24-BIT)",
            command=lambda: self.run_headless_dsp(dry_run=False),
            bg="#1f7a3f",
            fg="#ffffff",
            activebackground="#2ca356",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5
        )
        self.btn_live_clean.pack(side="left", padx=4)

        self.btn_master_only = tk.Button(
            btn_row,
            text="3. GLUE BUSES & RENDER MASTER ONLY",
            command=self.run_master_only,
            bg="#8a4b0f",
            fg="#ffffff",
            activebackground="#b86514",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=5
        )
        self.btn_master_only.pack(side="left", padx=4)

        # --- SECTION 5: STATUS DISPLAY BOX ---
        self.status_box = tk.Text(
            root,
            height=15,
            width=98,
            bg="#111111",
            fg="#00ff00",
            font=("Consolas", 9)
        )
        self.status_box.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        self.status_box.tag_config("INFO", foreground="#cccccc")
        self.status_box.tag_config("RUN", foreground="#5bc0de")
        self.status_box.tag_config("DRYRUN", foreground="#f0ad4e")
        self.status_box.tag_config("SUCCESS", foreground="#00ff00")
        self.status_box.tag_config("ERROR", foreground="#ff5555")

        sys.stdout = StatusBoxRedirector(self.status_box, sys.__stdout__)

        self.log_status("[INFO] Ready! Sliders pre-tuned to Vocals=1.18, Rhythm=0.92, Music=0.76, Gate=-36dB.\n")

    def reset_slider_defaults(self):
        """Resets the 4 sliders back to our Sensory Bleed chorus-cutting defaults."""
        self.vocals_weight_var.set(1.18)
        self.rhythm_weight_var.set(0.92)
        self.music_weight_var.set(0.76)
        self.vocal_gate_db_var.set(-36.0)
        self.log_status("[INFO] Reset sliders to defaults: Vocals=1.18, Rhythm=0.92, Music=0.76, Vocal Gate=-36.0 dB\n")

    def get_current_bus_weights(self) -> dict:
        """Reads the 3 mix balance sliders into a dictionary for render_master_mixdown."""
        return {
            "Vocals": round(float(self.vocals_weight_var.get()), 2),
            "Rhythm": round(float(self.rhythm_weight_var.get()), 2),
            "Music":  round(float(self.music_weight_var.get()), 2)
        }

    def _set_buttons_state(self, state: str):
        for btn in (self.btn_dry_run, self.btn_live_clean, self.btn_master_only):
            btn.configure(state=state)

    def browse_source_only(self):
        folder = filedialog.askdirectory(title="Select Source Song Stem Folder")
        if folder:
            self.active_source_var.set(folder)
            self.log_status(f"[INFO] Active Source Song Folder set to: {folder}\n")

    def browse_dest_only(self):
        folder = filedialog.askdirectory(title="Select Destination Root Folder")
        if folder:
            self.dest_root_var.set(folder)
            self.log_status(f"[INFO] Destination Root Folder set to: {folder}\n")

    def sanitize_song_name(self, raw_folder_name: str) -> str:
        cleaned = re.sub(r'[^a-zA-Z0-9_\-]+', '_', raw_folder_name).strip('_')
        return cleaned if cleaned else "Untitled_Song"

    def clean_filename(self, filename: str, song_name: str = "") -> str:
        name, ext = os.path.splitext(filename)
        name = re.sub(r'\s*\[.*?\]', '', name)
        name = re.sub(r'\s*\(.*?\)', lambda m: "_" + m.group(0).strip(" ()"), name)
        name = re.sub(r'^[0-9]+_[a-fA-F0-9]+_', '', name)
        name = re.sub(r'_[a-fA-F0-9]{8,}', '', name)
        name = re.sub(r'__+', '_', name).strip('_-_ ')
        if song_name and not name.lower().startswith(song_name.lower()):
            name = f"{song_name}_{name}"
        return f"{name}{ext}"

    def determine_subfolder(self, filename: str) -> str:
        lower_name = filename.lower()
        if any(k in lower_name for k in ["vocal", "vocals", "vox", "acapella", "lead", "backing"]):
            return "Vocals"
        elif any(k in lower_name for k in ["drum", "drums", "rhythm", "bass", "percussion", "kick", "snare"]):
            return "Rhythm"
        else:
            return "Music"

    def process_file_path(self, file_path_str):
        file_path = Path(file_path_str)
        if file_path.suffix.lower() == ".wav":
            original_name = file_path.name
            song_name = self.sanitize_song_name(file_path.parent.name)
            cleaned_name = self.clean_filename(original_name, song_name)

            subfolder_name = self.determine_subfolder(original_name)
            dest_root = Path(self.dest_root_var.get().strip() or str(BASE_OUTPUT_DIR))
            target_dir = dest_root / song_name / subfolder_name

            target_dir.mkdir(parents=True, exist_ok=True)
            dest_path = target_dir / cleaned_name

            try:
                if self.move_files_var.get():
                    shutil.move(str(file_path), str(dest_path))
                    self.log_status(f"[SUCCESS] [{song_name}/{subfolder_name}] Moved: {cleaned_name}\n")
                else:
                    shutil.copy2(file_path, dest_path)
                    self.log_status(f"[SUCCESS] [{song_name}/{subfolder_name}] Copied: {cleaned_name}\n")
            except Exception as e:
                self.log_status(f"[ERROR] Failed on {original_name}: {e}\n")

    def select_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select MVSep Stems",
            filetypes=[("WAV Audio Files", "*.wav")]
        )
        if file_paths:
            first_parent = str(Path(file_paths[0]).parent)
            self.active_source_var.set(first_parent)
            self.log_status(f"[RUN] --- Quick-Sorting {len(file_paths)} selected files ---\n")
            for fp in file_paths:
                self.process_file_path(fp)
            messagebox.showinfo("Success", "Stems renamed and sorted into <Song_Name>\\<Bus> subfolders!")

    def select_folder(self):
        folder_path = filedialog.askdirectory(title="Select MVSep Export Folder")
        if folder_path:
            self.active_source_var.set(folder_path)
            folder = Path(folder_path)
            wav_files = list(folder.glob("*.wav"))
            self.log_status(f"[RUN] --- Quick-Sorting folder: {folder.name} ({len(wav_files)} files) ---\n")
            for fp in wav_files:
                self.process_file_path(str(fp))
            messagebox.showinfo("Success", f"Stems sorted into {folder.name}\\Vocals, Rhythm, and Music subfolders!")

    def run_headless_dsp(self, dry_run=True):
        source_dir = self.active_source_var.get().strip()
        dest_root = self.dest_root_var.get().strip() or str(BASE_OUTPUT_DIR)
        move_files = self.move_files_var.get()
        vocal_gate = float(self.vocal_gate_db_var.get())
        weights = self.get_current_bus_weights()

        if not source_dir:
            picked = filedialog.askdirectory(title="Select Song Folder for Headless VST3 Cleanup")
            if not picked:
                return
            source_dir = picked
            self.active_source_var.set(source_dir)

        if not os.path.exists(source_dir):
            messagebox.showerror("Error", f"Source folder does not exist:\n{source_dir}")
            return

        self._set_buttons_state("disabled")

        def _worker():
            try:
                summary = execute_stem_cleanup(
                    source_dir=source_dir,
                    dest_root=dest_root,
                    dry_run=dry_run,
                    move_source_files=move_files,
                    render_master=True,
                    vocal_gate_db=vocal_gate,
                    bus_weights=weights
                )
                if not dry_run and summary.get("processed_count", 0) > 0:
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "HMS VST3 Cleanup & Master Complete",
                            f"Song: {summary['song_name']}\n"
                            f"Cleaned 24-Bit Stems: {summary['processed_count']}\n"
                            f"Mix Weights: V={weights['Vocals']} | R={weights['Rhythm']} | M={weights['Music']}\n"
                            f"Master File:\n{summary.get('master_wav_path')}"
                        )
                    )
            except Exception:
                print("[ERROR] Unhandled exception in Headless VST3 Worker:")
                print(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_buttons_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def run_master_only(self):
        """
        Directly glues existing Vocals/Rhythm/Music subfolders and renders
        <Song_Name>_MASTER_MIX.wav using the live Mix Balance Sliders.
        """
        dest_root = self.dest_root_var.get().strip() or str(BASE_OUTPUT_DIR)
        source_dir = self.active_source_var.get().strip()
        weights = self.get_current_bus_weights()

        candidate_song_dir = None
        if source_dir:
            song_name = self.sanitize_song_name(os.path.basename(os.path.normpath(source_dir)))
            possible_path = os.path.join(dest_root, song_name)
            if os.path.exists(possible_path):
                candidate_song_dir = possible_path

        if not candidate_song_dir:
            init_dir = dest_root if os.path.exists(dest_root) else os.getcwd()
            picked = filedialog.askdirectory(
                initialdir=init_dir,
                title="Select Processed Song Folder (Containing Vocals / Rhythm / Music)"
            )
            if not picked:
                return
            candidate_song_dir = picked

        self._set_buttons_state("disabled")

        def _worker():
            try:
                res = render_master_mixdown(
                    dest_song_dir=candidate_song_dir,
                    bus_weights=weights
                )
                if res.get("master_wav_path"):
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Master Mixdown Complete",
                            f"Mix Weights: V={weights['Vocals']} | R={weights['Rhythm']} | M={weights['Music']}\n"
                            f"Peak Level: {res.get('peak_db')} dBFS\n"
                            f"Master File:\n{res.get('master_wav_path')}"
                        )
                    )
            except Exception:
                print("[ERROR] Unhandled exception in Master Mixdown Worker:")
                print(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_buttons_state("normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def log_status(self, message):
        self.status_box.insert(tk.END, message)
        self.status_box.see(tk.END)


if __name__ == "__main__":
    root = tk.Tk()
    app = MVSepGUIInjector(root)
    root.mainloop()