"""Password-protected browser UI. Business rules live in AppService, not HTTP."""
import asyncio
import hmac
import logging
import os
import secrets
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from oso.core.browser_login import BrowserLogin
from oso.core.i18n import translations
from oso.core.logging import configureLogging
from oso.core.paths import AppPaths
from oso.core.recorder import RecorderManager
from oso.core.service import AppService

logger = logging.getLogger("oso.web")
STATIC = Path(__file__).parent / "static"


class ActionRequest(BaseModel):
    action: str
    payload: dict = {}


def createApp(data=None, videos=None, password=None, startRecorder=True):
    password = password if password is not None else os.environ.get("OSO_WEB_PASSWORD")
    if not password:
        raise RuntimeError("Set a non-empty OSO_WEB_PASSWORD to start web mode")
    paths = AppPaths.create("web", data, videos)
    configureLogging(paths)
    service = AppService(paths, "web")
    browser = BrowserLogin(service)
    manager = RecorderManager(service)
    sessions = set()
    failures = {}

    @asynccontextmanager
    async def lifespan(app):
        if startRecorder:
            await manager.start()
        yield
        await manager.shutdown()

    app = FastAPI(title="Oso Stream Record", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service = service
    app.state.manager = manager
    app.state.browser = browser
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def authenticated(request):
        session = request.cookies.get("oso_session", "")
        return bool(session) and session in sessions

    def requireAuth(request):
        if not authenticated(request):
            raise HTTPException(status_code=401, detail="Authentication required")
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlsplit
                originParts = urlsplit(origin)
                if (originParts.netloc != request.headers.get("host") or originParts.scheme not in ("http", "https")):
                    raise HTTPException(status_code=403, detail="Invalid request origin")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if not authenticated(request):
            return HTMLResponse((STATIC / "login.html").read_text(encoding="utf-8"))
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.post("/login")
    async def login(request: Request, passwordValue: str = Form(alias="password")):
        address = request.client.host if request.client else "unknown"
        now = __import__("time").monotonic()
        count, since = failures.get(address, (0, now))
        if now - since > 300:
            count, since = 0, now
        if count >= 10:
            raise HTTPException(429, "Too many login attempts; retry in five minutes")
        if not hmac.compare_digest(passwordValue, password):
            failures[address] = (count + 1, since)
            return HTMLResponse((STATIC / "login.html").read_text(encoding="utf-8").replace("<!--ERROR-->", '<p class="error">Incorrect password</p>'), status_code=401)
        failures.pop(address, None)
        key = secrets.token_urlsafe(32)
        sessions.add(key)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("oso_session", key, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=7*86400)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        requireAuth(request)
        sessions.discard(request.cookies.get("oso_session"))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("oso_session")
        return response

    @app.get("/locale/{lang}")
    def locale(lang: str):
        if lang not in ("en", "es", "pt"):
            raise HTTPException(404, "Unknown language")
        return translations(lang)

    @app.get("/state")
    async def state(request: Request):
        requireAuth(request)
        profiles, channels, videos, accounts, settings = await asyncio.gather(
            asyncio.to_thread(service.profiles), asyncio.to_thread(service.channels),
            asyncio.to_thread(service.videos), asyncio.to_thread(service.cloudAccounts),
            asyncio.to_thread(service.settings))
        return {"profiles": profiles, "channels": channels, "videos": videos,
                "accounts": accounts, "settings": settings, "statuses": manager.snapshot(),
                "vnc_active": browser.activeProfileId,
                "vnc_port": int(os.environ.get("OSO_VNC_PORT", "3001"))}

    @app.post("/action")
    async def action(request: Request, params: ActionRequest):
        requireAuth(request)
        name = params.action
        args = params.payload
        try:
            if name == "profile.create":
                result = await asyncio.to_thread(service.createProfile, args["name"])
            elif name == "profile.update":
                item = dict(args)
                profileId = int(item.pop("id"))
                result = await asyncio.to_thread(service.updateProfile, profileId, **item)
            elif name == "profile.delete":
                await asyncio.to_thread(service.deleteProfile, int(args["id"]))
                result = True
            elif name == "channel.create":
                result = await asyncio.to_thread(service.createChannel, int(args["profile_id"]), args["platform"], args["username"])
            elif name == "channel.update":
                item = dict(args)
                channelId = int(item.pop("id"))
                result = await asyncio.to_thread(service.updateChannel, channelId, **item)
            elif name == "channel.delete":
                await asyncio.to_thread(service.deleteChannel, int(args["id"]))
                result = True
            elif name == "channel.check":
                await manager.checkStatus(int(args["id"]))
                result = True
            elif name == "channel.start":
                await manager.beginManual(int(args["id"]))
                result = True
            elif name == "channel.stop":
                await manager.stopManual(int(args["id"]))
                result = True
            elif name == "account.create":
                result = await asyncio.to_thread(service.createCloudAccount, "mega", args["alias"], args["email"], args["password"])
            elif name == "account.delete":
                await asyncio.to_thread(service.deleteCloudAccount, int(args["id"]))
                result = True
            elif name == "settings.update":
                result = await asyncio.to_thread(service.updateSettings, language=args.get("language"), passphrase=args.get("passphrase"))
            elif name == "vnc.start":
                result = await asyncio.to_thread(browser.startVnc, int(args["id"]))
            elif name == "vnc.finish":
                result = await asyncio.to_thread(browser.finishVnc, int(args["id"]))
            elif name == "vnc.cancel":
                result = await asyncio.to_thread(browser.cancelVnc, int(args["id"]))
            else:
                raise ValueError("Unknown action")
            return {"ok": True, "result": result}
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(400, str(error)) from error
        except Exception:
            logger.exception("Action failed: %s", name)
            raise HTTPException(500, "Operation failed. Check the application logs")

    @app.post("/export")
    async def export(request: Request):
        requireAuth(request)
        try:
            body = await request.json()
            key = body.get("passphrase", "")
            if not hmac.compare_digest(key, service.passphrases.load()):
                raise ValueError("Incorrect passphrase")
            raw = await asyncio.to_thread(service.exportArchive, key)
            return Response(raw, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="oso-stream-record-backup.zip"'})
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/import")
    async def importData(request: Request, file: UploadFile = File(), passphrase: str = Form(), confirm: str = Form()):
        requireAuth(request)
        if confirm != "REPLACE":
            raise HTTPException(400, "Explicit replacement confirmation required")
        if browser.activeProfileId is not None:
            raise HTTPException(409, "Finish the browser login before importing")
        raw = await file.read(512 * 1024 * 1024 + 1)
        if len(raw) > 512 * 1024 * 1024:
            raise HTTPException(413, "Archive exceeds 512 MB")
        await manager.shutdown()
        try:
            await asyncio.to_thread(service.importArchive, raw, passphrase)
        except (ValueError, Exception) as error:
            if startRecorder:
                await manager.start()
            raise HTTPException(400, str(error)) from error
        if startRecorder:
            await manager.start()
        return {"ok": True}

    @app.get("/videos/{videoId}/download")
    async def download(request: Request, videoId: int):
        requireAuth(request)
        try:
            item = await asyncio.to_thread(service.video, videoId)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        return FileResponse(item["path"], filename=Path(item["path"]).name, media_type="application/octet-stream")

    @app.get("/videos/{videoId}/watch")
    async def watch(request: Request, videoId: int):
        requireAuth(request)
        try:
            item = await asyncio.to_thread(service.video, videoId)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

        def chunks():
            process = subprocess.Popen(["ffmpeg", "-v", "error", "-i", item["path"], "-c:v", "libx264", "-preset", "ultrafast",
                                        "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                while True:
                    data = process.stdout.read(64 * 1024)
                    if not data:
                        break
                    yield data
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

        return StreamingResponse(chunks(), media_type="video/mp4", headers={"Cache-Control": "no-store"})

    return app


def main():
    import uvicorn
    uvicorn.run(createApp(), host="0.0.0.0", port=int(os.environ.get("OSO_WEB_PORT", "8080")))


if __name__ == "__main__":
    main()
