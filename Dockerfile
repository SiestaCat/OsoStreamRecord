FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INVISIBLE_PLAYWRIGHT_CACHE_DIR=/opt/invisible-playwright-cache

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY oso ./oso
RUN python -m pip install --no-cache-dir '.[web,recorder,mega]' \
    && python -m invisible_playwright fetch
RUN mkdir -p /data /videos /browser-login && chmod -R 0775 /data /videos /browser-login

EXPOSE 8080
CMD ["oso-web"]
