from pathlib import Path
import json
import sys

import pytest

from oc_gateway.__main__ import load_settings


def base_cloud_env(monkeypatch):
    monkeypatch.setenv("OC_VOICE_PROVIDER", "cloud")
    monkeypatch.setenv("OC_DEVICE_TOKEN", "test-device-token")
    monkeypatch.delenv("OC_DISPLAY_TRANSPORT", raising=False)
    monkeypatch.delenv("OC_RING_SOURCE", raising=False)
    monkeypatch.delenv("OC_WAV_INPUT", raising=False)


def test_requires_device_token_in_cloud_mode(monkeypatch):
    monkeypatch.setenv("OC_VOICE_PROVIDER", "cloud")
    monkeypatch.delenv("OC_DEVICE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="OC_DEVICE_TOKEN"):
        load_settings()


def test_defaults_to_safe_local_bind(monkeypatch):
    monkeypatch.setenv("OC_VOICE_PROVIDER", "cloud")
    monkeypatch.setenv("OC_DEVICE_TOKEN", "test")
    settings = load_settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8787
    assert settings.cloud_base_url == "https://oc-voice-lab.pages.dev"
    assert settings.device_id == "orangepi-3b-01"


def test_rejects_an_invalid_device_id(monkeypatch):
    base_cloud_env(monkeypatch)
    monkeypatch.setenv("OC_DEVICE_ID", "../bad")
    with pytest.raises(ValueError, match="OC_DEVICE_ID"):
        load_settings()


def test_rejects_an_unknown_provider(monkeypatch):
    monkeypatch.setenv("OC_VOICE_PROVIDER", "mystery")
    with pytest.raises(ValueError, match="OC_VOICE_PROVIDER"):
        load_settings()


def test_advx_display_requires_complete_route(monkeypatch, tmp_path):
    base_cloud_env(monkeypatch)
    monkeypatch.setenv("OC_DISPLAY_TRANSPORT", "advx")
    monkeypatch.setenv(
        "OC_HARDWARE_SERVER_URL", "http://127.0.0.1:8781"
    )
    monkeypatch.setenv(
        "OC_HARDWARE_SERVER_TOKEN", "server-token"
    )
    monkeypatch.setenv(
        "OC_HARDWARE_AGENT_ID", "orangepi-3b-01"
    )
    monkeypatch.setenv(
        "OC_HARDWARE_TARGETS", '["left", "right", "left"]'
    )
    monkeypatch.setenv(
        "OC_HARDWARE_SCREEN_TOKENS",
        '{"left": "left-token", "right": ""}',
    )
    monkeypatch.setenv("OC_HARDWARE_ASSET_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.display_transport == "advx"
    assert settings.hardware_targets == ("left", "right")
    assert settings.hardware_screen_tokens == {
        "left": "left-token",
        "right": "",
    }
    assert settings.hardware_asset_dir == tmp_path


def test_advx_display_rejects_invalid_target_json(monkeypatch, tmp_path):
    base_cloud_env(monkeypatch)
    monkeypatch.setenv("OC_DISPLAY_TRANSPORT", "advx")
    monkeypatch.setenv(
        "OC_HARDWARE_SERVER_URL", "http://127.0.0.1:8781"
    )
    monkeypatch.setenv(
        "OC_HARDWARE_SERVER_TOKEN", "server-token"
    )
    monkeypatch.setenv(
        "OC_HARDWARE_AGENT_ID", "orangepi-3b-01"
    )
    monkeypatch.setenv("OC_HARDWARE_TARGETS", '{"left": true}')
    monkeypatch.setenv("OC_HARDWARE_ASSET_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="OC_HARDWARE_TARGETS"):
        load_settings()


def test_zilo_source_requires_existing_sdk_path(monkeypatch, tmp_path):
    base_cloud_env(monkeypatch)
    monkeypatch.setenv("OC_RING_SOURCE", "zilo-recorded")
    monkeypatch.setenv(
        "OC_ZILO_ADDRESS", "AA:BB:CC:DD:EE:FF"
    )
    monkeypatch.setenv(
        "OC_ZILO_SDK_PATH", str(tmp_path / "missing-sdk")
    )
    monkeypatch.setenv("OC_FFMPEG_PATH", sys.executable)
    with pytest.raises(ValueError, match="OC_ZILO_SDK_PATH"):
        load_settings()


def test_zilo_source_accepts_complete_configuration(
    monkeypatch, tmp_path
):
    base_cloud_env(monkeypatch)
    (tmp_path / "ring_sound.py").write_text(
        "__all__ = []\n", encoding="utf-8"
    )
    monkeypatch.setenv("OC_RING_SOURCE", "zilo-recorded")
    monkeypatch.setenv(
        "OC_ZILO_ADDRESS", "AA:BB:CC:DD:EE:FF"
    )
    monkeypatch.setenv("OC_ZILO_SDK_PATH", str(tmp_path))
    monkeypatch.setenv("OC_FFMPEG_PATH", sys.executable)
    settings = load_settings()
    assert settings.ring_source == "zilo-recorded"
    assert settings.zilo_sdk_path == tmp_path


def test_mock_and_no_ring_remain_safe_defaults(monkeypatch):
    base_cloud_env(monkeypatch)
    settings = load_settings()
    assert settings.display_transport == "mock"
    assert settings.ring_source == "none"


def test_legacy_wav_input_selects_wav_source(monkeypatch, tmp_path):
    base_cloud_env(monkeypatch)
    wav_path = tmp_path / "speech.wav"
    monkeypatch.setenv("OC_WAV_INPUT", str(wav_path))
    settings = load_settings()
    assert settings.ring_source == "wav"
    assert settings.wav_input == wav_path


def test_systemd_unit_uses_dedicated_unprivileged_service():
    unit = (
        Path(__file__).parents[1] / "systemd" / "oc-gatewayd.service"
    ).read_text(encoding="utf-8")
    assert "User=orangepi" in unit
    assert "EnvironmentFile=/etc/oc-gatewayd.env" in unit
    assert "NoNewPrivileges=true" in unit
