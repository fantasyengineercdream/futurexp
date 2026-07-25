from __future__ import annotations

from dataclasses import dataclass

import pytest

from oc_gateway.audio import PcmFrame
from oc_gateway.service import GatewayService
from oc_gateway.voice import VoiceEvent


class FakeVoice:
    def __init__(self):
        self.cancel_calls = 0
        self.request_response_calls = 0
        self.inner_os_acks = []

    async def cancel(self):
        self.cancel_calls += 1

    async def request_response(self):
        self.request_response_calls += 1

    async def send_inner_os_ack(self, event_id, status):
        self.inner_os_acks.append((event_id, status))


class FakeSink:
    def __init__(self):
        self.clear_calls = 0
        self.played = []
        self.states = []
        self.transcripts = []

    async def clear(self):
        self.clear_calls += 1

    async def play(self, frame):
        self.played.append(frame)

    async def state(self, phase):
        self.states.append(phase)

    async def transcript(self, role, text):
        self.transcripts.append((role, text))


class FakeDisplays:
    def __init__(self):
        self.sent = []

    async def submit(self, task):
        self.sent.append(task)
        return True


@dataclass
class Fakes:
    voice: FakeVoice
    sink: FakeSink
    displays: FakeDisplays


@pytest.fixture
def fakes():
    return Fakes(FakeVoice(), FakeSink(), FakeDisplays())


@pytest.mark.asyncio
async def test_speech_started_clears_audio_cancels_response_and_shows_listening(
    fakes,
):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
        character_id="devil",
    )
    await service.handle_voice_event(VoiceEvent("speech_started"))
    assert fakes.sink.clear_calls == 1
    assert fakes.voice.cancel_calls == 1
    assert fakes.displays.sent[-1].scene == {
        "animation": {
            "asset_id": "devil_listening",
            "asset_version": 1,
            "loop": 1,
        }
    }


@pytest.mark.asyncio
async def test_public_cancel_clears_sinks_and_cancels_voice(fakes):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
        character_id="devil",
    )
    await service.cancel_current_response()
    assert fakes.sink.clear_calls == 1
    assert fakes.voice.cancel_calls == 1


@pytest.mark.asyncio
async def test_public_final_transcript_stays_public_and_never_becomes_eink_text(
    fakes,
):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
        character_id="angel",
    )
    await service.handle_voice_event(
        VoiceEvent("assistant_transcript", text="主人，我才没有等你。")
    )
    assert fakes.sink.transcripts == [
        ("assistant", "主人，我才没有等你。")
    ]
    assert fakes.displays.sent == []


@pytest.mark.asyncio
async def test_private_inner_os_becomes_atomic_text_animation_scene(fakes):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
        character_id="angel",
    )
    await service.handle_voice_event(
        VoiceEvent(
            "inner_os",
            text="别误会，我只是顺手。",
            raw={"event_id": "inner_001"},
        )
    )
    scene = fakes.displays.sent[-1].scene
    assert set(scene) == {"text", "animation"}
    assert scene["text"]["content"] == "别误会，我只是顺手。"
    assert scene["animation"]["asset_id"] == "angel_thinking"
    assert fakes.voice.inner_os_acks == [("inner_001", "accepted")]


@pytest.mark.asyncio
async def test_private_inner_os_is_capped_to_24_characters_for_eink(fakes):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
    )
    await service.handle_voice_event(
        VoiceEvent(
            "inner_os",
            text="好" * 30,
            raw={"event_id": "inner_002"},
        )
    )
    assert fakes.displays.sent[-1].scene["text"]["content"] == "好" * 23 + "…"


@pytest.mark.asyncio
async def test_audio_fans_out_the_same_immutable_frame(fakes):
    second = FakeSink()
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink, second],
        displays=fakes.displays,
    )
    frame = PcmFrame(b"\x00\x00")
    await service.handle_voice_event(VoiceEvent("audio", audio=frame))
    assert fakes.sink.played == [frame]
    assert second.played == [frame]


@pytest.mark.asyncio
async def test_retries_one_silent_response_then_returns_idle(fakes):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
    )
    await service.handle_voice_event(VoiceEvent("speech_stopped"))
    await service.handle_voice_event(VoiceEvent("response_done"))
    await service.handle_voice_event(VoiceEvent("response_done"))
    assert fakes.voice.request_response_calls == 1
    assert fakes.displays.sent[-1].scene["animation"]["asset_id"] == "devil_idle"


@pytest.mark.asyncio
async def test_forwards_voice_state_and_final_transcripts_to_room_view(fakes):
    service = GatewayService(
        voice=fakes.voice,
        audio_source=None,
        audio_sinks=[fakes.sink],
        displays=fakes.displays,
    )
    await service.handle_voice_event(VoiceEvent("connected"))
    await service.handle_voice_event(VoiceEvent("speech_started"))
    await service.handle_voice_event(VoiceEvent("speech_stopped"))
    await service.handle_voice_event(
        VoiceEvent("user_transcript", text="你好")
    )
    await service.handle_voice_event(
        VoiceEvent("assistant_transcript", text="欢迎回来")
    )
    await service.handle_voice_event(
        VoiceEvent("audio", audio=PcmFrame(b"\x00\x00"))
    )
    await service.handle_voice_event(VoiceEvent("response_done"))

    assert fakes.sink.states == [
        "idle",
        "listening",
        "thinking",
        "speaking",
        "idle",
    ]
    assert fakes.sink.transcripts == [
        ("user", "你好"),
        ("assistant", "欢迎回来"),
    ]
