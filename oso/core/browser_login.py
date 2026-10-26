"""Desktop Firefox login and web VNC-cookie import in a shared directory."""
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from oso.platforms.config import getProfileSeed

logger = logging.getLogger("oso.browser_login")


class BrowserLogin:
    def __init__(self, service, stagingPath=None):
        self.service = service
        self.stagingPath = Path(stagingPath or os.environ.get("OSO_VNC_BROWSER_DIR", "/browser-login"))
        self.lock = threading.Lock()
        self.finishLock = threading.Lock()
        self.activeProfileId = None

    def desktopLogin(self, profileId):
        if self.service.mode != "desktop":
            raise ValueError("Desktop login is unavailable in web mode")
        if not self.lock.acquire(blocking=False):
            raise ValueError("Another browser login is active")
        try:
            from invisible_playwright import InvisiblePlaywright
            profile = self.service.profile(profileId)
            directory = self.service.browserProfile(profile)
            directory.mkdir(parents=True, exist_ok=True)
            with InvisiblePlaywright(profile_dir=str(directory), seed=getProfileSeed(directory), headless=False) as browser:
                page = browser.new_page()
                page.goto("https://www.tiktok.com")
                # Wait while the user logs in. Closing the window ends this task.
                while not page.is_closed():
                    try:
                        page.wait_for_timeout(1000)
                    except Exception:
                        break
        finally:
            self.lock.release()

    def startVnc(self, profileId):
        if self.service.mode != "web":
            raise ValueError("VNC login is web-only")
        self.service.profile(profileId)
        if not self.stagingPath.exists():
            raise ValueError("VNC browser volume is unavailable; start Docker Compose")
        if not self.lock.acquire(blocking=False):
            raise ValueError("A VNC login is already active")
        self.activeProfileId = profileId

    def _runWorker(self, operation, *paths, timeout):
        """Run blocking browser/SQLite work separately so a stalled job is killable."""
        command = [sys.executable, "-m", "oso.core.browser_login", operation, *(str(path) for path in paths)]
        logger.info("VNC cookie import: starting %s (limit %ss)", operation, timeout)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            # Kill any Firefox process started by the worker as well as Python.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("VNC cookie import: worker left open pipes after termination")
            logger.error("VNC cookie import: %s timed out after %ss", operation, timeout)
            raise ValueError(f"VNC cookie import: {operation} timed out after {timeout}s; check web logs") from error
        if process.returncode != 0:
            detail = (stderr or stdout or "Unknown subprocess error").strip()[-1800:]
            logger.error("VNC cookie import: %s failed: %s", operation, detail)
            raise ValueError(f"VNC cookie import: {operation} failed. Check the web logs")
        logger.info("VNC cookie import: %s finished successfully", operation)

    def finishVnc(self, profileId):
        if not self.finishLock.acquire(blocking=False):
            raise ValueError("A cookie import is already in progress")
        try:
            if self.activeProfileId != profileId:
                raise ValueError("This profile has no active VNC login")
            logger.info("VNC cookie import: begin profile %s", profileId)
            files = list(self.stagingPath.glob(".config/mozilla/firefox/*/cookies.sqlite"))
            if not files:
                raise ValueError("No Firefox cookies found; open TikTok in the VNC browser first")
            source = max(files, key=lambda path: path.stat().st_mtime)
            logger.info("VNC cookie import: source database found at %s", source)
            profile = self.service.profile(profileId)
            destination = self.service.browserProfile(profile)
            destination.mkdir(parents=True, exist_ok=True)
            # Initialize Playwright's profile before replacing its cookie database.
            if not (destination / "cookies.sqlite").exists():
                self._runWorker("prepare", destination, timeout=60)
                if not (destination / "cookies.sqlite").is_file():
                    raise ValueError("Patched Firefox did not create a cookies.sqlite database")
            # Snapshot into a distinct SQLite file. Never back up into the live profile.
            fd, snapshotName = tempfile.mkstemp(prefix=".cookies-import-", suffix=".sqlite", dir=destination)
            os.close(fd)
            snapshotPath = Path(snapshotName)
            try:
                self._runWorker("backup", source, snapshotPath, timeout=30)
                # An old WAL/SHM must not be associated with the replaced database.
                for suffix in ("-wal", "-shm"):
                    (destination / f"cookies.sqlite{suffix}").unlink(missing_ok=True)
                snapshotPath.chmod(0o600)
                os.replace(snapshotPath, destination / "cookies.sqlite")
            finally:
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{snapshotPath}{suffix}").unlink(missing_ok=True)
            self.activeProfileId = None
            self.lock.release()
            logger.info("VNC cookie import: completed profile %s", profileId)
        finally:
            self.finishLock.release()

    def cancelVnc(self, profileId):
        if not self.finishLock.acquire(blocking=False):
            raise ValueError("Wait for the cookie import to finish before cancelling")
        try:
            if self.activeProfileId != profileId:
                raise ValueError("This profile has no active VNC login")
            self.activeProfileId = None
            self.lock.release()
        finally:
            self.finishLock.release()


def _workerMain():
    """Commands used only by the web service, not standalone user entrypoints."""
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python -m oso.core.browser_login prepare DIR | backup SOURCE SNAPSHOT")
    operation = sys.argv[1]
    if operation == "prepare" and len(sys.argv) == 3:
        from invisible_playwright import InvisiblePlaywright
        directory = Path(sys.argv[2])
        with InvisiblePlaywright(profile_dir=str(directory), seed=getProfileSeed(directory), headless=True) as browser:
            page = browser.new_page()
            page.goto("https://www.tiktok.com", wait_until="domcontentloaded", timeout=20000)
    elif operation == "backup" and len(sys.argv) == 4:
        source, snapshot = Path(sys.argv[2]), Path(sys.argv[3])
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as dbSource:
            with sqlite3.connect(snapshot, timeout=5) as dbDest:
                dbSource.backup(dbDest, pages=128, sleep=0.1)
    else:
        raise SystemExit(f"Unknown worker operation: {operation}")


if __name__ == "__main__":
    _workerMain()
