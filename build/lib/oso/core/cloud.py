"""Extensible cloud provider registry. Uploads run outside the UI thread."""
import logging
from pathlib import Path

from .crypto import decodeSecret

logger = logging.getLogger("oso.cloud")


class MegaProvider:
    def upload(self, filePath, email, password, folder):
        try:
            from mega import Mega
        except ImportError as error:
            raise RuntimeError("Install the 'mega' extra to enable Mega uploads") from error
        client = Mega().login(email, password)
        folder = folder.strip("/")
        target = None
        if folder:
            # Find a folder by its entire path (not just the final name).
            target = client.find_path_descriptor(folder)
            if not target:
                client.create_folder(folder)
                target = client.find_path_descriptor(folder)
            if not target:
                raise RuntimeError("Unable to create or locate Mega cloud subfolder")
        client.upload(str(filePath), dest=target)


PROVIDERS = {"mega": MegaProvider()}


def uploadVideo(service, videoId):
    video = service.video(videoId)
    profile = service.profile(video["profile_id"])
    if not profile["auto_upload"] or not profile["cloud_id"]:
        return False
    account = service.cloudAccount(profile["cloud_id"])
    provider = PROVIDERS.get(account["provider"])
    if provider is None:
        raise ValueError("Unknown cloud provider")
    provider.upload(Path(video["path"]), account["email"],
                    decodeSecret(account["secret"], service.passphrases.load()), profile["cloud_folder"])
    service.db.execute("UPDATE videos SET uploaded_at=? WHERE id=?", (__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), videoId))
    if profile["delete_uploaded"]:
        Path(video["path"]).unlink(missing_ok=True)
        service.db.execute("DELETE FROM videos WHERE id=?", (videoId,))
    return True
