from __future__ import annotations

import asyncio
from array import array
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import wave


@dataclass(frozen=True)
class PcmFrame:
    """One little-endian PCM16 mono frame accepted by StepFun Realtime."""

    data: bytes
    sample_rate: int = 24_000
    channels: int = 1
    sample_width: int = 2

    def __post_init__(self) -> None:
        if self.sample_rate != 24_000:
            raise ValueError("PCM sample rate must be 24000 Hz")
        if self.channels != 1:
            raise ValueError("PCM must be mono")
        if self.sample_width != 2:
            raise ValueError("PCM must be 16-bit")
        if len(self.data) % 2:
            raise ValueError("PCM16 byte count must be even")


class RingAudioSource(Protocol):
    def frames(self) -> AsyncIterator[PcmFrame]: ...


class AudioSink(Protocol):
    async def play(self, frame: PcmFrame) -> None: ...

    async def clear(self) -> None: ...

    async def state(self, phase: str) -> None: ...

    async def transcript(self, role: str, text: str) -> None: ...


def _resample_linear(samples: array, source_rate: int) -> array:
    if source_rate == 24_000 or not samples:
        return array("h", samples)
    target_count = round(len(samples) * 24_000 / source_rate)
    output = array("h")
    for target_index in range(target_count):
        source_position = target_index * source_rate / 24_000
        lower = min(int(source_position), len(samples) - 1)
        upper = min(lower + 1, len(samples) - 1)
        fraction = source_position - lower
        value = round(samples[lower] * (1 - fraction) + samples[upper] * fraction)
        output.append(max(-32768, min(32767, value)))
    return output


class WavRingAudioSource:
    """Repeatable ring substitute: WAV speech with fixed leading/trailing silence."""

    FRAME_SAMPLES = 480

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _pcm(self) -> bytes:
        with wave.open(str(self.path), "rb") as source:
            if source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise ValueError("WAV mock must be mono PCM16")
            rate = source.getframerate()
            samples = array("h")
            samples.frombytes(source.readframes(source.getnframes()))
        resampled = _resample_linear(samples, rate)
        leading = array("h", [0]) * (24_000 // 2)
        trailing = array("h", [0]) * 24_000
        leading.extend(resampled)
        leading.extend(trailing)
        return leading.tobytes()

    async def frames(self) -> AsyncIterator[PcmFrame]:
        pcm = self._pcm()
        frame_bytes = self.FRAME_SAMPLES * 2
        for offset in range(0, len(pcm), frame_bytes):
            chunk = pcm[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += bytes(frame_bytes - len(chunk))
            yield PcmFrame(chunk)
            await asyncio.sleep(0)
