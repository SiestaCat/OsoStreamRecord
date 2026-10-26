import json
from urllib.parse import urlsplit


ROOM_QUERY = """async username => {
    const params = new URLSearchParams({
        aid: "1988",
        sourceType: "54",
        staleTime: "600000",
        uniqueId: username.toLowerCase()
    });
    const response = await fetch(
        `/api-live/user/room?${params}`,
        {credentials: "include"}
    );
    if (!response.ok) return null;
    return await response.json();
}"""


def addStream(value, streams, path="", codec=""):
    if isinstance(value, dict):
        sdkParams = value.get("sdk_params")
        if isinstance(sdkParams, str):
            try:
                sdkParams = json.loads(sdkParams)
            except ValueError:
                sdkParams = {}

        if isinstance(sdkParams, dict):
            codec = str(sdkParams.get("VCodec") or sdkParams.get("v_codec") or codec).lower()
        codec = str(value.get("VCodec") or value.get("v_codec") or codec).lower()

        for key, item in value.items():
            addStream(item, streams, f"{path}/{key}", codec)
    elif isinstance(value, list):
        for item in value:
            addStream(item, streams, path, codec)
    elif isinstance(value, str):
        if value.startswith(("{", "[")):
            try:
                addStream(json.loads(value), streams, path, codec)
            except (ValueError, RecursionError):
                pass
        elif value.startswith("https://"):
            parsed = urlsplit(value)
            isFlv = ".flv" in parsed.path.lower() or "pull-flv" in parsed.netloc.lower()
            isHls = ".m3u8" in parsed.path.lower()

            if isFlv or isHls:
                score = 100 if "origin" in path.lower() else 0
                score += 10 if isFlv else 0
                if codec in ("h264", "avc", "264"):
                    score += 1000
                elif codec in ("h265", "hevc", "265") or "hevc" in path.lower():
                    score -= 1000
                streams[value] = max(streams.get(value, float("-inf")), score)


def getLiveStreams(page, username):
    liveUrl = f"https://www.tiktok.com/@{username}/live"
    page.goto(liveUrl, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)

    info = page.evaluate(ROOM_QUERY, username)
    if not isinstance(info, dict) or info.get("statusCode") != 0:
        raise ValueError("TikTok did not return a valid response for this username")

    data = info.get("data") or {}
    userInfo = data.get("user") or {}
    liveRoom = data.get("liveRoom") or {}

    apiUsername = userInfo.get("uniqueId")
    if apiUsername and apiUsername.lower() != username.lower():
        raise ValueError(f"Response username is @{apiUsername}, not @{username}")

    roomId = str(userInfo.get("roomId") or "")
    liveRoomId = str(liveRoom.get("roomId") or "")
    if roomId and liveRoomId and roomId != liveRoomId:
        raise ValueError(f"User live room ({roomId}) does not match stream room ({liveRoomId})")

    if str(liveRoom.get("status")) != "2":
        print(f"@{username} is not currently live (status: {liveRoom.get('status')}).", flush=True)
        return []

    # Use stream URLs only from the requested user room.
    # No recoger streams de peticiones, recomendaciones ni otros LIVE.
    streams = {}
    addStream(liveRoom.get("streamData"), streams)
    addStream(liveRoom.get("hevcStreamData"), streams)
    print(f"@{username} | Verified live room: {roomId or liveRoomId or 'no ID'} | streamId: {liveRoom.get('streamId', 'unavailable')}", flush=True)
    return sorted(streams, key=streams.get, reverse=True)
