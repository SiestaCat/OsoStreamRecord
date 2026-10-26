import concurrent.futures
import sqlite3
import time
from pathlib import Path

import pytest

from oso.core.paths import AppPaths
from oso.core.service import AppService
from oso.core.crypto import decodeSecret


def test_initial_configuration(service):
    assert service.profiles()[0]["name"] == "Profile 1"
    assert service.profiles()[0]["enabled"] == 1
    assert service.settings()["language"] == ""
    assert service.paths.data != service.paths.videos
    assert (service.paths.data / "passphrase").is_file()
    assert service.db.one("PRAGMA journal_mode")["journal_mode"] == "wal"


def test_profiles_and_channels(service):
    profileId = service.createProfile("Main account")
    service.updateProfile(profileId, enabled=False, delete_older_hours=24)
    assert service.profile(profileId)["enabled"] == 0
    assert service.profile(profileId)["delete_older_hours"] == 24
    channelId = service.createChannel(profileId, "tiktok", "@SomeUser")
    channel = service.channel(channelId)
    assert channel["username"] == "someuser"
    assert channel["auto_record"] == 0
    service.updateChannel(channelId, auto_record=True)
    assert service.channel(channelId)["auto_record"] == 1
    with pytest.raises(ValueError):
        service.createChannel(profileId, "youtube", "hello")
    with pytest.raises(ValueError):
        service.createChannel(profileId, "tiktok", "@SomeUser")
    with pytest.raises(ValueError):
        service.updateProfile(profileId, video_dir="/tmp/not-allowed")


def test_concurrent_sqlite_writes(service):
    def create(index):
        service.createProfile(f"Profile {index + 2}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(create, range(40)))
    assert len(service.profiles()) == 41


def test_encrypted_secrets_rekey(service):
    old = service.settings()["passphrase"]
    account = service.createCloudAccount("mega", "backup", "user@example.org", "privatePassword!")
    row = service.cloudAccount(account)
    assert "privatePassword!" not in row["secret"]
    assert decodeSecret(row["secret"], old) == "privatePassword!"
    service.updateSettings(passphrase="a new long passphrase", language="pt")
    assert service.settings()["language"] == "pt"
    assert decodeSecret(service.cloudAccount(account)["secret"], "a new long passphrase") == "privatePassword!"
    with pytest.raises(Exception):
        decodeSecret(service.cloudAccount(account)["secret"], old)


def test_video_registration_security_and_retention(service):
    channelId = service.createChannel(1, "tiktok", "testuser")
    profile = service.profile(1)
    folder = service.videoRoot(profile) / "tiktok"
    folder.mkdir(parents=True)
    path = folder / "testuser-2026-07-01.mkv"
    path.write_bytes(b"a" * 2048)
    videoId = service.registerVideo(channelId, path)
    assert service.video(videoId)["size"] == 2048
    assert service.videos(channelId=channelId, search="testuser", sort="size")
    outside = service.paths.data / "db.sqlite"
    outside.write_bytes(b"test")
    with pytest.raises(ValueError):
        service.registerVideo(channelId, outside)
    service.updateProfile(1, delete_older_hours=1)
    import os
    oldTime = time.time() - 2 * 3600
    os.utime(path, (oldTime, oldTime))
    assert service.deleteExpiredVideos() == 1
    assert not path.exists()
    assert service.videos() == []


def test_no_path_traversal(service):
    with pytest.raises(ValueError):
        service.createProfile("../")
    with pytest.raises(ValueError):
        service.createChannel(1, "tiktok", "../etc/passwd")
