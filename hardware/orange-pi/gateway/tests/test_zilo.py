from __future__ import annotations

import asyncio
from array import array
from collections import deque
from types import SimpleNamespace
import sys

import pytest

from oc_gateway.zilo import (
    ZiloDoublePressListener,
    ZiloRecordedAudioSource,
    pcm16_16k_to_frames,
)


def one_ring_frame():
    return array("h", range(320)).tobytes()


def test_resamples_16k_pcm16_to_24k_twenty_ms_frames():
    source = array("h", range(160)).tobytes()
    frames = list(
        pcm16_16k_to_frames(
            source,
            leading_silence_ms=0,
            trailing_silence_ms=0,
        )
    )
    assert len(frames) == 1
    assert len(frames[0].data) == 960
    assert frames[0].sample_rate == 24_000


def test_default_padding_adds_75_twenty_ms_frames():
    frames = list(pcm16_16k_to_frames(b""))
    assert len(frames) == 75
    assert all(frame.data == bytes(960) for frame in frames)


def test_rejects_odd_pcm16_byte_count():
    with pytest.raises(ValueError, match="PCM16"):
        list(pcm16_16k_to_frames(b"\x00"))


class FakeClient:
    def __init__(self, events):
        self.events = events
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self):
        self.connect_calls += 1

    async def disconnect(self):
        self.disconnect_calls += 1


class FakeSdk:
    def __init__(self, events, decode=None):
        self.events = deque(events)
        self.client = FakeClient(self.events)
        self.decode = decode or (lambda raw: one_ring_frame())
        self.decode_calls = []
        self.double_press_calls = 0

    def RingSoundClient(self, *, address):
        self.address = address
        return self.client

    async def receive_auto_audio_file(self, client, *, timeout_s=None):
        assert client is self.client
        event = self.events.popleft()
        if isinstance(event, Exception):
            raise event
        return event

    def decode_speex_to_pcm(self, raw, **kwargs):
        self.decode_calls.append(raw)
        return SimpleNamespace(
            pcm_bytes=self.decode(raw),
            pcm_config=SimpleNamespace(
                sample_rate=16_000,
                channels=1,
                bit_depth=16,
            ),
        )

    async def wait_sensor_key_double_press_event(
        self, client, *, timeout_s=None
    ):
        assert client is self.client
        self.double_press_calls += 1
        return SimpleNamespace(timestamp_ms=123)


async def next_frame(source):
    generator = source.frames()
    try:
        return await anext(generator)
    finally:
        await generator.aclose()


@pytest.mark.asyncio
async def test_complete_recordings_are_deduplicated_by_index():
    sdk = FakeSdk(
        [
            (7, b"first"),
            (7, b"duplicate"),
            (8, b"second"),
        ]
    )
    source = ZiloRecordedAudioSource(
        "AA:BB:CC:DD:EE:FF",
        sdk,
        ffmpeg_path=sys.executable,
        leading_silence_ms=0,
        trailing_silence_ms=0,
        sleep=lambda _delay: asyncio.sleep(0),
    )
    generator = source.frames()
    try:
        first = await anext(generator)
        second = await anext(generator)
    finally:
        await generator.aclose()

    assert len(first.data) == 960
    assert len(second.data) == 960
    assert sdk.decode_calls == [b"first", b"second"]
    assert sdk.client.connect_calls == 1


@pytest.mark.asyncio
async def test_disconnect_reconnects_after_fixed_delay():
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    sdk = FakeSdk([ConnectionError("BLE offline"), (9, b"next")])
    source = ZiloRecordedAudioSource(
        "AA:BB:CC:DD:EE:FF",
        sdk,
        ffmpeg_path=sys.executable,
        reconnect_delay_s=5,
        leading_silence_ms=0,
        trailing_silence_ms=0,
        sleep=fake_sleep,
    )
    frame = await next_frame(source)

    assert len(frame.data) == 960
    assert sdk.client.connect_calls == 2
    assert 5 in sleeps


@pytest.mark.asyncio
async def test_decode_failure_drops_only_the_current_recording():
    def decode(raw):
        if raw == b"bad":
            raise ValueError("corrupt Speex")
        return one_ring_frame()

    sdk = FakeSdk([(1, b"bad"), (2, b"good")], decode=decode)
    source = ZiloRecordedAudioSource(
        "AA:BB:CC:DD:EE:FF",
        sdk,
        ffmpeg_path=sys.executable,
        leading_silence_ms=0,
        trailing_silence_ms=0,
        sleep=lambda _delay: asyncio.sleep(0),
    )
    frame = await next_frame(source)

    assert len(frame.data) == 960
    assert sdk.decode_calls == [b"bad", b"good"]
    assert sdk.client.connect_calls == 1


def test_dedupe_cache_is_bounded():
    sdk = FakeSdk([])
    source = ZiloRecordedAudioSource(
        "AA:BB:CC:DD:EE:FF",
        sdk,
        ffmpeg_path=sys.executable,
    )
    for index in range(257):
        source._remember(f"index:{index}")
    assert len(source._seen_recordings) == 256
    assert "index:0" not in source._seen_recordings


class FakeGatewayService:
    def __init__(self):
        self.cancel_calls = 0

    async def cancel_current_response(self):
        self.cancel_calls += 1


@pytest.mark.asyncio
async def test_double_press_uses_public_gateway_cancel_entry():
    sdk = FakeSdk([])
    service = FakeGatewayService()
    listener = ZiloDoublePressListener(sdk, sdk.client, service)
    await listener.run_once()
    assert service.cancel_calls == 1
    assert sdk.double_press_calls == 1
