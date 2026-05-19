"""Language helpers for the web workbench."""

from __future__ import annotations

from config.public_config import load_public_config


DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = {"zh", "en"}


def resolve_language(value: object) -> str:
    text = str(value or DEFAULT_LANGUAGE).strip().lower()
    return text if text in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_web_language() -> str:
    try:
        public_config = load_public_config()
    except Exception:
        return DEFAULT_LANGUAGE
    return resolve_language(public_config.get("ui", {}).get("language", DEFAULT_LANGUAGE))


def text_for(lang: str, *, zh: str, en: str) -> str:
    return zh if resolve_language(lang) == "zh" else en
