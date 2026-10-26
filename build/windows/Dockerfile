# EXPERIMENTAL: Requires a Windows Docker host running Windows container mode.
# Third-party Windows GI/FFmpeg/invisible-playwright bundling has not been E2E verified.
FROM mcr.microsoft.com/windows/servercore:ltsc2022
SHELL ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';"]
ENV MSYSTEM=UCRT64
ENV CHERE_INVOKING=1
ARG MSYS2_INSTALLER=https://repo.msys2.org/distrib/x86_64/msys2-base-x86_64-20250622.sfx.exe
RUN Invoke-WebRequest -Uri $env:MSYS2_INSTALLER -OutFile C:\msys2.exe; \
    Start-Process C:\msys2.exe -ArgumentList '-y','-oC:\' -NoNewWindow -Wait; \
    Remove-Item C:\msys2.exe
COPY . C:/src
RUN & C:\msys64\usr\bin\bash.exe -lc 'pacman --noconfirm -Syuu || true'
RUN & C:\msys64\usr\bin\bash.exe -lc 'pacman --noconfirm -Syuu || true'
RUN & C:\msys64\usr\bin\bash.exe -lc 'pacman --noconfirm -S --needed mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-pip mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-python-pillow mingw-w64-ucrt-x86_64-python-cryptography mingw-w64-ucrt-x86_64-gtk4 mingw-w64-ucrt-x86_64-pyinstaller'
RUN & C:\msys64\usr\bin\bash.exe -lc 'export PATH=/ucrt64/bin:$PATH; cd /c/src; python -m pip install --break-system-packages .[recorder,desktop,mega]; python -m invisible_playwright fetch'
RUN & C:\msys64\usr\bin\bash.exe -lc 'export PATH=/ucrt64/bin:$PATH; cd /c/src; pyinstaller --noconfirm --onedir --name OsoStreamRecord --collect-all gi --hidden-import gi.repository.Gtk --hidden-import gi.repository.Gdk --add-data "oso/locales;oso/locales" build/desktop_entry.py'
RUN New-Item -ItemType Directory C:\out\lib -Force | Out-Null; \
    Copy-Item C:\src\dist\OsoStreamRecord\* C:\out\ -Recurse -Force; \
    Copy-Item C:\msys64\ucrt64\bin\*.dll C:\out\ -Force; \
    Copy-Item C:\msys64\ucrt64\lib\girepository-1.0 C:\out\lib\girepository-1.0 -Recurse -Force
CMD ["powershell", "-NoProfile", "-Command", "Copy-Item C:\\out\\* C:\\artifacts\\ -Recurse -Force"]
