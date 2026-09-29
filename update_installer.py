import sys
import os
import time
import shutil
import logging
import ctypes
from pathlib import Path


def wait_for_pid_exit(pid: int, timeout: float = 30.0):
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    kernel32 = ctypes.windll.kernel32

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        logging.info(f"OpenProcess failed for PID {pid} (likely already exited)")
        return
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == WAIT_TIMEOUT:
            logging.warning(f"Timed out waiting for PID {pid} to exit")
        else:
            logging.info(f"PID {pid} exited (wait result={result})")
    finally:
        kernel32.CloseHandle(handle)


def main():
    if len(sys.argv) != 4:
        sys.exit(1)

    pid = int(sys.argv[1])
    new_exe = Path(sys.argv[2])
    target_exe = Path(sys.argv[3])

    log_dir = Path(os.environ.get("TEMP", ".")) / "Better-Schoology-update"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "updater.log",
        level=logging.INFO,
        format="%(asctime)s %(message)s",
    )

    logging.info(f"Updater started. pid={pid} new_exe={new_exe} target={target_exe}")

    wait_for_pid_exit(pid, timeout=30)

    old_backup = target_exe.with_suffix(target_exe.suffix + ".old")
    try:
        if old_backup.exists():
            old_backup.unlink()
    except Exception as e:
        logging.warning(f"Could not remove stale backup: {e}")

    renamed = False
    for attempt in range(10):
        try:
            target_exe.rename(old_backup)
            renamed = True
            break
        except Exception as e:
            logging.info(f"Rename-out attempt {attempt + 1} failed: {e}")
            time.sleep(1)

    if not renamed:
        logging.error("Failed to rename out old exe after 10 attempts, aborting")
        sys.exit(1)

    try:
        shutil.move(str(new_exe), str(target_exe))
    except Exception as e:
        logging.error(f"Move-in failed: {e}, restoring backup")
        try:
            old_backup.rename(target_exe)
        except Exception as e2:
            logging.error(f"Restore also failed: {e2}")
        sys.exit(1)

    logging.info("Replace succeeded")
    time.sleep(1)

    try:
        os.startfile(str(target_exe))
        logging.info("Launched new exe")
    except Exception as e:
        logging.error(f"Failed to launch new exe: {e}")
        sys.exit(1)

    time.sleep(2)

    try:
        old_backup.unlink()
        logging.info("Cleaned up backup")
    except Exception as e:
        logging.info(f"Backup cleanup skipped: {e}")

    logging.info("Updater finished")


if __name__ == "__main__":
    main()