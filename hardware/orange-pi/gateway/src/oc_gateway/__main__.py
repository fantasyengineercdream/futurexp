from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from aiohttp import ClientSession, web

from .api import PC_SINK_KEY, create_app
from .audio import WavRingAudioSource
from .display import DisplayTaskOrchestrator
from .hardware_api import AssetStore, HardwareServerDisplayTransport
from .service import GatewayService
from .transports import MockDisplayTransport
from .voice import CloudVoiceProvider, DirectStepFunProvider
from .zilo import ZiloDoublePressListener, ZiloRecordedAudioSource


@dataclass(frozen=True)
class Settings:
    voice_provider: str
    cloud_base_url: str
    device_token: str | None
    device_id: str
    character: str
    host: str
    port: int
    display_transport: str
    wav_input: Path | None
    hardware_server_url: str | None
    hardware_server_token: str | None
    hardware_agent_id: str | None
    hardware_targets: tuple[str, ...]
    hardware_screen_tokens: dict[str, str]
    hardware_asset_dir: Path | None
    ring_source: str
    zilo_address: str | None
    zilo_sdk_path: Path | None
    ffmpeg_path: str


def _optional_env(name: str) -> str | None:
    return os.getenv(name, "").strip() or None


def _hardware_targets() -> tuple[str, ...]:
    raw = os.getenv("OC_HARDWARE_TARGETS", "[]")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OC_HARDWARE_TARGETS must be a JSON list"
        ) from exc
    if not isinstance(value, list):
        raise ValueError("OC_HARDWARE_TARGETS must be a JSON list")
    targets = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )
    if not targets:
        raise ValueError(
            "OC_HARDWARE_TARGETS must contain at least one target"
        )
    return targets


def _hardware_screen_tokens(
    targets: tuple[str, ...],
) -> dict[str, str]:
    raw = os.getenv("OC_HARDWARE_SCREEN_TOKENS", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OC_HARDWARE_SCREEN_TOKENS must be a JSON object"
        ) from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(token, str)
        for key, token in value.items()
    ):
        raise ValueError(
            "OC_HARDWARE_SCREEN_TOKENS must map strings to strings"
        )
    unknown = set(value) - set(targets)
    if unknown:
        raise ValueError(
            "OC_HARDWARE_SCREEN_TOKENS contains unrouted targets: "
            + ", ".join(sorted(unknown))
        )
    return dict(value)


def load_settings() -> Settings:
    provider = os.getenv("OC_VOICE_PROVIDER", "cloud").strip().lower()
    if provider not in {"cloud", "direct"}:
        raise ValueError("OC_VOICE_PROVIDER must be cloud or direct")
    device_token = os.getenv("OC_DEVICE_TOKEN", "").strip() or None
    if provider == "cloud" and device_token is None:
        raise ValueError("OC_DEVICE_TOKEN is required in cloud mode")
    character = os.getenv("OC_CHARACTER", "devil").strip().lower()
    if character not in {"devil", "angel"}:
        raise ValueError("OC_CHARACTER must be devil or angel")
    device_id = os.getenv(
        "OC_DEVICE_ID", "orangepi-3b-01"
    ).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", device_id):
        raise ValueError("OC_DEVICE_ID is invalid")
    port = int(os.getenv("OC_BIND_PORT", "8787"))
    if not 1 <= port <= 65_535:
        raise ValueError("OC_BIND_PORT must be between 1 and 65535")
    display_transport = (
        os.getenv("OC_DISPLAY_TRANSPORT", "mock").strip().lower()
    )
    if display_transport not in {"mock", "advx"}:
        raise ValueError("OC_DISPLAY_TRANSPORT must be mock or advx")

    hardware_server_url = None
    hardware_server_token = None
    hardware_agent_id = None
    hardware_targets: tuple[str, ...] = ()
    hardware_screen_tokens: dict[str, str] = {}
    hardware_asset_dir = None
    if display_transport == "advx":
        hardware_server_url = _optional_env(
            "OC_HARDWARE_SERVER_URL"
        )
        hardware_server_token = _optional_env(
            "OC_HARDWARE_SERVER_TOKEN"
        )
        hardware_agent_id = _optional_env("OC_HARDWARE_AGENT_ID")
        if hardware_server_url is None:
            raise ValueError("OC_HARDWARE_SERVER_URL is required")
        if hardware_server_token is None:
            raise ValueError("OC_HARDWARE_SERVER_TOKEN is required")
        if hardware_agent_id is None:
            raise ValueError("OC_HARDWARE_AGENT_ID is required")
        hardware_targets = _hardware_targets()
        hardware_screen_tokens = _hardware_screen_tokens(
            hardware_targets
        )
        asset_value = _optional_env("OC_HARDWARE_ASSET_DIR")
        if asset_value is None:
            raise ValueError("OC_HARDWARE_ASSET_DIR is required")
        hardware_asset_dir = Path(asset_value)
        if not hardware_asset_dir.is_dir():
            raise ValueError(
                "OC_HARDWARE_ASSET_DIR must be an existing directory"
            )

    wav_value = os.getenv("OC_WAV_INPUT", "").strip()
    configured_ring_source = os.getenv("OC_RING_SOURCE", "").strip().lower()
    ring_source = configured_ring_source or (
        "wav" if wav_value else "none"
    )
    if ring_source not in {"none", "wav", "zilo-recorded"}:
        raise ValueError(
            "OC_RING_SOURCE must be none, wav or zilo-recorded"
        )
    if ring_source == "wav" and not wav_value:
        raise ValueError("OC_WAV_INPUT is required for wav ring source")

    zilo_address = None
    zilo_sdk_path = None
    ffmpeg_value = os.getenv("OC_FFMPEG_PATH", "ffmpeg").strip()
    ffmpeg_path = shutil.which(ffmpeg_value) or ffmpeg_value
    if ring_source == "zilo-recorded":
        zilo_address = _optional_env("OC_ZILO_ADDRESS")
        if zilo_address is None:
            raise ValueError("OC_ZILO_ADDRESS is required")
        sdk_value = _optional_env("OC_ZILO_SDK_PATH")
        if sdk_value is None:
            raise ValueError("OC_ZILO_SDK_PATH is required")
        zilo_sdk_path = Path(sdk_value)
        if not (zilo_sdk_path / "ring_sound.py").is_file():
            raise ValueError(
                "OC_ZILO_SDK_PATH must contain ring_sound.py"
            )
        resolved_ffmpeg = shutil.which(ffmpeg_value)
        if resolved_ffmpeg is None:
            raise ValueError("OC_FFMPEG_PATH must be executable")
        ffmpeg_path = resolved_ffmpeg

    return Settings(
        voice_provider=provider,
        cloud_base_url=os.getenv(
            "OC_CLOUD_BASE_URL", "https://oc-voice-lab.pages.dev"
        ).rstrip("/"),
        device_token=device_token,
        device_id=device_id,
        character=character,
        host=os.getenv("OC_BIND_HOST", "127.0.0.1"),
        port=port,
        display_transport=display_transport,
        wav_input=Path(wav_value) if wav_value else None,
        hardware_server_url=hardware_server_url,
        hardware_server_token=hardware_server_token,
        hardware_agent_id=hardware_agent_id,
        hardware_targets=hardware_targets,
        hardware_screen_tokens=hardware_screen_tokens,
        hardware_asset_dir=hardware_asset_dir,
        ring_source=ring_source,
        zilo_address=zilo_address,
        zilo_sdk_path=zilo_sdk_path,
        ffmpeg_path=ffmpeg_path,
    )


