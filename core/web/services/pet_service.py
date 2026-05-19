"""Pet space summary helpers."""

from __future__ import annotations

from config.public_config import load_public_config
from core.pet_system.pet_system import get_pet_system

from .i18n import get_web_language, text_for


def get_pet_summary() -> dict:
    """Return a condensed summary for the pet space page."""

    public_config = load_public_config()
    lang = get_web_language()
    avatar_preset = public_config.get("avatar", {}).get("preset", "lobster")

    pet = get_pet_system()
    attributes = pet.data.attributes
    hunger = pet.data.hunger
    social = pet.data.social
    dream = pet.data.dream
    heart = pet.data.heart

    return {
        "name": attributes.name,
        "avatarPreset": avatar_preset,
        "level": attributes.level,
        "exp": attributes.exp,
        "expToNext": attributes.exp_to_next,
        "mood": attributes.mood,
        "hunger": attributes.hunger,
        "energy": attributes.energy,
        "health": attributes.health,
        "love": attributes.love,
        "totalTasks": attributes.total_tasks,
        "achievements": attributes.achievements[:6],
        "heartActive": heart.is_active,
        "inDream": dream.in_dream,
        "friendCount": len(social.friends),
        "dailyTokens": hunger.daily_tokens,
        "totalTokens": hunger.total_tokens,
        "statusLine": _build_status_line(lang, attributes.mood, attributes.hunger, dream.in_dream),
    }


def _build_status_line(lang: str, mood: int, hunger: int, in_dream: bool) -> str:
    if in_dream:
        return text_for(lang, zh="正安静待在梦境循环里", en="resting inside a dream cycle")
    if hunger < 30:
        return text_for(lang, zh="有点想补充燃料了", en="asking for a little more fuel")
    if mood > 80:
        return text_for(lang, zh="状态明亮、稳定，而且很在场", en="bright, steady, and very present")
    if mood > 50:
        return text_for(lang, zh="情绪平稳，正在安静观察", en="calm and tracking the room")
    return text_for(lang, zh="状态有点低，但还在认真守着", en="a little low, but still keeping watch")
