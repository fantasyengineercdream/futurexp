from __future__ import annotations

from array import array
import wave

import pytest

from oc_gateway.audio import PcmFrame, WavRingAudioSource
from oc_gateway.voice import (
    CloudVoiceProvider,
    normalize_realtime_event,
    reconnect_delays,
)


class FakeSocket:
    closed = False

    def __init__(self):
        self.sent = []

    async def send_json(self, value):
        self.sent.append(value)


class FakeSession:
    def __init__(self):
        self.socket = FakeSocket()

    async def ws_connect(self, *_args, **_kwargs):
        return self.socket


@pytest.mark.parametrize(
    ("raw_type", "kind"),
    [
        ("session.updated", "connected"),
        ("input_audio_buffer.speech_started", "speech_started"),
        ("input_audio_buffer.speech_stopped", "speech_stopped"),
        ("response.audio.delta", "audio"),
        ("response.audio_transcript.done", "assistant_transcript"),
        ("oc.inner_os", "inner_os"),
        (
            "conversation.item.input_audio_transcription.completed",
            "user_transcript",
        ),
        ("response.done", "response_done"),
        ("error", "error"),
    ],
)
def test_normalizes_supported_realtime_events(raw_type, kind):
    event = normalize_realtime_event(
        {"type": raw_type, "delta": "AAA=", "transcript": "你好"}
    )
    assert event.kind == kind


def test_decodes_audio_delta_as_pcm16():
    event = normalize_realtime_event(
        {"type": "response.audio.delta", "delta": "AAECAw=="}
    )
    assert event.audio == PcmFrame(b"\x00\x01\x02\x03")


def test_reads_private_inner_os_text_without_exposing_it_as_a_transcript():
    event = normalize_realtime_event(
        {
            "type": "oc.inner_os",
            "event_id": "inner_001",
            "character": "devil",
            "text": "才不是因为担心你。",
        }
    )
    assert event.kind == "inner_os"
    assert event.text == "才不是因为担心你。"
    assert event.raw["event_id"] == "inner_001"


def test_reconnect_backoff_is_capped_at_ten_seconds():
    delays = reconnect_delays()
    assert [next(delays) for _ in range(7)] == [1, 2, 4, 8, 10, 10, 10]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate": 16_000},
        {"channels": 2},
        {"sample_width": 1},
        {"data": b"\x00"},
    ],
)
def test_pcm_frame_rejects_non_realtime_audio(kwargs):
    defaults = {
        "data": b"\x00\x00",
        "sample_rate": 24_000,
        "channels": 1,
        "sample_width": 2,
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        PcmFrame(**defaults)


def test_cloud_provider_uses_device_route_and_dedicated_token():
    provider = CloudVoiceProvider(
        base_url="https://oc-voice-lab.pages.dev/",
        device_token="device-secret\n",
        character_id="devil",
        session=object(),
        device_id="orangepi-3b-01",
    )
    assert provider.websocket_url == (
        "wss://oc-voice-lab.pages.dev/api/device/realtime"
        "?character=devil&deviceId=orangepi-3b-01"
    )
    assert provider.request_headers == {
        "Authorization": "Bearer device-secret"
    }


@pytest.mark.asyncio
async def test_cloud_provider_announces_inner_os_capability_after_connect():
    session = FakeSession()
    provider = CloudVoiceProvider(
        base_url="https://oc-voice-lab.pages.dev",
        device_token="device-secret",
        character_id="devil",
        session=session,
    )
    await provider._open_socket()
    assert session.socket.sent == [
        {
            "type": "oc.capabilities",
            "capabilities": ["inner_os.v1"],
        }
    ]


@pytest.mark.asyncio
async def test_cloud_provider_acknowledges_private_os_display_acceptance():
    session = FakeSession()
    provider = CloudVoiceProvider(
        base_url="https://oc-voice-lab.pages.dev",
        device_token="device-secret",
        character_id="devil",
        session=session,
    )
    provider._socket = session.socket
    await provider.send_inner_os_ack("inner_001", "accepted")
    assert session.socket.sent == [
        {
            "type": "oc.inner_os.ack",
            "event_id": "inner_001",
            "status": "accepted",
        }
    ]


def test_cloud_provider_rejects_an_unknown_character():
    with pytest.raises(ValueError, match="unknown character"):
        CloudVoiceProvider(
            base_url="https://example.com",
            device_token="token",
            character_id="other",
            session=object(),
        )


def test_cloud_provider_rejects_an_invalid_device_id():
    with pytest.raises(ValueError, match="device id"):
        CloudVoiceProvider(
            base_url="https://example.com",
            device_token="token",
            character_id="devil",
            session=object(),
            device_id="../bad",
        )


@pytest.mark.asyncio
async def test_wav_mock_resamples_and_adds_deterministic_silence(tmp_path):
    path = tmp_path / "ring.wav"
    samples = array("h", [1000] * 1_600)  # 100 ms at 16 kHz
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())

    frames = [frame async for frame in WavRingAudioSource(path).frames()]
    assert len(frames) == 80  # 500 ms + 100 ms + 1,000 ms
    assert all(len(frame.data) == 960 for frame in frames)
    assert all(frame.sample_rate == 24_000 for frame in frames)
    assert frames[0].data == bytes(960)
    assert frames[-1].data == bytes(960)
