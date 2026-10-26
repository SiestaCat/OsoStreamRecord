import json
import logging
from urllib.parse import urlsplit


logger = logging.getLogger("oso.tiktok")


class LiveStreamUnavailable(RuntimeError):
    """TikTok confirms the room is LIVE but supplies no usable stream URLs."""
    pass


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


# Ask the same user-scoped endpoint for a fresh result only when the first
# response confirms a LIVE but contains no playable URL.
ROOM_QUERY_REFRESH = ROOM_QUERY.replace('staleTime: "600000"', 'staleTime: "0"').replace(
    '{credentials: "include"}', '{credentials: "include", cache: "no-store"}'
)


def describeStreamData(value):
    """Describe a TikTok API field without logging URLs or auth tokens."""
    if isinstance(value, dict):
        return "object(keys=" + ",".join(sorted(str(key) for key in value)[:12]) + ")"
    if isinstance(value, list):
        return f"array(length={len(value)})"
    if isinstance(value, str):
        return "string" if value else "empty string"
    return type(value).__name__


def verifiedRoom(info, username):
    """Never use a response for a different TikTok username or live room."""
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
    return liveRoom, roomId or liveRoomId


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


def getRoomInfoStreams(page, username, roomId):
    """Try TikTok's room-specific Webcast API when user/room lacks playback fields.

    Only return media URLs from the verified room's stream_url payload.
    """
    if not roomId or not str(roomId).isdigit():
        logger.warning("@%s: cannot query Webcast room info without a numeric room ID", username)
        return []

    try:
        response = page.context.request.get(
            "https://webcast.tiktok.com/webcast/room/info/",
            params={"aid": "1988", "room_id": str(roomId)},
            headers={"Referer": f"https://www.tiktok.com/@{username}/live", "Accept": "application/json"},
            timeout=15000
        )
        if not response.ok:
            logger.warning("@%s: Webcast room info returned HTTP %s", username, response.status)
            return []
        payload = response.json()
        if not isinstance(payload, dict):
            logger.warning("@%s: Webcast room info is not a JSON object", username)
            return []
        code = payload.get("status_code")
        if code is not None and str(code) != "0":
            logger.warning("@%s: Webcast room info returned status_code=%s", username, code)
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            logger.warning("@%s: Webcast room info has no data object", username)
            return []

        responseRoomId = data.get("id") or data.get("room_id") or data.get("roomId")
        if responseRoomId is not None and str(responseRoomId) != str(roomId):
            logger.warning("@%s: Webcast room ID differs from verified room; ignoring response", username)
            return []
        owner = data.get("owner") or {}
        if isinstance(owner, dict):
            ownerName = owner.get("unique_id") or owner.get("uniqueId")
            if ownerName and ownerName.lower().lstrip("@") != username.lower().lstrip("@"):
                logger.warning("@%s: Webcast room owner differs from requested user; ignoring response", username)
                return []
        if data.get("status") is not None and str(data["status"]) != "2":
            logger.warning("@%s: Webcast room info status=%s is not LIVE", username, data["status"])
            return []

        streamInfo = data.get("stream_url") or data.get("streamUrl") or {}
        streams = {}
        addStream(streamInfo, streams)
        logger.info("@%s: Webcast room info returned %d playable URLs (streamInfo=%s)",
                    username, len(streams), describeStreamData(streamInfo))
        return sorted(streams, key=streams.get, reverse=True)
    except Exception as error:
        # Do not log exception details: request errors can include signed URLs.
        logger.warning("@%s: Webcast room info request failed (%s)", username, type(error).__name__)
        return []


def getLiveStreams(page, username):
    liveUrl = f"https://www.tiktok.com/@{username}/live"
    page.goto(liveUrl, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)

    info = page.evaluate(ROOM_QUERY, username)
    liveRoom, roomId = verifiedRoom(info, username)
    if str(liveRoom.get("status")) != "2":
        print(f"@{username} is not currently live (status: {liveRoom.get('status')}).", flush=True)
        return []

    def collectStreams(room):
        # Only collect URLs from the verified requested user's live room.
        streams = {}
        addStream(room.get("streamData"), streams)
        addStream(room.get("hevcStreamData"), streams)
        return streams

    streams = collectStreams(liveRoom)
    print(f"@{username} | Verified live room: {roomId or 'no ID'} | streamId: {liveRoom.get('streamId', 'unavailable')}", flush=True)
    if streams:
        return sorted(streams, key=streams.get, reverse=True)

    logger.warning(
        "@%s is LIVE but the first API response has no playable URLs: "
        "streamData=%s hevcStreamData=%s roomKeys=%s",
        username, describeStreamData(liveRoom.get("streamData")),
        describeStreamData(liveRoom.get("hevcStreamData")),
        sorted(liveRoom.keys())
    )

    # TikTok sometimes serves a partial or cached room description. Retry
    # once using its own same-origin endpoint and the same logged-in context.
    try:
        freshInfo = page.evaluate(ROOM_QUERY_REFRESH, username)
        freshRoom, freshRoomId = verifiedRoom(freshInfo, username)
        if freshRoomId and roomId and freshRoomId != roomId:
            logger.warning("@%s: refreshed response refers to a different room; ignoring it", username)
        elif str(freshRoom.get("status")) == "2":
            streams = collectStreams(freshRoom)
            if streams:
                logger.info("@%s: recovered %s stream URLs on refreshed room query", username, len(streams))
                return sorted(streams, key=streams.get, reverse=True)
            logger.warning(
                "@%s LIVE response after refresh still has no playable URLs: "
                "streamData=%s hevcStreamData=%s roomKeys=%s",
                username, describeStreamData(freshRoom.get("streamData")),
                describeStreamData(freshRoom.get("hevcStreamData")),
                sorted(freshRoom.keys())
            )
        else:
            logger.warning("@%s: refreshed room status is %s", username, freshRoom.get("status"))
    except Exception as error:
        logger.warning("@%s: fresh TikTok room query failed: %s", username, type(error).__name__)

    # The user/room endpoint may return only room metadata. The room-specific
    # Webcast endpoint can still provide stream_url for the same verified room.
    streams = getRoomInfoStreams(page, username, roomId)
    if streams:
        logger.info("@%s: recovered %s stream URLs from Webcast room info", username, len(streams))
        return streams

    raise LiveStreamUnavailable(
        f"TikTok confirms @{username} is LIVE (room {roomId or 'unknown'}), "
        "but no playable URL was found in the room or Webcast responses. "
        "Check the oso.tiktok diagnostics in the web logs."
    )
