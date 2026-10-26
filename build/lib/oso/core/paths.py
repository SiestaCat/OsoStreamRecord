"""Application directories and safe folder names."""
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data: Path
    videos: Path

    @classmethod
    def create(cls, mode="desktop", data=None, videos=None):
        home = Path.home()
        defaultData = Path("/data") if mode == "web" else home / "OsoStreamRecord"
        defaultVideos = Path("/videos") if mode == "web" else home / "Videos" / "OsoStreamRecord"
        instance = cls(Path(data or os.environ.get("OSO_DATA_DIR") or defaultData).expanduser().resolve(),
                       Path(videos or os.environ.get("OSO_VIDEO_DIR") or defaultVideos).expanduser().resolve())
        if instance.data == instance.videos or instance.data in instance.videos.parents or instance.videos in instance.data.parents:
            raise ValueError("Data and video directories must not overlap")
        for folder in (instance.data, instance.videos, instance.data / "logs"):
            folder.mkdir(parents=True, exist_ok=True)
        return instance


def safeName(name):
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip()).strip("._-")
    if not name or name in (".", ".."):
        raise ValueError("Name must contain alphanumeric characters")
    return name[:72]


def inside(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    return path == root or root in path.parents
