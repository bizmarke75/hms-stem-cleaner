# Save as: C:\github\projects\hms-stem-cleaner\build_standalone_exe.py
# Run in PowerShell: python.exe C:\github\projects\hms-stem-cleaner\build_standalone_exe.py

import os
import sys
import subprocess
import traceback


def build_hms_executable(repo_root=r"C:\github\projects\hms-stem-cleaner"):
    """
    Compiles hms_stem_cleaner_app.py into a single-file Windows executable
    (dist\\HMS_Stem_Cleaner.exe) using PyInstaller with Pedalboard & NumPy binaries bundled.
    """
    norm_repo = os.path.normpath(repo_root)
    script_path = os.path.join(norm_repo, "hms_stem_cleaner_app.py")
    dist_exe_path = os.path.join(norm_repo, "dist", "HMS_Stem_Cleaner.exe")

    print("=" * 75)
    print(f"[RUN] Starting PyInstaller Standalone EXE Build for: {script_path}")
    print("=" * 75)

    if not os.path.exists(script_path):
        print(f"[ERROR] Target script not found: {script_path}")
        return False

    try:
        # 1. Verify PyInstaller is installed in the active Python environment
        try:
            import PyInstaller  # noqa: F401
            print("[SUCCESS] PyInstaller module detected.")
        except ImportError:
            print("[RUN] Installing PyInstaller into active Python environment...")
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

        # 2. Assemble PyInstaller command with C++ extension collection for pedalboard and numpy
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name", "HMS_Stem_Cleaner",
            "--collect-all", "pedalboard",
            "--collect-all", "numpy",
            script_path
        ]

        print(f"[RUN] Executing PyInstaller (this takes ~60-90 seconds)...")
        print(f"[INFO] Command: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=norm_repo, check=True)

        if os.path.exists(dist_exe_path):
            size_mb = round(os.path.getsize(dist_exe_path) / (1024 * 1024), 2)
            print("=" * 75)
            print(f"[SUCCESS] STANDALONE EXE BUILT SUCCESSFULLY! ({size_mb} MB)")
            print(f"          Executable Path: {dist_exe_path}")
            print("=" * 75)
            return True
        else:
            print(f"[ERROR] PyInstaller finished but EXE was not found at: {dist_exe_path}")
            return False

    except Exception:
        print("[ERROR] Failed building standalone executable:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    build_hms_executable()