"""SQLite persistence. Short transactions, WAL and one writer lock per process."""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone


def utcNow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.writeLock = threading.RLock()
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def transaction(self):
        with self.writeLock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def all(self, sql, args=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.connect() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def execute(self, sql, args=()):
        with self.transaction() as conn:
            cursor = conn.execute(sql, args)
            return cursor.lastrowid

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def setSetting(self, key, value):
        self.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def initialize(self):
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                    directory TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1,
                    video_dir TEXT, auto_upload INTEGER NOT NULL DEFAULT 0,
                    cloud_id INTEGER, cloud_folder TEXT NOT NULL DEFAULT '/',
                    delete_uploaded INTEGER NOT NULL DEFAULT 0, delete_older_hours INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(cloud_id) REFERENCES cloud_accounts(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
                    platform TEXT NOT NULL, username TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, auto_record INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    UNIQUE(profile_id,platform,username)
                );
                CREATE TABLE IF NOT EXISTS cloud_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
                    alias TEXT NOT NULL UNIQUE, email TEXT NOT NULL, secret TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
                    channel_id INTEGER, platform TEXT NOT NULL, username TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,
                    created_at TEXT NOT NULL, uploaded_at TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_channels_profile ON channels(profile_id);
                CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
            """)
            count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if not count:
                conn.execute("INSERT INTO profiles(name,directory,created_at) VALUES(?,?,?)", ("Profile 1", "Profile_1", utcNow()))
