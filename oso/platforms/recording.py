import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


RETRY_SECONDS = 60
logger = logging.getLogger("oso.ffmpeg")


class RecordingJob:
    def __init__(self, username, outputDir):
        self.username = username
        self.outputDir = Path(outputDir)
        self.nextCheckAt = 0.0
        self.process = None
        self.logFile = None
        self.outputFile = None
        self.streamUrls = []
        self.sourceIndex = 0
        self.userAgent = ""

    def isRecording(self):
        return self.process is not None

    def start(self, streamUrls, userAgent):
        self.outputDir.mkdir(parents=True, exist_ok=True)
        self.outputFile = self.outputDir / f"{self.username}_{datetime.now():%Y-%m-%d_%H-%M-%S}.mkv"
        self.streamUrls = list(streamUrls)
        self.sourceIndex = 0
        self.userAgent = userAgent
        if not self.startNextSource():
            self.finish()

    def startNextSource(self):
        liveUrl = f"https://www.tiktok.com/@{self.username}/live"
        while self.sourceIndex < len(self.streamUrls):
            streamUrl = self.streamUrls[self.sourceIndex]
            self.sourceIndex += 1
            parsedStream = urlsplit(streamUrl)
            print(f"@{self.username} | Source: {parsedStream.netloc}{parsedStream.path}", flush=True)
            print(f"@{self.username} | Recording: {self.outputFile}", flush=True)

            try:
                self.process = subprocess.Popen([
                    "ffmpeg",
                    "-hide_banner",
                    "-user_agent", self.userAgent,
                    "-referer", liveUrl,
                    "-analyzeduration", "30000000",
                    "-probesize", "50000000",
                    "-i", streamUrl,
                    "-map", "0:v:0",
                    "-map", "0:a:0?",
                    "-c", "copy",
                    "-y",
                    str(self.outputFile)
                ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                threading.Thread(target=self.forwardLogs, args=(self.process.stderr,), daemon=True).start()
                return True
            except OSError as error:
                self.closeHandles()
                print(f"@{self.username} | Failed to start FFmpeg: {error}", flush=True)

        print(f"@{self.username} | No stream source could be recorded. If H.265 is the only option, update FFmpeg to version 8.1 or later.", flush=True)
        return False

    def forwardLogs(self, stream):
        try:
            for line in iter(stream.readline, b""):
                logger.debug("FFmpeg @%s %s", self.username, line.decode(errors="replace").rstrip())
        finally:
            stream.close()

    def closeHandles(self):
        if self.process is not None and self.process.stdin is not None:
            self.process.stdin.close()
        if self.logFile is not None:
            self.logFile.close()
        self.process = None
        self.logFile = None

    def finish(self):
        self.streamUrls = []
        self.sourceIndex = 0
        self.nextCheckAt = time.monotonic() + RETRY_SECONDS
        print(f"@{self.username} | Recording finished. Retrying in {RETRY_SECONDS} seconds...", flush=True)

    def update(self):
        if self.process is None:
            return
        result = self.process.poll()
        if result is None:
            return

        self.closeHandles()
        if result == 0:
            self.finish()
            return
        if self.outputFile.exists() and self.outputFile.stat().st_size > 0:
            print(f"@{self.username} | FFmpeg exited with an error; retaining partial recording: {self.outputFile}", flush=True)
            self.finish()
            return

        self.outputFile.unlink(missing_ok=True)
        print(f"@{self.username} | Stream URL could not be recorded. Trying another available source...", flush=True)
        if not self.startNextSource():
            self.finish()

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b"q\n")
                self.process.stdin.flush()
                self.process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
        self.closeHandles()
        print(f"@{self.username} | Recording stopped; retaining the output file.", flush=True)
