"""Asynchronous channel supervision; the UI never performs browser or FFmpeg I/O."""
import asyncio
import logging
import shutil
import time
from pathlib import Path

from oso.platforms.browser import BrowserSession, checkLiveWithRecovery
from oso.platforms.config import getProfileSeed
from oso.platforms.profile import createBrowserFactory
from oso.platforms.recording import RecordingJob
from oso.platforms.streams import getLiveStreams
from .cloud import uploadVideo

logger = logging.getLogger("oso.recorder")
CHECK_INTERVAL_SECONDS = 60


class TikTokPlatform:
    def check(self, service, channel):
        profile = service.profile(channel["profile_id"])
        base = service.browserProfile(profile)
        base.mkdir(parents=True, exist_ok=True)
        # First launch is essential before importing Firefox cookies, and also
        # allows anonymous checks where TikTok doesn't require authentication.
        if not (base / "cookies.sqlite").exists():
            from invisible_playwright import InvisiblePlaywright
            with InvisiblePlaywright(profile_dir=str(base), seed=getProfileSeed(base), headless=True) as browser:
                page = browser.new_page()
                page.goto("https://www.tiktok.com", wait_until="domcontentloaded", timeout=45000)
        factory = createBrowserFactory(base, channel["username"])
        clonedPaths = []
        # Our factory makes an isolated clone for every browser restart.
        def wrappedFactory():
            browser = factory()
            clonedPaths.append(factory.lastProfileCopy)
            return browser
        try:
            with BrowserSession(wrappedFactory) as session:
                return checkLiveWithRecovery(session, channel["username"], getLiveStreams)
        finally:
            # Clones intentionally survive only until the browser is closed.
            for clonedPath in clonedPaths:
                if clonedPath != base and clonedPath.name.startswith("profile_"):
                    shutil.rmtree(clonedPath, ignore_errors=True)


PLATFORMS = {"tiktok": TikTokPlatform()}