def load_zilo_sdk(path: Path) -> Any:
    module_path = path / "ring_sound.py"
    spec = importlib.util.spec_from_file_location(
        "_oc_zilo_ring_sound", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Zilo SDK from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    required = {
        "RingSoundClient",
        "receive_auto_audio_file",
        "decode_speex_to_pcm",
        "wait_sensor_key_double_press_event",
    }
    missing = sorted(name for name in required if not hasattr(module, name))
    if missing:
        raise RuntimeError(
            "Zilo SDK is missing public APIs: " + ", ".join(missing)
        )
    return module


async def build_app(settings: Settings) -> web.Application:
    session = ClientSession()
    if settings.voice_provider == "cloud":
        voice = CloudVoiceProvider(
            settings.cloud_base_url,
            settings.device_token or "",
            settings.character,
            session,
            device_id=settings.device_id,
        )
    else:
        voice = DirectStepFunProvider(settings.character, session)

    if settings.display_transport == "advx":
        display_transport = HardwareServerDisplayTransport(
            settings.hardware_server_url or "",
            settings.hardware_server_token or "",
            settings.hardware_agent_id or "",
            list(settings.hardware_targets),
            AssetStore(settings.hardware_asset_dir or Path(".")),
            session,
            screen_tokens=settings.hardware_screen_tokens,
        )
    else:
        display_transport = MockDisplayTransport(
            auto_ack=True, auto_ack_status="completed"
        )
    display = DisplayTaskOrchestrator(display_transport)
    app = create_app(display)
    zilo_sdk = None
    if settings.ring_source == "wav":
        source = WavRingAudioSource(settings.wav_input or "")
    elif settings.ring_source == "zilo-recorded":
        zilo_sdk = load_zilo_sdk(settings.zilo_sdk_path or Path("."))
        source = ZiloRecordedAudioSource(
            settings.zilo_address or "",
            zilo_sdk,
            ffmpeg_path=settings.ffmpeg_path,
        )
    else:
        source = None
    service = GatewayService(
        voice=voice,
        audio_source=source,
        audio_sinks=[app[PC_SINK_KEY]],
        displays=display,
        character_id=settings.character,
    )
    double_press_listener = (
        ZiloDoublePressListener(zilo_sdk, source.client, service)
        if zilo_sdk is not None
        and isinstance(source, ZiloRecordedAudioSource)
        else None
    )

    async def runtime(_: web.Application):
        tasks = [
            asyncio.create_task(
                service.run(), name="oc-gateway-service"
            )
        ]
        if double_press_listener is not None:
            tasks.append(
                asyncio.create_task(
                    double_press_listener.run_forever(),
                    name="oc-zilo-double-press",
                )
            )
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()
        await session.close()

    app.cleanup_ctx.append(runtime)
    return app


def main() -> None:
    settings = load_settings()
    web.run_app(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        print=lambda message: print(message, flush=True),
    )


if __name__ == "__main__":
    main()
