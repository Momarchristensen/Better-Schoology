import shutil
import subprocess
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent


def run_pyinstaller(*args):
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", *args],
        cwd=script_dir,
        check=True,
    )


run_pyinstaller(
    "--onefile",
    "--noconsole",
    "--clean",
    "--name", "app_updater",
    "update_installer.py",
)

shutil.copy2(script_dir / "dist" / "app_updater.exe", script_dir / "app_updater.exe")

run_pyinstaller(
    "--onefile",
    "--clean",
    "--name", "Better-Schoology",
    "--collect-all", "lxml",
    "--hidden-import", "app_updater",
    "--add-data", "web;web",
    "--add-binary", "app_updater.exe;.",
    "server.py",
)