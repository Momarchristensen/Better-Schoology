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
    "--name", "update",
    "update.py",
)

shutil.copy2(script_dir / "dist" / "update.exe", script_dir / "update.exe")

run_pyinstaller(
    "--onefile",
    "--clean",
    "--name", "Better-Schoology",
    "--collect-all", "lxml",
    "--hidden-import", "updater",
    "--add-data", "HTML;HTML",
    "--add-data", "libreoffice;libreoffice",
    "--add-binary", "update.exe;.",
    "server.py",
)