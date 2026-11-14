import os
import shutil
import zipfile
import traceback


def prepare_hms_song_workspace(input_audio_path, downloaded_paths, log_callback=print):
    """
    Organizes downloaded MVSep stem files (or extracts a downloaded MVSep ZIP)
    into a dedicated song folder (<Parent_Dir>/<Song_Name>/) so HMS Stem Cleaner
    can accurately derive the song title and scan only that song's stems.

    Args:
        input_audio_path (str): Path to the original input audio file uploaded to MVSep.
        downloaded_paths (list[str]): List of file paths saved by MVSepGUIApp.download_results().
        log_callback (callable): Logging function (defaults to print; pass self.log in MVSepGUIApp).

    Returns:
        str or None: Absolute path to the prepared song directory, or None on failure.
    """
    log_callback("=" * 65)
    log_callback(f"[RUN] Preparing HMS Song Workspace for: {input_audio_path}")

    if not input_audio_path or not downloaded_paths:
        log_callback("[ERROR] Missing input_audio_path or downloaded_paths list is empty.")
        return None

    try:
        # 1. Derive clean Song_Name from the original uploaded audio filename
        parent_dir = os.path.dirname(os.path.abspath(input_audio_path))
        raw_base = os.path.splitext(os.path.basename(input_audio_path))[0]
        clean_song_name = "".join(
            "_" if c in '<>:"/\\|?* ' else c for c in raw_base
        ).strip("_") or "MVSep_Song"

        song_workspace_dir = os.path.join(parent_dir, f"{clean_song_name}_Stems")
        os.makedirs(song_workspace_dir, exist_ok=True)
        log_callback(f"[INFO] Target HMS Song Folder: {song_workspace_dir}")

        staged_wav_count = 0

        # 2. Move individual stem files or extract ZIP archives into song_workspace_dir
        for item_path in downloaded_paths:
            if not item_path or not os.path.isfile(item_path):
                log_callback(f"[INFO] Skipping missing path: {item_path}")
                continue

            ext = os.path.splitext(item_path)[1].lower()

            # Handle MVSep ZIP archive fallback
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
                # Move individual stem file into the dedicated song folder
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