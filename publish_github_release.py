# Save as: C:\github\projects\hms-stem-cleaner\publish_github_release.py
# Run Local Stage & Zip : python.exe C:\github\projects\hms-stem-cleaner\publish_github_release.py
# Push to Remote URL    : python.exe C:\github\projects\hms-stem-cleaner\publish_github_release.py --remote "https://github.com/<your-username>/hms-stem-cleaner.git"

import os
import sys
import zipfile
import argparse
import subprocess
import traceback
from datetime import datetime


# ==============================================================================
# FUNCTION 1: SAFE GIT INITIALIZER, LARGE-FILE GUARD & COMMITTER
# ==============================================================================
def stage_and_commit_local_repo(repo_root=r"C:\github\projects\hms-stem-cleaner", version_tag="v1.0.0"):
    """
    Initializes the local Git repository in repo_root, ensures release_upload/
    is in .gitignore, audits tracked candidates to guarantee zero .wav/.exe bloat,
    and creates the v1.0.0 commit and Git tag.

    Args:
        repo_root (str): Path to the local GitHub repository folder.
        version_tag (str): Semantic version tag for the release.

    Returns:
        dict: Status report containing staged files and commit hash.
    """
    norm_repo = os.path.normpath(repo_root)
    result = {
        "git_ready": False,
        "staged_files": [],
        "commit_hash": None
    }

    print("=" * 75)
    print(f"[RUN] Phase 4A: Auditing & Staging Git Repository in: {norm_repo}")
    print("=" * 75)

    if not os.path.exists(norm_repo):
        print(f"[ERROR] Repository directory not found: {norm_repo}")
        return result

    try:
        # 1. Verify Git CLI is installed and accessible
        git_ver = subprocess.run(
            ["git", "--version"],
            cwd=norm_repo,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"[SUCCESS] Detected {git_ver.stdout.strip()}")

        # 2. Ensure 'release_upload/' and temporary test folders are listed in .gitignore
        gitignore_path = os.path.join(norm_repo, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                ig_text = f.read()
            extra_ignores = ["release_upload/", "_layer1_test_song/", "_layer2b_raw_in/", "_layer2b_clean_out/"]
            appended = False
            for rule in extra_ignores:
                if rule not in ig_text:
                    ig_text += f"\n{rule}"
                    appended = True
            if appended:
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(ig_text + "\n")
                print("[INFO] Updated .gitignore with release_upload/ and test folder exclusions.")

        # 3. Initialize Git repo on 'main' branch if .git does not exist yet
        git_dir = os.path.join(norm_repo, ".git")
        if not os.path.exists(git_dir):
            print("[RUN] Initializing new Git repository (branch: main)...")
            subprocess.run(["git", "init", "-b", "main"], cwd=norm_repo, check=True)
        else:
            print("[INFO] Existing .git repository detected.")

        # 4. Stage files respecting .gitignore
        subprocess.run(["git", "add", "."], cwd=norm_repo, check=True)

        # 5. Safety Audit: Inspect staged files to ensure no .wav, .exe, or >25MB file was staged
        status_proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=norm_repo,
            capture_output=True,
            text=True,
            check=True
        )
        staged = [line.strip() for line in status_proc.stdout.splitlines() if line.strip()]

        for rel_path in staged:
            full_p = os.path.join(norm_repo, rel_path)
            if os.path.exists(full_p) and os.path.isfile(full_p):
                size_mb = os.path.getsize(full_p) / (1024 * 1024)
                lower_p = rel_path.lower()
                if lower_p.endswith((".wav", ".exe", ".zip")) or size_mb > 25.0:
                    print(f"[ERROR] Safety Guard triggered! Unstaging binary/large file: {rel_path} ({size_mb:.2f} MB)")
                    subprocess.run(["git", "reset", "HEAD", rel_path], cwd=norm_repo, check=False)
                else:
                    result["staged_files"].append(rel_path)
                    print(f"[SUCCESS] Staged for Git commit: {rel_path} ({size_mb * 1024:.1f} KB)")

        # 6. Commit staged changes if any exist
        if result["staged_files"]:
            commit_msg = f"Release {version_tag}: HMS Stem Cleaner & Headless VST3 Master Engine (As-Is Release)"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=norm_repo, check=True)
            print(f"[SUCCESS] Created Git commit: '{commit_msg}'")
        else:
            print("[INFO] Working tree is already clean and committed.")

        # 7. Create or update version tag
        subprocess.run(["git", "tag", "-f", version_tag], cwd=norm_repo, check=True)

        rev_proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=norm_repo,
            capture_output=True,
            text=True,
            check=True
        )
        result["commit_hash"] = rev_proc.stdout.strip()
        result["git_ready"] = True

        print(f"[SUCCESS] Local Git Repository locked at commit [{result['commit_hash']}] (Tag: {version_tag})")
        return result

    except Exception:
        print("[ERROR] Failed staging or committing local Git repository:")
        print(traceback.format_exc())
        return result


