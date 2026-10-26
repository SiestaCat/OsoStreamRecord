FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    INVISIBLE_PLAYWRIGHT_CACHE_DIR=/opt/invisible-playwright-cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
    libgtk-4-1 libgirepository-2.0-0 libnss3 libasound2t64 \
    python3-venv python3-dev ffmpeg curl file libfuse2t64 \
    librsvg2-dev libgtk-4-dev libgirepository1.0-dev patchelf binutils \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY . /src
WORKDIR /src
RUN pip install --no-cache-dir '.[recorder,desktop,mega]' pyinstaller \
    && pip uninstall -y pathlib \
    && python -m invisible_playwright fetch
ENTRYPOINT ["/bin/bash", "/src/build/linux/build.sh"]