class RecorderManager:
    def __init__(self, service, checker=None):
        self.service = service
        self.checker = checker  # Optional injectable checker for tests.
        self.jobs = {}  # id -> {'job', 'manual', 'status', 'lastError', 'live'}
        self.nextChecks = {}
        self.probes = set()
        self.lock = asyncio.Lock()
        self.stopEvent = asyncio.Event()
        self.runner = None
        self.browserLimit = asyncio.Semaphore(2)
        self.lastCleanup = 0
        self.lastCloudRetry = 0
        self.pendingUploads = set()

    def snapshot(self):
        return {str(id): {"recording": bool(state.get("job") and state["job"].isRecording()),
                           "manual": state["manual"], "live": state["live"],
                           "status": state["status"], "error": state["lastError"]}
                for id, state in self.jobs.items()}

    def state(self, channelId):
        return self.snapshot().get(str(channelId), {"recording": False, "manual": False,
                                                     "live": None, "status": "idle", "error": ""})

    async def start(self):
        if not self.runner:
            self.stopEvent.clear()
            self.runner = asyncio.create_task(self.run(), name="oso-recorder")

    async def shutdown(self):
        self.stopEvent.set()
        if self.runner:
            await self.runner
            self.runner = None
        for task in list(self.probes):
            task.cancel()
        if self.probes:
            await asyncio.gather(*self.probes, return_exceptions=True)
        self.probes.clear()
        for state in self.jobs.values():
            if state.get("job") and state["job"].isRecording():
                await asyncio.to_thread(state["job"].stop)
        await self.reapJobs()

    async def run(self):
        while not self.stopEvent.is_set():
            try:
                await self.reapJobs()
                now = time.monotonic()
                for channel in await asyncio.to_thread(self.service.channels):
                    profile = await asyncio.to_thread(self.service.profile, channel["profile_id"])
                    if not (channel["enabled"] and profile["enabled"]):
                        continue
                    state = self.jobs.get(channel["id"])
                    if state and state.get("job") and state["job"].isRecording():
                        continue
                    if now >= self.nextChecks.get(channel["id"], 0) and not (state and state["status"] == "checking"):
                        self.nextChecks[channel["id"]] = now + CHECK_INTERVAL_SECONDS
                        self._spawn(self._probe(channel["id"], manual=False, record=bool(channel["auto_record"])))
                if now - self.lastCleanup > 300:
                    self.lastCleanup = now
                    await asyncio.to_thread(self.service.deleteExpiredVideos)
                if now - self.lastCloudRetry > 300:
                    self.lastCloudRetry = now
                    for video in await asyncio.to_thread(self.service.db.all, "SELECT id FROM videos WHERE uploaded_at IS NULL"):
                        if video["id"] not in self.pendingUploads:
                            self._spawn(self._upload(video["id"]))
            except Exception:
                logger.exception("Scheduler iteration failed")
            try:
                await asyncio.wait_for(self.stopEvent.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.probes.add(task)
        task.add_done_callback(self.probes.discard)
        return task

    async def beginManual(self, channelId):
        channel = await asyncio.to_thread(self.service.channel, channelId)
        profile = await asyncio.to_thread(self.service.profile, channel["profile_id"])
        if not channel["enabled"] or not profile["enabled"]:
            raise ValueError("Enable the profile and channel before recording")
        state = self.state(channelId)
        if state["recording"] or state["status"] == "checking":
            raise ValueError("Channel is already recording or checking")
        self._spawn(self._probe(channelId, manual=True, record=True))

    async def stopManual(self, channelId):
        state = self.jobs.get(channelId)
        if not state or not state["manual"] or not state.get("job") or not state["job"].isRecording():
            raise ValueError("Only manually started recordings can be stopped")
        await asyncio.to_thread(state["job"].stop)
        await self._finalize(channelId, state)

    async def checkStatus(self, channelId):
        channel = await asyncio.to_thread(self.service.channel, channelId)
        profile = await asyncio.to_thread(self.service.profile, channel["profile_id"])
        if not channel["enabled"] or not profile["enabled"]:
            raise ValueError("Enable the profile and channel before checking")
        state = self.state(channelId)
        if state["status"] == "checking":
            raise ValueError("Channel is already checking")
        self._spawn(self._probe(channelId, manual=False, record=False))

    async def _probe(self, channelId, manual, record):
        state = self.jobs.setdefault(channelId, {"job": None, "manual": False, "live": None,
                                                  "status": "idle", "lastError": ""})
        if state["status"] == "checking" or (state.get("job") and state["job"].isRecording()):
            return
        state.update(status="checking", lastError="")
        try:
            channel = await asyncio.to_thread(self.service.channel, channelId)
            async with self.browserLimit:
                if self.checker:
                    urls, agent = await asyncio.to_thread(self.checker, self.service, channel)
                else:
                    urls, agent = await asyncio.to_thread(PLATFORMS[channel["platform"]].check, self.service, channel)
            state["live"] = bool(urls)
            if not urls:
                state["status"] = "offline"
                return
            if not record:
                state["status"] = "live"
                return
            if self.stopEvent.is_set():
                return
            profile = await asyncio.to_thread(self.service.profile, channel["profile_id"])
            root = self.service.videoRoot(profile) / channel["platform"]
            job = RecordingJob(channel["username"], root)
            await asyncio.to_thread(job.start, urls, agent)
            state.update(job=job, manual=manual, status="recording" if job.isRecording() else "error")
            if not job.isRecording():
                state["lastError"] = "FFmpeg did not start"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state.update(status="error", lastError=str(error), live=None)
            logger.exception("Cannot check live channel %s", channelId)
        finally:
            self.nextChecks[channelId] = time.monotonic() + CHECK_INTERVAL_SECONDS

    async def reapJobs(self):
        for channelId, state in list(self.jobs.items()):
            job = state.get("job")
            if job is not None and job.isRecording():
                # update() automatically falls back to another stream URL.
                await asyncio.to_thread(job.update)
            if job is not None and not job.isRecording():
                await self._finalize(channelId, state)

    async def _finalize(self, channelId, state):
        job = state.get("job")
        state["job"] = None
        state["manual"] = False
        state["status"] = "idle"
        if not job or not job.outputFile or not job.outputFile.exists() or job.outputFile.stat().st_size == 0:
            return
        try:
            videoId = await asyncio.to_thread(self.service.registerVideo, channelId, job.outputFile)
            if videoId:
                self._spawn(self._upload(videoId))
        except Exception:
            logger.exception("Cannot register recorded file")

    async def _upload(self, videoId):
        if videoId in self.pendingUploads:
            return
        self.pendingUploads.add(videoId)
        try:
            await asyncio.to_thread(uploadVideo, self.service, videoId)
        except Exception:
            logger.exception("Cloud upload of video %s failed", videoId)
        finally:
            self.pendingUploads.discard(videoId)
