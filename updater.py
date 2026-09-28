import sys
import os
import tempfile
import subprocess
from pathlib import Path
from typing import Optional
import shutil
import httpx
import certifi

REPO = "Momarchristensen/Better-Schoology"
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

__version__ = "0.0.0"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Better-Schoology-Updater",
}
DOWNLOAD_HEADERS = {
    "Accept": "application/octet-stream",
    "User-Agent": "Better-Schoology-Updater",
}

MIN_EXE_SIZE = 1 * 1024 * 1024
EXE_MAGIC = b"MZ"
MAIN_EXE_NAME = "Better-Schoology.exe"

print("Running version:", __version__)


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        num = ""
        for ch in p:
            if not ch.isdigit():
                break
            num += ch
        parts.append(int(num) if num else 0)
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


class UpdateValidationError(Exception):
    """Raised when a release asset or downloaded file fails validation."""


def find_exe_asset(assets: list) -> Optional[dict]:
    for asset in assets:
        name = asset.get("name", "")
        if name != MAIN_EXE_NAME:
            if name.lower().endswith(".exe"):
                print(f"Skipping asset '{name}': expected '{MAIN_EXE_NAME}'.")
            continue
        size = asset.get("size", 0)
        if not (MIN_EXE_SIZE <= size):
            print(
                f"Skipping asset '{name}': size {size} bytes is outside "
                f"expected range ({MIN_EXE_SIZE}-infinity)."
            )
            continue
        return asset
    return None


def _get(url: str, *, timeout: float, headers: dict):
    last_exc = None
    for client_kwargs in ({}, {"trust_env": False, "verify": certifi.where()}):
        try:
            with httpx.Client(timeout=timeout, **client_kwargs) as client:
                resp = client.get(url, headers=headers, follow_redirects=True)
                resp.raise_for_status()
                return resp
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc


def check_for_update(timeout: float = 5.0) -> Optional[dict]:
    try:
        resp = _get(GITHUB_API_LATEST, timeout=timeout, headers=HEADERS)
        data = resp.json()
    except Exception as e:
        print(f"Failed to check for updates: {e}")
        return None

    latest_tag = data.get("tag_name", "")
    if not latest_tag or _parse_version(latest_tag) <= _parse_version(__version__):
        return None

    asset = find_exe_asset(data.get("assets", []))
    if not asset:
        return None

    return {
        "version": latest_tag,
        "notes": data.get("body", "") or "",
        "download_url": asset["browser_download_url"],
        "size": asset.get("size", 0),
    }


def _validate_exe_file(path: Path):
    size = path.stat().st_size
    if not (MIN_EXE_SIZE <= size):
        raise UpdateValidationError(
            f"Downloaded file size {size} bytes is outside expected range "
            f"({MIN_EXE_SIZE}-infinity)."
        )

    with open(path, "rb") as f:
        header = f.read(2)
    if header != EXE_MAGIC:
        raise UpdateValidationError(
            f"Downloaded file does not look like a Windows executable "
            f"(expected {EXE_MAGIC!r} header, got {header!r})."
        )


def download_update(download_url: str, dest_path: Path, timeout: float = 60):
    temp_path = dest_path.with_suffix(".part")
    try:
        with httpx.stream(
            "GET",
            download_url,
            headers=DOWNLOAD_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            with open(temp_path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)

        _validate_exe_file(temp_path)
        temp_path.replace(dest_path)
    finally:
        temp_path.unlink(missing_ok=True)


def get_bundled_updater_path() -> Path:
    base = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
    )
    return base / "update.exe"


def apply_update_and_restart(download_url: str):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Updates are only supported in packaged builds.")

    current_exe = Path(sys.executable).resolve()
    tmp_dir = Path(tempfile.gettempdir()) / "Better-Schoology-update"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    new_exe = tmp_dir / "new_update.exe"
    download_update(download_url, new_exe)

    bundled_updater = get_bundled_updater_path()
    if not bundled_updater.is_file():
        raise FileNotFoundError(f"Bundled updater not found: {bundled_updater}")

    updater_copy = tmp_dir / "update.exe"
    shutil.copy2(bundled_updater, updater_copy)

    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008

    subprocess.Popen(
        [
            str(updater_copy.resolve()),
            str(os.getpid()),
            str(new_exe.resolve()),
            str(current_exe.resolve()),
        ],
        creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
        close_fds=True,
    )
    os._exit(0)


def _tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def prompt_update_dialog(release_info: dict) -> bool:
    from tkinter import messagebox

    root = _tk_root()
    try:
        return messagebox.askyesno(
            "Update available",
            f"A new version ({release_info['version']}) of Better Schoology is "
            f"available.\nYou're running {__version__}.\n\n"
            "Download and install it now? The app will restart.",
            parent=root,
        )
    finally:
        root.destroy()


def show_error_dialog(title: str, message: str):
    from tkinter import messagebox

    root = _tk_root()
    try:
        messagebox.showerror(title, message, parent=root)
    finally:
        root.destroy()


def check_for_updates():
    if not getattr(sys, "frozen", False):
        return

    release = check_for_update()
    if not release:
        return

    if prompt_update_dialog(release):
        try:
            apply_update_and_restart(release["download_url"])
        except Exception as exc:
            show_error_dialog("Update failed", f"Could not install the update:\n{exc}")
