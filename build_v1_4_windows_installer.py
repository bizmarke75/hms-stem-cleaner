# Save as: C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py
# Isolated .iss Verification : python.exe C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py --iss-only
# Full Setup.exe Compilation : python.exe C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py

import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
APP_VERSION = "1.4.0"
APP_NAME = "HMS Unified Studio Suite"
APP_EXE_BASENAME = "HMS_Studio_Suite"
V14_HTML_NAME = "337_west_hms_unified_studio_web_daw_v1.4.html"

# Plain placeholder template prevents Python f-string vs Inno Setup {constant} brace bugs
INNO_SCRIPT_TEMPLATE = r"""; ==============================================================================
; HMS Unified Studio Suite v__APP_VERSION__ — Non-Portable Windows Installer
; Generated automatically by build_v1_4_windows_installer.py
; ==============================================================================

#define MyAppName "__APP_NAME__"
#define MyAppVersion "__APP_VERSION__"
#define MyAppPublisher "337 West Productions"
#define MyAppURL "https://github.com/bizmarke75/hms-stem-cleaner"
#define MyAppExeName "__APP_EXE_NAME__"

[Setup]
; Fixed GUID ensures future upgrades overwrite cleanly without duplicate Windows entries
AppId={{A4A9CA40-FF08-4C93-BD3F-0FDF3188C53F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Allow user to choose All Users (Program Files) OR Current User (AppData\Local\Programs)
; Always request Administrator UAC elevation so C:\Program Files installs cleanly
PrivilegesRequired=admin
DefaultDirName={autopf}\HMS Studio Suite
DefaultGroupName={#MyAppName}

; Explicitly allow installing onto any drive or custom directory on the computer
DisableDirPage=no
DisableProgramGroupPage=auto

; 64-bit Windows architecture & compact LZMA2 compression
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

OutputDir=__OUTPUT_DIR__
OutputBaseFilename=HMS_Studio_Suite_v__APP_VERSION___Setup
__LICENSE_LINE__
__ICON_LINE__

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Bundle the entire verified PyInstaller --onedir folder (exe + _internal runtime + HTML UI)
Source: "__BUNDLE_DIR__\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
__EXTRA_DOC_FILES__

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
__DOC_SHORTCUTS__
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
"""


