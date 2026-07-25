from __future__ import annotations

import asyncio
from array import array
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterator
import hashlib
import shutil
import sys
from typing import Any

from .audio import PcmFrame, _resample_linear


FRAME_SAMPLES = 480
FRAME_BYTES = FRAME_SAMPLES * 2


def pcm16_16k_to_frames(
    pcm_bytes: bytes,
    *,
    leading_silence_ms: int = 500,
    trailing_silence_ms: int = 1_000,
) -> Iterator[PcmFrame]:
    """Convert one complete 16 kHz mono PCM16 recording to StepFun frames."""

    if len(pcm_bytes) % 2:
        raise ValueError("PCM16 byte count must be even")
    if leading_silence_ms < 0 or trailing_silence_ms < 0:
        raise ValueError("silence padding cannot be negative")

    samples = array("h")
    samples.frombytes(pcm_bytes)
    if sys.byteorder != "little":
        samples.byteswap()
    resampled = _resample_linear(samples, 16_000)

    padded = array(
        "h", [0] * (24_000 * leading_silence_ms // 1_000)
    )
    padded.extend(resampled)
    padded.extend(
        [0] * (24_000 * trailing_silence_ms // 1_000)
    )
    if sys.byteorder != "little":
        padded.byteswap()
    output = padded.tobytes()

    for offset in range(0, len(output), FRAME_BYTES):
        chunk = output[offset : offset + FRAME_BYTES]
        if len(chunk) < FRAME_BYTES:
            chunk += bytes(FRAME_BYTES - len(chunk))
        yield PcmFrame(chunk)


class ZiloRecordedAudioSource:
    """Receives complete saved Zilo recordings; this is not a live stream."""

    def __init__(
        self,
        address: str,
        sdk: Any,
        *,
        ffmpeg_path: str = "ffmpeg",
        reconnect_delay_s: float = 5,
        receive_timeout_s: float = 60,
        leading_silence_ms: int = 500,
        trailing_silence_ms: int = 1_000,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        self.address = address.strip()
        if not self.address:
            raise ValueError("Zilo BLE address is required")
        if not hasattr(sdk, "RingSoundClient"):
            raise ValueError("Zilo SDK is missing RingSoundClient")
        if not hasattr(sdk, "receive_auto_audio_file"):
            raise ValueError(
                "Zilo SDK is missing receive_auto_audio_file"
            )
        if not hasattr(sdk, "decode_speex_to_pcm"):
            raise ValueError("Zilo SDK is missing decode_speex_to_pcm")
        resolved_ffmpeg = shutil.which(ffmpeg_path)
        if resolved_ffmpeg is None:
            raise ValueError(f"ffmpeg executable not found: {ffmpeg_path}")
        if reconnect_delay_s < 0:
            raise ValueError("reconnect delay cannot be negative")
        self.sdk = sdk
        self.ffmpeg_path = resolved_ffmpeg
        self.reconnect_delay_s = reconnect_delay_s
        self.receive_timeout_s = receive_timeout_s
        self.leading_silence_ms = leading_silence_ms
        self.trailing_silence_ms = trailing_silence_ms
        self._sleep = sleep
        self.client = sdk.RingSoundClient(address=self.address)
        self._seen_recordings: OrderedDict[str, None] = OrderedDict()
        self._dedupe_limit = 256

    def _recording_key(
        self, file_index: Any, raw_audio: bytes
    ) -> str:
        if file_index is not None:
            return f"index:{file_index}"
        return "sha256:" + hashlib.sha256(raw_audio).hexdigest()

    def _remember(self, key: str) -> None:
        self._seen_recordings[key] = None
        self._seen_recordings.move_to_end(key)
        while len(self._seen_recordings) > self._dedupe_limit:
            self._seen_recordings.popitem(last=False)

    def _decode(self, raw_audio: bytes) -> bytes:
        result = self.sdk.decode_speex_to_pcm(
            raw_audio,
            pcm_config={
                "sample_rate": 16_000,
                "channels": 1,
                "bit_depth": 16,
            },
            ffmpeg_path=self.ffmpeg_path,
        )
        config = result.pcm_config
        sample_rate = (
            config.get("sample_rate")
            if isinstance(config, dict)
            else getattr(config, "sample_rate", None)
        )
        channels = (
            config.get("channels")
            if isinstance(config, dict)
            else getattr(config, "channels", None)
        )
        bit_depth = (
            config.get("bit_depth")
            if isinstance(config, dict)
            else getattr(config, "bit_depth", None)
        )
        if (sample_rate, channels, bit_depth) != (16_000, 1, 16):
            raise ValueError(
                "Zilo decoder must return 16 kHz mono PCM16"
            )
        pcm_bytes = bytes(result.pcm_bytes)
        if len(pcm_bytes) % 2:
            raise ValueError("Zilo decoder returned invalid PCM16")
        return pcm_bytes

    async def _disconnect(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:
            pass

    async def frames(self) -> AsyncIterator[PcmFrame]:
        connected = False
        try:
            while True:
                try:
                    await self.client.connect()
                    connected = True
                    while True:
                        file_index, raw_audio = (
                            await self.sdk.receive_auto_audio_file(
                                self.client,
                                timeout_s=self.receive_timeout_s,
                            )
                        )
                        raw_audio = bytes(raw_audio)
                        key = self._recording_key(
                            file_index, raw_audio
                        )
                        if key in self._seen_recordings:
                            self._seen_recordings.move_to_end(key)
                            continue
                        try:
                            pcm_bytes = self._decode(raw_audio)
                        except Exception:
                            continue
                        self._remember(key)
                        for frame in pcm16_16k_to_frames(
                            pcm_bytes,
                            leading_silence_ms=(
                                self.leading_silence_ms
                            ),
                            trailing_silence_ms=(
                                self.trailing_silence_ms
                            ),
                        ):
                            yield frame
                            await self._sleep(0.02)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if connected:
                        await self._disconnect()
                        connected = False
                    await self._sleep(self.reconnect_delay_s)
        finally:
            if connected:
                await self._disconnect()


class ZiloDoublePressListener:
    """Maps the public key-double-press event to response cancellation."""

    def __init__(
        self,
        sdk: Any,
        client: Any,
        gateway_service: Any,
        *,
        retry_delay_s: float = 5,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        if not hasattr(sdk, "wait_sensor_key_double_press_event"):
            raise ValueError(
                "Zilo SDK is missing key double-press support"
            )
        self.sdk = sdk
        self.client = client
        self.gateway_service = gateway_service
        self.retry_delay_s = retry_delay_s
        self._sleep = sleep

    async def run_once(self) -> None:
        await self.sdk.wait_sensor_key_double_press_event(
            self.client, timeout_s=None
        )
        await self.gateway_service.cancel_current_response()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._sleep(self.retry_delay_s)
