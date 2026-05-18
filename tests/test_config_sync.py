#!/usr/bin/env python3
"""
配置结构统一性测试
"""

import tomllib
from pathlib import Path

from config import AppConfig, ConfigLoader, Settings, denormalize_config_dict, normalize_public_config_dict


PROJECT_ROOT = Path(__file__).parent.parent
MAIN_CONFIG = PROJECT_ROOT / "config.toml"
EXAMPLE_CONFIG = PROJECT_ROOT / "config.example.toml"


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _assert_same_shape(left, right, path="root"):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return

    assert type(left) is type(right), f"{path}: {type(left).__name__} != {type(right).__name__}"

    if isinstance(left, dict):
        assert set(left.keys()) == set(right.keys()), (
            f"{path}: keys mismatch\nleft={sorted(left.keys())}\nright={sorted(right.keys())}"
        )
        for key in sorted(left.keys()):
            _assert_same_shape(left[key], right[key], f"{path}.{key}")
        return

    if isinstance(left, list):
        if not left or not right:
            return
        first_left = left[0]
        first_right = right[0]
        if isinstance(first_left, dict) and isinstance(first_right, dict):
            assert set(first_left.keys()) == set(first_right.keys()), (
                f"{path}[0]: dict item keys mismatch\n"
                f"left={sorted(first_left.keys())}\nright={sorted(first_right.keys())}"
            )


def _assert_model_shape_is_exposed(expected, actual, path="root"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict"
        for key, value in expected.items():
            assert key in actual, f"{path}: missing key {key}"
            _assert_model_shape_is_exposed(value, actual[key], f"{path}.{key}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list"
        return


def test_config_files_have_same_public_shape():
    main = _load_toml(MAIN_CONFIG)
    example = _load_toml(EXAMPLE_CONFIG)

    _assert_same_shape(main, example)


def test_main_config_exposes_all_public_model_blocks():
    raw = _load_toml(MAIN_CONFIG)
    assert "providers" not in raw["llm"]
    assert "profiles" in raw["llm"]
    assert "discovery" in raw["llm"]
    assert "model_library" in raw["llm"]
    assert "primary" in raw["llm"]["profiles"]
    assert "provider" in raw["llm"]["profiles"]["primary"]
    assert "share_ai" in raw["llm"]["model_library"]
    assert "provider" in raw["llm"]["model_library"]["share_ai"]


def test_config_loader_normalizes_nested_public_blocks():
    raw = _load_toml(MAIN_CONFIG)
    normalized = normalize_public_config_dict(raw)
    config = AppConfig.model_validate(normalized)

    assert config.llm.get_profile("compression").model == raw["llm"]["profiles"]["compression"]["model"]
    assert config.llm.discovery.timeout == raw["llm"]["discovery"]["timeout"]
    assert config.pet_gene.inherit_from_model == raw["pet"]["gene"]["inherit_from_model"]
    assert len(config.prompt.sections) == len(raw["prompt"]["sections"])


def test_main_and_example_configs_load_through_entrypoints():
    main_loader = ConfigLoader(str(MAIN_CONFIG)).load()
    example_loader = ConfigLoader(str(EXAMPLE_CONFIG)).load()
    settings_config = Settings(config_path=str(MAIN_CONFIG)).config
    main_primary_provider_kind = main_loader.llm.get_provider(main_loader.llm.get_profile("primary").provider_id).kind
    settings_primary_provider_kind = settings_config.llm.get_provider(
        settings_config.llm.get_profile("primary").provider_id
    ).kind

    assert main_loader.prompt.default_components == settings_config.prompt.default_components
    assert "CONFIG_AWARENESS" in main_loader.prompt.default_components
    assert "LANGUAGE_AWARENESS" in main_loader.prompt.default_components
    assert "MEMORY" in main_loader.prompt.default_components
    assert len(main_loader.prompt.sections) == len(settings_config.prompt.sections) == 2
    assert example_loader.tools.restart_enabled is True
    assert main_loader.pet_heart.enabled is True
    assert settings_primary_provider_kind == main_primary_provider_kind
