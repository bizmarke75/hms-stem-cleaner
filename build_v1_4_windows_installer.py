# Save as: C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py
# Isolated .iss Verification : python.exe -u C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py --iss-only
# Full v1.4.1 Compilation    : python.exe -u C:\github\projects\hms-stem-cleaner\build_v1_4_windows_installer.py

import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

HMS_REPO_DIR = r"C:\github\projects\hms-stem-cleaner"
APP_VERSION = "1.4.1"
APP_NAME = "HMS Unified Studio Suite"
APP_EXE_BASENAME = "HMS_Studio_Suite"
V14_HTML_NAME = "337_west_hms_unified_studio_web_daw_v1.4.html"

# Placeholder template avoids Python f-string vs Inno Setup {constant} brace collisions
INNO_SCRIPT_TEMPLATE = r"""; ==============================================================================
; HMS Unified Studio Suite v__APP_VERSION__ — Admin Windows Installer
; Generated automatically by build_v1_4_windows_installer.py
; ==============================================================================

#define MyAppName "__APP_NAME__"
#define MyAppVersion "__APP_VERSION__"
#define MyAppPublisher "337 West Productions"
#define MyAppURL "https://github.com/bizmarke75/hms-stem-cleaner"
#define MyAppExeName "__APP_EXE_NAME__"

[Setup]
; Fixed GUID ensures clean in-place upgrades without duplicate Installed Apps entries
AppId={{A4A9CA40-FF08-4C93-BD3F-0FDF3188C53F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Elevate cleanly for C:\Program Files\HMS Studio Suite (prevents Access Denied & split installs)
PrivilegesRequired=admin
DefaultDirName={autopf}\HMS Studio Suite
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=auto

; Auto-close any running instance before replacing binaries
CloseApplications=yes
CloseApplicationsFilter=*.exe

; 64-bit Windows mode & LZMA2 compression
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

[InstallDelete]
; Clear stale PyInstaller _internal runtime files before copying the new v1.4.1 bundle
Type: filesandordirs; Name: "{app}\_internal"

[Files]
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
# FUNCTION 1: VALIDATE --ONEDIR BUNDLE, UI FIX MARKERS & INNO SETUP COMPILER
# ==============================================================================
def validate_bundle_and_find_iscc(repo_dir=HMS_REPO_DIR, app_exe_basename=APP_EXE_BASENAME):
    """
    Validates that the compiled PyInstaller --onedir bundle exists, confirms the
    bundled v1.4 HTML contains the UI layout order fix, and locates ISCC.exe.

    Args:
        repo_dir (str): Path to the local hms-stem-cleaner repository.
        app_exe_basename (str): Name of the --onedir folder and .exe without extension.

    Returns:
        dict | None: Validated paths dictionary, or None if validation fails.
    """
    norm_repo = os.path.normpath(repo_dir)
    bundle_dir = os.path.join(norm_repo, "dist", app_exe_basename)
    exe_path = os.path.join(bundle_dir, f"{app_exe_basename}.exe")
    internal_html = os.path.join(bundle_dir, "_internal", V14_HTML_NAME)

    print("=" * 75)
    print(f"[RUN] Function 1: Validating v{APP_VERSION} --onedir bundle & locating ISCC.exe")
    print("=" * 75)

    try:
        if not os.path.isfile(exe_path):
            print(f"[ERROR] Missing compiled executable: {exe_path}")
            print("[INFO] Run fix_v1_4_html_and_rebuild.py first.")
            return None

        if not os.path.isfile(internal_html):
            print(f"[ERROR] Missing bundled UI HTML inside _internal: {internal_html}")
            return None

        # Guard against packaging an outdated HTML copy without the UI layout fix
        html_text = Path(internal_html).read_text(encoding="utf-8", errors="ignore")
        has_ui_fix = ("HMS_DOM_ORDER_GUARD_V1_4_2" in html_text) or ("HMS_LAYOUT_ORDER_FIX_V1_4_1" in html_text)
        has_bad_prepend = "host.prepend(card);" in html_text
        if not has_ui_fix or has_bad_prepend:
            print(f"[ERROR] Bundled HTML failed UI layout check (UIFix={has_ui_fix}, BadPrepend={has_bad_prepend})!")
            print("[INFO] Re-run fix_ui_order_final.py and fix_v1_4_html_and_rebuild.py first.")
            return None

        print(f"[SUCCESS] Verified --onedir EXE : {exe_path}")
        print(f"[SUCCESS] Verified UI-fixed HTML: {internal_html}")

        # Locate Inno Setup 6 compiler across PATH, Program Files, and per-user LocalAppData
        iscc_candidates = [
            shutil.which("ISCC"),
            shutil.which("iscc"),
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            r"C:\Program Files\Inno Setup 6\ISCC.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
        ]
        iscc_path = next((p for p in iscc_candidates if p and os.path.isfile(p)), None)
        if iscc_path:
            print(f"[SUCCESS] Located ISCC.exe      : {iscc_path}")
        else:
            print("[ERROR] ISCC.exe not found! Install via: winget install JRSoftware.InnoSetup")

        # Discover optional license, icon, and bundled documentation files
        license_path = os.path.join(norm_repo, "LICENSE")
        icon_path = os.path.join(norm_repo, "assets", "hms.ico")
        readme_path = os.path.join(norm_repo, "README.md")
        changelog_path = os.path.join(norm_repo, "CHANGELOG.md")
        pdf_candidates = [
            os.path.join(norm_repo, "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
            os.path.join(norm_repo, "docs", "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
            str(Path.home() / "Downloads" / "HMS_Studio_Suite_v1_4_HowTo_Guide.pdf"),
        ]
        howto_pdf_path = next((p for p in pdf_candidates if os.path.isfile(p)), None)

        extra_docs = [p for p in (readme_path, changelog_path, howto_pdf_path) if p and os.path.isfile(p)]
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
        print("[ERROR] Function 1 failed:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 2: GENERATE CLEAN ADMIN INNO SETUP (.ISS) SCRIPT
# ==============================================================================
def generate_inno_setup_script(bundle_info, repo_dir=HMS_REPO_DIR, version=APP_VERSION):
    """
    Writes installer_out\\HMS_Studio_Suite_v<version>.iss atomically using UTF-8.

    Args:
        bundle_info (dict): Validated asset dictionary from Function 1.
        repo_dir (str): Repository root directory.
        version (str): Semantic installer version (e.g., "1.4.1").

    Returns:
        str | None: Path to the generated .iss script, or None on failure.
    """
    norm_repo = os.path.normpath(repo_dir)
    out_dir = os.path.join(norm_repo, "installer_out")
    iss_path = os.path.join(out_dir, f"HMS_Studio_Suite_v{version}.iss")

    print("\n" + "=" * 75)
    print(f"[RUN] Function 2: Generating Admin Inno Setup script -> {iss_path}")
    print("=" * 75)

    try:
        os.makedirs(out_dir, exist_ok=True)

        license_line = f'LicenseFile={bundle_info["license_path"]}' if bundle_info.get("license_path") else "; No LICENSE file"
        icon_line = f'SetupIconFile={bundle_info["icon_path"]}' if bundle_info.get("icon_path") else "; Default installer icon"

        extra_doc_lines = [
            f'Source: "{doc_path}"; DestDir: "{{app}}\\docs"; Flags: ignoreversion'
            for doc_path in bundle_info.get("extra_docs", [])
        ]
        doc_shortcut_lines = []
        if bundle_info.get("howto_pdf_path"):
            pdf_name = os.path.basename(bundle_info["howto_pdf_path"])
            doc_shortcut_lines.append(
                f'Name: "{{group}}\\HMS Studio Suite How-To Guide (PDF)"; Filename: "{{app}}\\docs\\{pdf_name}"'
            )

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

        # Atomic write with clean LF line endings
        tmp_iss = f"{iss_path}.tmp"
        with open(tmp_iss, "w", encoding="utf-8", newline="\n") as f:
            f.write(iss_content)
        os.replace(tmp_iss, iss_path)

        print(f"[SUCCESS] Wrote Inno Setup script ({os.path.getsize(iss_path)} bytes) -> {iss_path}")
        return iss_path
    except Exception:
        print("[ERROR] Function 2 failed:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# FUNCTION 3: COMPILE HMS_STUDIO_SUITE_V1.4.1_SETUP.EXE VIA ISCC.EXE
# ==============================================================================
def compile_windows_installer(iss_path, iscc_path, version=APP_VERSION):
    """
    Compiles the generated .iss script via ISCC.exe and verifies the output Setup.exe.

    Args:
        iss_path (str): Path to the .iss script generated by Function 2.
        iscc_path (str): Absolute path to ISCC.exe.
        version (str): Expected version string in the output filename.

    Returns:
        str | None: Absolute path to compiled Setup.exe, or None on error.
    """
    out_dir = os.path.dirname(os.path.abspath(iss_path))
    expected_setup_exe = os.path.join(out_dir, f"HMS_Studio_Suite_v{version}_Setup.exe")

    print("\n" + "=" * 75)
    print(f"[RUN] Function 3: Compiling HMS_Studio_Suite_v{version}_Setup.exe via ISCC.exe...")
    print("=" * 75)

    if not iscc_path or not os.path.isfile(iscc_path):
        print("[ERROR] Cannot compile: ISCC.exe is missing.")
        return None

    try:
        # Remove any stale copy of this version so a failed build never masquerades as success
        if os.path.isfile(expected_setup_exe):
            os.remove(expected_setup_exe)

        print(f'[INFO] Executing: "{iscc_path}" "{iss_path}"')
        subprocess.run([iscc_path, iss_path], check=True)

        if not os.path.isfile(expected_setup_exe):
            print(f"[ERROR] ISCC exited 0, but Setup.exe was not found at: {expected_setup_exe}")
            return None

        size_mb = round(os.path.getsize(expected_setup_exe) / (1024 * 1024), 2)
        print("=" * 75)
        print(f"[SUCCESS] WINDOWS INSTALLER COMPILED! ({size_mb} MB)")
        print(f"          Installer Path : {expected_setup_exe}")
        print("=" * 75)
        return expected_setup_exe
    except Exception:
        print("[ERROR] Function 3 failed compiling with ISCC.exe:")
        print(traceback.format_exc())
        return None


# ==============================================================================
# ISOLATED TEST DRIVER & ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    iss_only = "--iss-only" in sys.argv
    print(f"=== HMS Unified Studio Suite v{APP_VERSION} — Admin Windows Installer Builder ===")

    info = validate_bundle_and_find_iscc(HMS_REPO_DIR)
    if not info:
        sys.exit(1)

    iss_file = generate_inno_setup_script(info, HMS_REPO_DIR, version=APP_VERSION)
    if not iss_file:
        sys.exit(1)

    if iss_only:
        print(f"\n[SUCCESS] --iss-only verification passed! Inspect: {iss_file}")
        sys.exit(0)

    setup_exe = compile_windows_installer(iss_file, info.get("iscc_path"), version=APP_VERSION)
    sys.exit(0 if setup_exe else 1)