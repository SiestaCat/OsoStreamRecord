"""Non-HTTP application API used by both user interfaces."""
import io
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .crypto import PassphraseStore, decodeSecret, encodeSecret
from .db import Database, utcNow
from .paths import inside, safeName

logger = logging.getLogger("oso.service")
SUPPORTED_PLATFORMS = ("tiktok",)
SUPPORTED_LANGUAGES = ("en", "es", "pt")


def flag(value):
    return 1 if value is True or str(value).lower() in ("true", "1", "on", "yes") else 0


class AppService:
    def __init__(self, paths, mode="web"):
        self.paths = paths
        self.mode = mode
        self.db = Database(paths.data / "oso.sqlite")
        self.passphrases = PassphraseStore(paths.data / "passphrase")

    def settings(self):
        return {"language": self.db.setting("language", ""),
                "default_video_dir": self.db.setting("default_video_dir", str(self.paths.videos)),
                "passphrase": self.passphrases.load()}

    def updateSettings(self, *, language=None, default_video_dir=None, passphrase=None):
        if language is not None:
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError("Unsupported language")
            self.db.setSetting("language", language)
        if default_video_dir is not None:
            if self.mode != "desktop":
                raise ValueError("Video directory cannot be changed in web mode")
            videoPath = Path(default_video_dir).expanduser().resolve()
            if inside(videoPath, self.paths.data) or inside(self.paths.data, videoPath):
                raise ValueError("Video and config directories must be separate")
            videoPath.mkdir(parents=True, exist_ok=True)
            self.db.setSetting("default_video_dir", str(videoPath))
        if passphrase is not None and passphrase != self.passphrases.load():
            if not passphrase:
                raise ValueError("Passphrase cannot be empty")
            oldPassphrase = self.passphrases.load()
            # Re-key every encrypted password inside the same transaction.
            with self.db.transaction() as conn:
                accounts = conn.execute("SELECT id,secret FROM cloud_accounts").fetchall()
                for account in accounts:
                    clear = decodeSecret(account["secret"], oldPassphrase)
                    conn.execute("UPDATE cloud_accounts SET secret=? WHERE id=?", (encodeSecret(clear, passphrase), account["id"]))
                self.passphrases.save(passphrase)

    def profiles(self):
        return self.db.all("SELECT * FROM profiles ORDER BY id")

    def profile(self, profileId):
        row = self.db.one("SELECT * FROM profiles WHERE id=?", (profileId,))
        if not row:
            raise ValueError("Profile not found")
        return row

    def createProfile(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Profile name cannot be blank")
        directory = safeName(name)
        try:
            return self.db.execute("INSERT INTO profiles(name,directory,created_at) VALUES(?,?,?)", (name, directory, utcNow()))
        except sqlite3.IntegrityError as error:
            raise ValueError("Profile name or folder already exists") from error

    def updateProfile(self, profileId, **changes):
        profile = self.profile(profileId)
        fields = ("name", "enabled", "video_dir", "auto_upload", "cloud_id", "cloud_folder", "delete_uploaded", "delete_older_hours")
        changes = {key: value for key, value in changes.items() if key in fields}
        if not changes:
            return profile
        for key in ("enabled", "auto_upload", "delete_uploaded"):
            if key in changes:
                changes[key] = flag(changes[key])
        if "name" in changes and not str(changes["name"]).strip():
            raise ValueError("Profile name cannot be blank")
        if "video_dir" in changes:
            if self.mode != "desktop":
                raise ValueError("Per-profile video paths are desktop-only")
            value = changes["video_dir"]
            if value:
                value = str(Path(value).expanduser().resolve())
                if inside(value, self.paths.data) or inside(self.paths.data, value):
                    raise ValueError("Video path overlaps the configuration directory")
                Path(value).mkdir(parents=True, exist_ok=True)
            changes["video_dir"] = value or None
        if "delete_older_hours" in changes:
            hours = changes["delete_older_hours"]
            changes["delete_older_hours"] = None if hours in (None, "", 0, "0") else int(hours)
            if changes["delete_older_hours"] is not None and changes["delete_older_hours"] <= 0:
                raise ValueError("Retention hours must be positive")
        if changes.get("cloud_id") in ("", "0", 0):
            changes["cloud_id"] = None
        if changes.get("cloud_id") is not None and "cloud_id" in changes:
            self.cloudAccount(int(changes["cloud_id"]))
        sql = "UPDATE profiles SET " + ", ".join(f"{key}=?" for key in changes) + " WHERE id=?"
        try:
            self.db.execute(sql, (*changes.values(), profileId))
        except sqlite3.IntegrityError as error:
            raise ValueError("Profile name already exists") from error
        return self.profile(profileId)

    def deleteProfile(self, profileId):
        self.profile(profileId)
        self.db.execute("DELETE FROM profiles WHERE id=?", (profileId,))

    def channels(self, profileId=None):
        if profileId is None:
            return self.db.all("SELECT * FROM channels ORDER BY id")
        return self.db.all("SELECT * FROM channels WHERE profile_id=? ORDER BY id", (profileId,))

    def channel(self, channelId):
        row = self.db.one("SELECT * FROM channels WHERE id=?", (channelId,))
        if not row:
            raise ValueError("Channel not found")
        return row

    def createChannel(self, profileId, platform, username):
        from oso.platforms.config import normalizeUsername
        self.profile(profileId)
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Unsupported platform")
        username = normalizeUsername(username).lower()
        try:
            return self.db.execute("INSERT INTO channels(profile_id,platform,username,created_at) VALUES(?,?,?,?)", (profileId, platform, username, utcNow()))
        except sqlite3.IntegrityError as error:
            raise ValueError("This channel is already in the profile") from error

    def updateChannel(self, channelId, *, enabled=None, auto_record=None, username=None):
        channel = self.channel(channelId)
        changes = {}
        if enabled is not None:
            changes["enabled"] = flag(enabled)
        if auto_record is not None:
            changes["auto_record"] = flag(auto_record)
        if username is not None:
            from oso.platforms.config import normalizeUsername
            changes["username"] = normalizeUsername(username).lower()
        if changes:
            try:
                self.db.execute("UPDATE channels SET " + ", ".join(f"{k}=?" for k in changes) + " WHERE id=?", (*changes.values(), channelId))
            except sqlite3.IntegrityError as error:
                raise ValueError("Duplicate username in profile") from error
        return self.channel(channelId)

    def deleteChannel(self, channelId):
        self.channel(channelId)
        self.db.execute("DELETE FROM channels WHERE id=?", (channelId,))

    def videoRoot(self, profile):
        base = (profile.get("video_dir") if self.mode == "desktop" else None) or self.db.setting("default_video_dir", str(self.paths.videos))
        if self.mode == "web":
            base = str(self.paths.videos)
        result = (Path(base).expanduser() if profile.get("video_dir") and self.mode == "desktop"
                  else Path(base).expanduser() / profile["directory"]).resolve()
        if inside(result, self.paths.data):
            raise ValueError("Video directory overlaps data")
        return result

    def browserProfile(self, profile):
        return self.paths.data / "browser" / "firefox" / profile["directory"]

    def registerVideo(self, channelId, path):
        channel = self.channel(channelId)
        profile = self.profile(channel["profile_id"])
        path = Path(path).resolve()
        if not inside(path, self.videoRoot(profile)) or not path.is_file():
            raise ValueError("Video is not inside this profile folder")
        if path.stat().st_size < 1:
            return None
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO videos(profile_id,channel_id,platform,username,path,size,created_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET size=excluded.size""",
                (profile["id"], channelId, channel["platform"], channel["username"], str(path), path.stat().st_size, utcNow()))
            row = conn.execute("SELECT id FROM videos WHERE path=?", (str(path),)).fetchone()
        return row[0]

    def videos(self, *, channelId=None, search="", sort="date", descending=True):
        orderFields = {"date": "v.created_at", "name": "v.path", "channel": "v.username", "size": "v.size"}
        sql = "SELECT v.*, p.name AS profile_name FROM videos v JOIN profiles p ON p.id=v.profile_id WHERE 1=1"
        args = []
        if channelId:
            sql += " AND v.channel_id=?"
            args.append(channelId)
        if search:
            sql += " AND (v.path LIKE ? OR v.username LIKE ?)"
            args.extend((f"%{search}%", f"%{search}%"))
        sql += " ORDER BY " + orderFields.get(sort, "v.created_at") + (" DESC" if descending else " ASC")
        return [{**v, "name": Path(v["path"]).name, "exists": Path(v["path"]).is_file()} for v in self.db.all(sql, args)]

    def video(self, videoId):
        item = self.db.one("SELECT * FROM videos WHERE id=?", (videoId,))
        if not item:
            raise ValueError("Video not found")
        profile = self.profile(item["profile_id"])
        if not inside(item["path"], self.videoRoot(profile)):
            raise ValueError("Video path is outside the profile folder")
        if not Path(item["path"]).is_file():
            raise ValueError("Video file is missing")
        return item

    def cloudAccounts(self):
        return self.db.all("SELECT id,provider,alias,email,created_at FROM cloud_accounts ORDER BY id")

    def cloudAccount(self, accountId):
        row = self.db.one("SELECT * FROM cloud_accounts WHERE id=?", (accountId,))
        if not row:
            raise ValueError("Cloud account not found")
        return row

    def createCloudAccount(self, provider, alias, email, password):
        if provider != "mega" or not alias.strip() or not email.strip() or not password:
            raise ValueError("Provide a valid Mega account, alias, email and password")
        try:
            return self.db.execute("INSERT INTO cloud_accounts(provider,alias,email,secret,created_at) VALUES(?,?,?,?,?)",
                                   (provider, alias.strip(), email.strip(), encodeSecret(password, self.passphrases.load()), utcNow()))
        except sqlite3.IntegrityError as error:
            raise ValueError("Alias already exists") from error

    def deleteCloudAccount(self, accountId):
        self.cloudAccount(accountId)
        self.db.execute("DELETE FROM cloud_accounts WHERE id=?", (accountId,))

    def deleteExpiredVideos(self):
        count = 0
        for profile in self.profiles():
            hours = profile["delete_older_hours"]
            if not hours:
                continue
            limit = datetime.now(timezone.utc) - timedelta(hours=hours)
            videos = self.db.all("SELECT * FROM videos WHERE profile_id=?", (profile["id"],))
            for video in videos:
                path = Path(video["path"])
                if path.exists() and inside(path, self.videoRoot(profile)) and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < limit:
                    path.unlink()
                    self.db.execute("DELETE FROM videos WHERE id=?", (video["id"],))
                    count += 1
        return count

    def exportArchive(self, passphrase):
        """AES encrypted ZIP using the user passphrase; no passphrase file inside."""
        import pyzipper
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "oso.sqlite"
            with self.db.connect() as source, sqlite3.connect(snapshot) as backup:
                source.backup(backup)
            output = io.BytesIO()
            with pyzipper.AESZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
                archive.setpassword(passphrase.encode())
                archive.setencryption(pyzipper.WZ_AES, nbits=256)
                archive.write(snapshot, "oso.sqlite")
                for path in self.paths.data.rglob("*"):
                    if not path.is_file() or path.name in ("passphrase", "oso.sqlite", "oso.sqlite-shm", "oso.sqlite-wal"):
                        continue
                    archive.write(path, str(path.relative_to(self.paths.data)))
            return output.getvalue()

    def importArchive(self, raw, passphrase):
        """Validate encrypted archive completely before replacing persistent data."""
        import pyzipper
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            stage.mkdir()
            try:
                with pyzipper.AESZipFile(io.BytesIO(raw), "r") as archive:
                    archive.setpassword(passphrase.encode())
                    names = archive.namelist()
                    if "oso.sqlite" not in names or "passphrase" in names:
                        raise ValueError("Invalid backup content")
                    for item in archive.infolist():
                        target = (stage / item.filename).resolve()
                        if not inside(target, stage) or item.filename.startswith("/") or (item.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("Unsafe backup path")
                        if item.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(item, "r") as source, target.open("wb") as dest:
                                shutil.copyfileobj(source, dest)
            except (RuntimeError, EOFError, zipfile.BadZipFile) as error:
                raise ValueError("Incorrect passphrase or invalid archive") from error
            with sqlite3.connect(stage / "oso.sqlite") as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid database")
                try:
                    secret = conn.execute("SELECT secret FROM cloud_accounts LIMIT 1").fetchone()
                    if secret:
                        decodeSecret(secret[0], passphrase)
                except (sqlite3.Error, Exception) as error:
                    raise ValueError("Invalid archive database or passphrase") from error
            # Copy rather than moving staging: restore can be retried on failure.
            originalPassphrase = self.passphrases.load()
            backup = Path(tmp) / "original"
            backup.mkdir()
            retained = {"passphrase", "logs"}
            originalFiles = [p for p in self.paths.data.iterdir() if p.name not in retained]
            try:
                for item in originalFiles:
                    shutil.move(str(item), str(backup / item.name))
                for item in stage.iterdir():
                    shutil.move(str(item), str(self.paths.data / item.name))
                self.passphrases.save(passphrase)
                self.db.initialize()
            except Exception:
                for item in self.paths.data.iterdir():
                    if item.name not in retained:
                        if item.is_dir(): shutil.rmtree(item)
                        else: item.unlink()
                for item in backup.iterdir():
                    shutil.move(str(item), str(self.paths.data / item.name))
                self.passphrases.save(originalPassphrase)
                self.db.initialize()
                raise