# ==============================================================================
# FUNCTION 2: STANDALONE EXE RELEASE ZIP & AS-IS RELEASE NOTES PACKAGER
# ==============================================================================
def package_release_bundle(repo_root=r"C:\github\projects\hms-stem-cleaner", version_tag="v1.0.0"):
    """
    Bundles dist\\HMS_Stem_Cleaner.exe, README.md, and LICENSE into a clean
    distributable ZIP archive inside release_upload\\ alongside RELEASE_NOTES.md.
    """
    norm_repo = os.path.normpath(repo_root)
    exe_path = os.path.join(norm_repo, "dist", "HMS_Stem_Cleaner.exe")
    release_dir = os.path.join(norm_repo, "release_upload")
    zip_filename = f"HMS_Stem_Cleaner_{version_tag}_Win64_Standalone.zip"
    zip_path = os.path.join(release_dir, zip_filename)
    notes_path = os.path.join(release_dir, f"RELEASE_NOTES_{version_tag}.md")

    print("=" * 75)
    print(f"[RUN] Phase 4B: Packaging Standalone EXE Release Bundle ({version_tag})")
    print("=" * 75)

    try:
        os.makedirs(release_dir, exist_ok=True)

        # 1. Write copy-pasteable GitHub Release Notes with clear "As-Is" notice
        release_notes = f"""# HMS Stem Cleaner & Headless VST3 Master Engine ({version_tag})
**By 337 West Productions** | Released: {datetime.now().strftime('%Y-%m-%d')}

## ⚠️ PROVIDED STRICTLY "AS-IS" (NO SUPPORT / NO PROMISES)
I built this standalone tool for my own studio workflow to eliminate MVSep stem bleed, hollow reverb tails, and slapback echo on AI-generated music tracks (Suno v5.5/v6) without having to open a full DAW. I am sharing the source code and standalone `.exe` because other creators can benefit from it, **but I am not a full-time programmer and cannot offer technical support, bug fixes, or custom feature modifications.** Use at your own risk and always keep backups of your raw `.wav` files!

## 📦 What's Included in `{zip_filename}`
- **`HMS_Stem_Cleaner.exe`**: Standalone 64-bit Windows executable (no Python installation required).
- **`README.md` & `LICENSE`**: Setup instructions and MIT "As-Is" license.

## 🚀 Quick Start
1. Extract `HMS_Stem_Cleaner.exe` to any folder on Windows 10/11.
2. *(Optional but Recommended)* Install the free 64-bit VST3 plugins into `C:\\Program Files\\Common Files\\VST3`:
   - **TDR Nova** (Dynamic EQ)
   - **Klanghelm MJUCjr** (Variable-Mu Vocal Compressor)
   - **CHOWTapeModel** (Analog Tape Saturation)
3. Double-click `HMS_Stem_Cleaner.exe`, select your raw MVSep stem folder, click **`0. AI AUTO-TUNE`** (or set the mix sliders manually), and click **`2. FULL LIVE CLEAN + MASTER (24-BIT)`**.
"""
        with open(notes_path, "w", encoding="utf-8") as nf:
            nf.write(release_notes)
        print(f"[SUCCESS] Wrote GitHub Release Notes -> {notes_path}")

        # 2. Package EXE + README + LICENSE into the release ZIP if EXE exists
        if not os.path.exists(exe_path):
            print(f"[INFO] Standalone EXE not found at {exe_path} yet.")
            print("       Run 'python.exe build_standalone_exe.py' first, then re-run this script to zip the EXE.")
            return None

        files_to_bundle = [
            (exe_path, "HMS_Stem_Cleaner.exe"),
            (os.path.join(norm_repo, "README.md"), "README.md"),
            (os.path.join(norm_repo, "LICENSE"), "LICENSE")
        ]

        print(f"[RUN] Compressing release archive -> {zip_path} ...")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for src_f, arc_name in files_to_bundle:
                if os.path.exists(src_f):
                    zf.write(src_f, arcname=arc_name)
                    print(f"[INFO]   + Added to ZIP: {arc_name}")

        zip_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        print("=" * 75)
        print(f"[SUCCESS] RELEASE BUNDLE READY FOR GITHUB UPLOAD! ({zip_mb} MB)")
        print(f"          ZIP Archive   : {zip_path}")
        print(f"          Release Notes : {notes_path}")
        print("=" * 75)
        return zip_path

    except Exception:
        print("[ERROR] Failed packaging release bundle:")
        print(traceback.format_exc())
        return None


def push_to_github_remote(repo_root, remote_url, version_tag="v1.0.0"):
    """
    Links the local repository to the user's GitHub remote URL and pushes
    the main branch and version tag.
    """
    norm_repo = os.path.normpath(repo_root)
    print("=" * 75)
    print(f"[RUN] Linking & Pushing to Remote GitHub Repository: {remote_url}")
    print("=" * 75)

    try:
        # Check if 'origin' already exists
        rem_proc = subprocess.run(["git", "remote"], cwd=norm_repo, capture_output=True, text=True)
        remotes = rem_proc.stdout.splitlines()
        if "origin" in remotes:
            subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=norm_repo, check=True)
        else:
            subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=norm_repo, check=True)

        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=norm_repo, check=True)
        subprocess.run(["git", "push", "origin", version_tag], cwd=norm_repo, check=True)
        print(f"[SUCCESS] Pushed 'main' branch and tag '{version_tag}' to {remote_url}!")
        return True
    except Exception:
        print("[ERROR] Failed pushing to GitHub remote:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMS GitHub Repository Stager & Release Packager")
    parser.add_argument("--repo", type=str, default=r"C:\github\projects\hms-stem-cleaner", help="Local repo path")
    parser.add_argument("--tag", type=str, default="v1.0.0", help="Release version tag")
    parser.add_argument("--remote", type=str, default=None, help="Optional GitHub remote URL to push to immediately")
    args = parser.parse_args()

    git_res = stage_and_commit_local_repo(repo_root=args.repo, version_tag=args.tag)
    zip_out = package_release_bundle(repo_root=args.repo, version_tag=args.tag)

    if args.remote and git_res.get("git_ready"):
        push_to_github_remote(repo_root=args.repo, remote_url=args.remote, version_tag=args.tag)