# ==============================================================================
# FUNCTION 1: VALIDATE --ONEDIR BUNDLE & LOCATE INNO SETUP COMPILER (ISCC.EXE)
# ==============================================================================
def validate_bundle_and_find_iscc(repo_dir=HMS_REPO_DIR, app_exe_basename=APP_EXE_BASENAME):
    """
    Verifies that the Step 2 PyInstaller --onedir bundle is complete and locates
    Inno Setup 6 (ISCC.exe), optional icons, and optional documentation files.

    Args:
        repo_dir (str): Path to the HMS Studio Suite repository root.
        app_exe_basename (str): Name of the --onedir folder and .exe without extension.

    Returns:
        dict | None: Validated paths dictionary, or None if the --onedir bundle is missing.
    """
    norm_repo = os.path.normpath(repo_dir)
    bundle_dir = os.path.join(norm_repo, "dist", app_exe_basename)
    exe_path = os.path.join(bundle_dir, f"{app_exe_basename}.exe")
    internal_html = os.path.join(bundle_dir, "_internal", V14_HTML_NAME)

    print("=" * 75)
    print(f"[RUN] Step 3A: Validating --onedir bundle & locating Inno Setup (ISCC.exe)")
    print("=" * 75)

    try:
        # 1. Confirm compiled .exe exists
        if not os.path.isfile(exe_path):
            print(f"[ERROR] Missing compiled executable: {exe_path}")
            print("[INFO] Run Step 2 (fix_v1_4_html_and_rebuild.py) before building the installer.")
            return None

        # 2. Confirm v1.4 HTML UI is packaged inside _internal\
        if not os.path.isfile(internal_html):
            print(f"[ERROR] Missing bundled v1.4 UI inside _internal: {internal_html}")
            print("[INFO] Run fix_v1_4_html_and_rebuild.py so the v1.4 HTML is bundled cleanly.")
            return None

        print(f"[SUCCESS] Verified --onedir executable : {exe_path}")
        print(f"[SUCCESS] Verified bundled v1.4 UI     : {internal_html}")

        # 3. Search PATH and standard Windows directories for Inno Setup Compiler (ISCC.exe)
        iscc_candidates = [
            shutil.which("ISCC"),
            shutil.which("iscc"),
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
            r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        ]
        iscc_path = next((p for p in iscc_candidates if p and os.path.isfile(p)), None)
        if iscc_path:
            print(f"[SUCCESS] Located Inno Setup Compiler  : {iscc_path}")
        else:
            print("[INFO] Inno Setup (ISCC.exe) not found on this machine yet.")
            print("[INFO] Install it in 1 command via PowerShell: winget install JRSoftware.InnoSetup")

        # 4. Discover optional license, icon, and How-To Guide PDF to bundle beside the app
        license_path = os.path.join(norm_repo, "LICENSE")
        icon_path = os.path.join(norm_repo, "assets", "hms.ico")
        readme_path = os.path.join(norm_repo, "README.md")

        pdf_candidates = [
            os.path.join(norm_repo, "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
            os.path.join(norm_repo, "docs", "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
            str(Path.home() / "Downloads" / "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
        ]
        howto_pdf_path = next((p for p in pdf_candidates if os.path.isfile(p)), None)

        extra_docs = []
        if os.path.isfile(readme_path):
            extra_docs.append(readme_path)
        if howto_pdf_path:
            extra_docs.append(howto_pdf_path)
            print(f"[INFO] Found How-To Guide PDF to bundle: {howto_pdf_path}")

        return {
            "bundle_dir": bundle_dir,
            "exe_path": exe_path,
            "exe_name": f"{app_exe_basename}.exe",
            "iscc_path": iscc_path,
            "license_path": license_path if os.path.isfile(license_path) else None,
            "icon_path": icon_path if os.path.isfile(icon_path) else None,
            "howto_pdf_path": howto_pdf_path,
            "extra_docs": extra_docs,
        }

    except Exception:
        print("[ERROR] Failed validating bundle or locating ISCC.exe:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 2: GENERATE INNO SETUP (.ISS) INSTALLER DEFINITION SCRIPT
# ==============================================================================
def generate_inno_setup_script(bundle_info, repo_dir=HMS_REPO_DIR, version=APP_VERSION):
    """
    Writes a clean Inno Setup 6 .iss script into installer_out\\ ready for ISCC.exe.

    Args:
        bundle_info (dict): Validated asset dictionary from Function 1.
        repo_dir (str): Repository root directory.
        version (str): Semantic installer version (e.g., "1.4.0").

    Returns:
        str | None: Path to the generated .iss file, or None on error.
    """
    norm_repo = os.path.normpath(repo_dir)
    out_dir = os.path.join(norm_repo, "installer_out")
    iss_path = os.path.join(out_dir, f"HMS_Studio_Suite_v{version}.iss")

    print("\n" + "=" * 75)
    print(f"[RUN] Step 3B: Generating Inno Setup script -> {iss_path}")
    print("=" * 75)

    try:
        os.makedirs(out_dir, exist_ok=True)

        # Optional License screen & Setup Icon lines
        license_line = (
            f'LicenseFile={bundle_info["license_path"]}'
            if bundle_info.get("license_path")
            else "; No LICENSE file found in repo root"
        )
        icon_line = (
            f'SetupIconFile={bundle_info["icon_path"]}'
            if bundle_info.get("icon_path")
            else "; Using default Windows installer icon"
        )

        # Optional documentation files + Start Menu PDF shortcut
        extra_doc_lines = []
        doc_shortcut_lines = []
        for doc_path in bundle_info.get("extra_docs", []):
            extra_doc_lines.append(
                f'Source: "{doc_path}"; DestDir: "{{app}}\\docs"; Flags: ignoreversion'
            )

        if bundle_info.get("howto_pdf_path"):
            pdf_name = os.path.basename(bundle_info["howto_pdf_path"])
            doc_shortcut_lines.append(
                f'Name: "{{group}}\\HMS Studio Suite How-To Guide (PDF)"; Filename: "{{app}}\\docs\\{pdf_name}"'
            )

        # Populate template cleanly via deterministic string replacement
        iss_content = (
            INNO_SCRIPT_TEMPLATE
            .replace("__APP_NAME__", APP_NAME)
            .replace("__APP_VERSION__", version)
            .replace("__APP_EXE_NAME__", bundle_info["exe_name"])
            .replace("__OUTPUT_DIR__", out_dir)
            .replace("__BUNDLE_DIR__", bundle_info["bundle_dir"])
            .replace("__LICENSE_LINE__", license_line)
            .replace("__ICON_LINE__", icon_line)
            .replace("__EXTRA_DOC_FILES__", "\n".join(extra_doc_lines))
            .replace("__DOC_SHORTCUTS__", "\n".join(doc_shortcut_lines))
        )

        # Atomic write so partial scripts are never left behind
        tmp_iss = f"{iss_path}.tmp"
        with open(tmp_iss, "w", encoding="utf-8") as f:
            f.write(iss_content)
        os.replace(tmp_iss, iss_path)

        print(f"[SUCCESS] Generated Inno Setup script: {iss_path}")
        return iss_path

    except Exception:
        print("[ERROR] Failed generating Inno Setup script:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 3: COMPILE WINDOWS SETUP.EXE VIA INNO SETUP (ISCC.EXE)
# ==============================================================================
def compile_windows_installer(iss_path, iscc_path, version=APP_VERSION):
    """
    Invokes ISCC.exe to compile HMS_Studio_Suite_v1.4.0_Setup.exe.

    Args:
        iss_path (str): Path to the generated .iss script.
        iscc_path (str): Absolute path to ISCC.exe.
        version (str): Expected version string in the output filename.

    Returns:
        str | None: Path to compiled Setup.exe on success, or None on error.
    """
    out_dir = os.path.dirname(os.path.abspath(iss_path))
    expected_setup_exe = os.path.join(out_dir, f"HMS_Studio_Suite_v{version}_Setup.exe")

    print("\n" + "=" * 75)
    print(f"[RUN] Step 3C: Compiling Windows Installer via ISCC.exe...")
    print("=" * 75)

    if not iscc_path or not os.path.isfile(iscc_path):
        print("[ERROR] Cannot compile yet: ISCC.exe (Inno Setup 6) is not installed.")
        print("[INFO] Install Inno Setup 6 in PowerShell with:")
        print("       winget install JRSoftware.InnoSetup")
        print("[INFO] Then re-run this script to produce your Setup.exe!")
        return None

    try:
        print(f"[INFO] Running: \"{iscc_path}\" \"{iss_path}\"")
        subprocess.run([iscc_path, iss_path], check=True)

        if not os.path.isfile(expected_setup_exe):
            print(f"[ERROR] ISCC finished, but Setup.exe was not found at: {expected_setup_exe}")
            return None

        size_mb = round(os.path.getsize(expected_setup_exe) / (1024 * 1024), 2)
        print("=" * 75)
        print(f"[SUCCESS] WINDOWS INSTALLER COMPILED SUCCESSFULLY! ({size_mb} MB)")
        print(f"          Installer Path : {expected_setup_exe}")
        print("=" * 75)
        return expected_setup_exe

    except Exception:
        print("[ERROR] Failed compiling Windows installer with ISCC.exe:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# ISOLATED TEST DRIVER & ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    iss_only = "--iss-only" in sys.argv
    print("=== HMS Unified Studio Suite v1.4 — Step 3 Windows Installer Builder ===")

    info = validate_bundle_and_find_iscc(HMS_REPO_DIR)
    if not info:
        sys.exit(1)

    iss_file = generate_inno_setup_script(info, HMS_REPO_DIR, version=APP_VERSION)
    if not iss_file:
        sys.exit(1)

    if iss_only:
        print("\n[SUCCESS] --iss-only verification passed! Inspect your .iss script at:")
        print(f"          {iss_file}")
        sys.exit(0)

    setup_exe = compile_windows_installer(iss_file, info.get("iscc_path"), version=APP_VERSION)
    if setup_exe:
        print("\n[SUCCESS] Step 3 complete! Run your Setup.exe to install HMS Studio Suite anywhere on your PC.")
        sys.exit(0)
    else:
        sys.exit(1)