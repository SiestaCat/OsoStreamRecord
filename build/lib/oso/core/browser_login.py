"""Desktop Firefox login and web VNC-cookie import in a shared directory."""
import asyncio
import os
import shutil
import sqlite3
import threading
from pathlib import Path

from oso.platforms.config import getProfileSeed


class BrowserLogin:
    def __init__(self, service, stagingPath=None):
        self.service = service
        self.stagingPath = Path(stagingPath or os.environ.get("OSO_VNC_BROWSER_DIR", "/browser-login"))
        self.lock = threading.Lock()
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

    def finishVnc(self, profileId):
        if self.activeProfileId != profileId:
            raise ValueError("This profile has no active VNC login")
        try:
            files = list(self.stagingPath.glob(".config/mozilla/firefox/*/cookies.sqlite"))
            if not files:
                raise ValueError("No Firefox cookies found; open TikTok in the VNC browser first")
            source = max(files, key=lambda path: path.stat().st_mtime)
            profile = self.service.profile(profileId)
            destination = self.service.browserProfile(profile)
            destination.mkdir(parents=True, exist_ok=True)
            # Initialize Playwright's profile FIRST: it can reset unrecognized files.
            if not (destination / "cookies.sqlite").exists():
                from invisible_playwright import InvisiblePlaywright
                with InvisiblePlaywright(profile_dir=str(destination), seed=getProfileSeed(destination), headless=True) as browser:
                    page = browser.new_page()
                    page.goto("https://www.tiktok.com", wait_until="domcontentloaded")
            # Use an SQLite backup rather than copying a live Firefox WAL file.
            with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as dbSource:
                with sqlite3.connect(destination / "cookies.sqlite") as dbDest:
                    dbSource.backup(dbDest)
        finally:
            self.activeProfileId = None
            self.lock.release()

    def cancelVnc(self, profileId):
        if self.activeProfileId != profileId:
            raise ValueError("This profile has no active VNC login")
        self.activeProfileId = None
        self.lock.release()
