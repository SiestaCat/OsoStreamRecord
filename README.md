# Oso Stream Record

Oso Stream Record is a Python application for monitoring and recording live channels, with two clients: an **in-process GTK 4 desktop application** and a **password-protected web application deployed with Docker**. Both clients use the same non-REST `AppService` Python business layer, SQLite database schema, and shared recording engine.

**Project status: implementation / integration build, version 0.1.0.** The SQLite, password login, service layer, web actions and mocked asynchronous recording flows have automated tests. The web Docker image, patched Firefox browser, real TikTok recordings, Mega uploads, graphical Linux AppImage, and Windows executable have **not** been end-to-end validated in the available build environment. Do not treat the desktop build scripts as verified release pipelines. See [Known limitations](#known-limitations) before deployment.

## Features

- One SQLite database for all profiles, accounts, channels, settings and video metadata; WAL, `busy_timeout`, short write transactions and a process-level writer lock.
- Initial language selection, with editable `oso/locales/en.json`, `oso/locales/es.json` and `oso/locales/pt.json`. Add a language by creating a new file and extending `SUPPORTED_LANGUAGES` and language selectors.
- Default `Profile 1`, plus isolated Firefox browser sessions per profile under `data/browser/firefox/PROFILE_DIRECTORY`.
- Profile enable/disable, cloud upload destination and account, delete-after-upload, hourly retention, and customizable desktop video folder.
- Platform registry that initially supports TikTok only. Adaptation of the supplied `tiktok-recorder` implementation for `invisible_playwright`, stream validation, session recovery, and FFmpeg recording with fallback stream URLs.
- Asynchronous background supervision. Active channels are checked approximately every 60 seconds, irrespective of whether auto-record is enabled. Manual recordings can be stopped; automatic ones continue until the live stream ends.
- Recorded videos in a separate storage root, organized as `PROFILE_DIRECTORY/PLATFORM/USERNAME_TIMESTAMP.mkv`.
- File listing, searching and sorting; web download and on-demand FFmpeg playback; desktop open-containing-folder.
- Cloud provider interface (currently Mega through `mega.py`) with alias, encrypted password, and asynchronous upload; failed uploads are retried periodically.
- AES-256-GCM cloud-credential encryption using a passphrase-derived PBKDF2 key. The passphrase is separately **obfuscated**, as expressly requested, rather than securely stored in a system key vault.
- AES-256 password-protected ZIP backup, using `pyzipper`, omitting the passphrase file and stored videos. Import validates the archive before replacing data. Videos are retained.
- Web password login with HttpOnly SameSite cookies, login attempt limiting and same-origin checks.
- Web VNC sign-in through a separate Docker Firefox container (one browser/one UI reservation at a time), with cookie transfer to an initialized patched-Firefox profile using a SQLite snapshot.
- Rotating DEBUG logs in `data/logs/oso.log`, with 9 backups plus the current file.

## Application layout

```text
oso/core/         Non-HTTP business API, SQLite, encryption, recorder, cloud, login
oso/platforms/    TikTok browser, stream discovery and FFmpeg adapter
oso/web/          FastAPI UI routes and HTML/CSS/JavaScript
oso/desktop/      GTK 4 client and optional system tray
oso/locales/      Editable locale files
build/            Docker build recipes and entry points
compose.yaml      Web and browser-login containers
tests/            Service, access-control, locale and recorder tests
```

The web application necessarily has HTTP UI endpoints (`/action`, `/state`, etc.). These **are not** the shared business API: that API is the `AppService` object, called directly by the web and desktop clients. No separate REST microservice is required.

## Run the web application with Docker

Requirements: Docker Engine with Compose, enough space for Firefox and captured streams (the browser engine alone is about 550 MB unpacked), and network access to TikTok and Mega as needed.

```bash
cp .env.example .env
# Edit .env and replace OSO_WEB_PASSWORD with a long random password.
mkdir -p data videos firefox-login
docker compose build
docker compose up -d
docker compose logs -f web
```

Navigate to **http://127.0.0.1:8080**; the web password comes from `OSO_WEB_PASSWORD` in `.env`. The default external web and Firefox ports are 8080 and 3001 respectively. To change these ports or their bind addresses, edit `.env` (see `.env.example`). No source-code changes are needed. The web application does not allow changing the Docker video path from the interface.

Firefox for interactive sign-in is available at **https://127.0.0.1:3001** with a self-signed certificate. Its basic-auth username defaults to `oso` (`OSO_VNC_USERNAME`) and its password uses `OSO_WEB_PASSWORD`. Select a profile, click *Open login browser*, open the VNC browser, log into TikTok, then click *Finish and save cookies*. **This must be performed while Firefox's profile and SQLite database are accessible via the mounted volume.**

Do not use the VNC Firefox browser for background recording; the background engine uses **headless** `invisible_playwright` and temporary cloned profiles. The VNC browser is an independent, headed Docker container only for obtaining authentication cookies. A Playwright profile is initialized *before* cookie import.

If `invisible_playwright` needs its patched engine updated, rebuild the web image:

```bash
docker compose build --no-cache web
docker compose up -d
```

### Without Compose

Build the application image:

```bash
docker build -t oso-stream-record:web .
```

Run the web process (without interactive VNC cookie import):

```bash
docker run --rm --shm-size=1gb \
  -p 127.0.0.1:8080:8080 \
  -v "$(pwd)/data:/data" \
  -v "$(pwd)/videos:/videos" \
  -e OSO_WEB_PASSWORD='replace-with-a-long-random-password' \
  oso-stream-record:web
```

For browser login use Compose (recommended), which adds the Firefox container and shares its `/config` at `/browser-login` in read-only mode for the web process.

**Security:** Both services bind only to `127.0.0.1` by default. If accessing remotely, use a trusted TLS reverse proxy and strong authentication, and restrict or tunnel the VNC endpoint. LinuxServer's Firefox desktop exposes powerful container functionality and is not intended to be publicly accessible. Do not expose port 3001 to the open Internet. The application HTTP interface alone is **not TLS encrypted**.

## Desktop development

Supported desktop code: Python 3.11+, GTK 4, PyGObject, `ffmpeg`, and the patched `invisible_playwright` Firefox engine. Linux developer example:

```bash
sudo apt-get install python3-gi python3-gi-cairo gir1.2-gtk-4.0 ffmpeg python3-venv
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e '.[recorder,desktop,mega]'
python -m invisible_playwright fetch
oso-desktop
```

This is a **development-only** invocation; end users are intended to launch a packaged application with no Python knowledge. The desktop application doesn't use web authentication. Its main window is maximized, and the close button hides it in the system tray where supported. Minimize does not hide the window. Right-click the tray icon to quit with confirmation. On unsupported system trays, hiding is intentionally prevented to avoid leaving users unable to reopen the window. See [Known limitations](#known-limitations).

Desktop storage:

```text
~/OsoStreamRecord/                      SQLite, passphrase, browser profiles, logs
~/Videos/OsoStreamRecord/Profile_1/      Video files (default)
```

**Important:** Desktop sign-in opens a *headed* patched Firefox instance on the host; it never uses the Docker VNC sign-in option.

## Desktop packaging: Docker-only workflows

The following recipes are included for release engineering and are **experimental**; they have not been executed in this environment. The Linux recipe builds an AppImage for x86_64 and attempts to bundle GTK 4's GI typelibs and patched Firefox. The Windows recipe is a Windows-container PyInstaller build whose complete GTK 4 and browser dependency deployment still requires validation.

### Linux AppImage (x86_64)

```bash
./build/build-desktop-linux.sh
# Expected output after successful Docker build:
# dist/OsoStreamRecord-x86_64.AppImage
chmod +x dist/OsoStreamRecord-x86_64.AppImage
./dist/OsoStreamRecord-x86_64.AppImage
```

Equivalent build commands:

```bash
docker build -f build/linux/Dockerfile -t oso-stream-record:desktop-linux .
docker run --rm --privileged -v "$(pwd)/dist:/out" oso-stream-record:desktop-linux
```

The `--privileged` option is included for environments whose AppImage tools require FUSE; prefer a restricted setup where possible. Check the generated AppImage on a clean distribution and confirm GTK4, GI typelibs, session-tray behavior, FFmpeg, and the patched browser are correctly bundled. The recipe depends on GitHub release assets at build time.

### Windows `.exe` (x86_64)

The Windows container build requires **Docker Desktop on Windows in Windows-container mode**, with compatibility for Windows Server Core LTSC 2022. It uses MSYS2 UCRT64 GTK 4/PyGObject and PyInstaller inside the Windows container. It **does not** cross-build on ordinary Linux Docker Engine.

In PowerShell on the Windows build host:

```powershell
.\build\build-desktop-windows.ps1
# Intended output: dist\OsoStreamRecord.exe plus GTK runtime dependencies
```

For clarity, **no Windows executable has been generated or verified for this version**. Review Windows-specific library paths, PyInstaller hooks, the patched Firefox executable cache, bundled FFmpeg and GTK/typelib resources before distributing the build. The Windows Dockerfile is an initial pipeline, not a tested redistributable installer.

## Tests

```bash
python -m pip install -e '.[web,test]'
pytest -q tests
node --check oso/web/static/app.js
```

The tested components do not require a live TikTok stream, browser binary, VNC server, an actual Mega account, a graphical display, or Docker. Real provider integration tests should run separately in an appropriate disposable environment.

## Configuration, data, and backups

### Configuration

Configuration is shared by both clients through a single `oso.sqlite` when they point to the same data directory, but only one process should control the scheduler at a time. Video storage must be outside the configuration directory. Default web mounts: `/data` and `/videos`. Desktop default data directory: `~/OsoStreamRecord`.

- Profiles live in `profiles` and channel records in `channels`; the platform field is immutable after channel creation.
- The initial channel recording checkbox is **off**; profile and channel enabled checkboxes are **on**.
- Video files may use `.mkv`; HTML5 playback uses FFmpeg to transcode to fragmented MP4 dynamically and can use substantial CPU.
- An interrupted recording may yield a partial file, which is retained if non-empty.
- Debug logs rotate up to 10 files in `data/logs`.
- Browser authentication profiles are separated by profile and stored under `data/browser/firefox/PROFILE_DIRECTORY`.

### Encryption caveat

The application stores cloud passwords encrypted using AES-GCM, PBKDF2 and the settings passphrase. The requested passphrase file is **obfuscated with a constant present in source code**. Obfuscation is not cryptographic protection against an attacker who can read the executable and data directory. Strong local-secret protection requires an OS credential vault, a manually entered master password, or a hardware-backed secret, which would change the specified unattended behavior.

Export creates a **standard AES-encrypted ZIP** using the settings passphrase. The passphrase file and video files are excluded. Import requires the correct password, validates paths and database integrity, and replaces configuration only after confirmation. Before importing, stop ongoing recordings. Because file replacement is not a single filesystem-atomic operation, keep a second copy of backups for disaster recovery.

## Add a new platform

`oso/core/recorder.py` holds a `PLATFORMS` mapping of platform names to checkers. Implement a checker with the signature `check(service, channel) -> (streamUrls, userAgent)` and register the platform in `SUPPORTED_PLATFORMS` in `oso/core/service.py`. `RecordingJob` handles FFmpeg independently of platform discovery.

## Known limitations

- Real TikTok stream endpoints, logins, rate limits and changes to upstream JavaScript/API behavior are external dependencies. The adapted implementation has **not** been tested against a live stream in this environment.
- `mega.py` is a third-party library and online uploads have not been validated against real accounts; verify provider API compatibility before enabling automatic deletion of local uploads.
- The `invisible_playwright` engine is downloaded separately at build time and requires access to its published binaries. See [upstream installation documentation](https://github.com/feder-cr/invisible_playwright/blob/main/docs/installation.md).
- The web's global VNC reservation is process-local; the single Firefox desktop service continues to run, and a person directly accessing its dedicated port is not blocked by the app's reservation UI.
- The desktop tray implementation uses `pystray` and depends on the availability of an X11/Windows-compatible tray. Wayland-only desktops may not support the requested close-to-tray functionality without additional platform integration.
- Automated tests cover local logic and HTTP UI behavior, **not** a graphical GTK 4 session or fully packaged Linux/Windows binaries.
- Python and dependencies are needed for source development; packaged end-user binaries cannot be claimed until the Docker desktop recipes succeed and the resulting builds pass acceptance tests.

## Credits

The supplied `tiktok-recorder`, `playwright-test`, and `docker-browser-cookie-generator` examples informed the browser profile, live-detection, Firefox cookie and recording adapters. The original camelCase function names in the adapted recorder files were preserved.

TikTok and Mega are trademarks of their respective owners. This software is not affiliated with either service; respect local laws and platform terms when recording streams.
