#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist

docker build -f build/linux/Dockerfile -t oso-stream-record:desktop-linux .
docker run --rm --privileged -v "$(pwd)/dist:/out" oso-stream-record:desktop-linux
