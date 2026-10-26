import asyncio

from oso.core.recorder import RecorderManager


def test_channel_check_does_not_record(service):
    channelId = service.createChannel(1, "tiktok", "foobar")
    probes = []
    def checker(instance, channel):
        probes.append(channel["username"])
        return ["https://live.example/stream.m3u8"], "Testing"
    manager = RecorderManager(service, checker=checker)
    async def run():
        await manager.checkStatus(channelId)
        while manager.probes:
            await asyncio.sleep(.02)
        status = manager.state(channelId)
        assert status["live"] is True
        assert status["recording"] is False
        assert status["status"] == "live"
        await manager.shutdown()
    asyncio.run(run())
    assert probes == ["foobar"]


def test_disabled_channel_rejected(service):
    channelId = service.createChannel(1, "tiktok", "foobar")
    service.updateChannel(channelId, enabled=False)
    manager = RecorderManager(service, checker=lambda *args: ([],""))
    async def run():
        try:
            await manager.beginManual(channelId)
            assert False, "Expected ValueError"
        except ValueError:
            pass
    asyncio.run(run())
