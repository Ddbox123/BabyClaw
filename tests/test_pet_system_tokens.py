#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.pet_system.pet_system import get_pet_system, reset_pet_system


def test_record_tokens_increases_exp():
    reset_pet_system()
    pet = get_pet_system()
    start_exp = pet.data.attributes.exp
    start_total_tokens = pet.data.hunger.total_tokens

    pet.record_tokens(120, 180)

    assert pet.data.hunger.total_tokens == start_total_tokens + 300
    assert pet.data.attributes.exp > start_exp
