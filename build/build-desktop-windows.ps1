# Requires Docker Desktop on Windows with Windows containers enabled.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path dist | Out-Null
docker build -f build/windows/Dockerfile -t oso-stream-record:desktop-windows .
docker run --rm --mount "type=bind,source=$((Get-Location).Path)\dist,target=C:\artifacts" oso-stream-record:desktop-windows
