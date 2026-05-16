# -*- coding: utf-8 -*-
"""
宠物系统核心类

管理宠物的所有子系统，提供统一的接口
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any

from .models import (
    PetData,
    PetAttributes,
    PetConfig,
    GeneConfig,
    HeartConfig,
    DreamConfig,
    PersonalityConfig,
    HungerConfig,
    DiaryConfig,
    SocialConfig,
    HealthConfig,
    SkinConfig,
    SoundConfig,
)
from .subsystems import (
    GeneSystem,
    HeartSystem,
    DreamSystem,
    PersonalitySystem,
    HungerSystem,
    DiarySystem,
    SocialSystem,
    HealthSystem,
    SkinSystem,
    SoundSystem,
)
from .utils.storage import Storage


class PetSystemConfig:
    """宠物系统配置包装类"""

    def __init__(self, config: Optional[PetConfig] = None):
        if config is None:
            config = PetConfig()
        self._config = config
        self.pet = config
        self.gene = GeneConfig()
        self.heart = HeartConfig()
        self.dream = DreamConfig()
        self.personality = PersonalityConfig()
        self.hunger = HungerConfig()
        self.diary = DiaryConfig()
        self.social = SocialConfig()
        self.health = HealthConfig()
        self.skin = SkinConfig()
        self.sound = SoundConfig()


class PetSystem:
    """
    宠物系统核心类

    管理宠物的所有子系统，提供统一的接口。

    Attributes:
        config: 宠物系统配置
        data: 宠物数据
        gene_system: 基因系统
        heart_system: 心跳系统
        dream_system: 梦境系统
        personality_system: 性格系统
        hunger_system: 饥饿系统
        diary_system: 日记系统
        social_system: 社交系统
        health_system: 健康系统
        skin_system: 装扮系统
        sound_system: 声音系统
    """

    _instance: Optional['PetSystem'] = None
    _TOKENS_PER_EXP: int = 200
    _VALIDATION_EXP_REWARDS: Dict[str, int] = {
        "lint": 1,
        "compile": 1,
        "tests": 3,
        "validation": 2,
        "environment": 2,
    }
    _TASK_COMPLETION_EXP: int = 5

    def __new__(cls, config: Optional[PetConfig] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[PetConfig] = None):
        if self._initialized:
            return
        self._initialized = True

        # 配置
        self.config = PetSystemConfig(config)

        # 存储
        self.save_path = "workspace/memory/pet_info.json"
        self.storage = Storage(self.save_path)

        # 加载数据
        self.data = self._load_data()
        if not self.data.attributes.birth_time:
            self.data.attributes.birth_time = datetime.now().isoformat()

        # 初始化子系统
        self.gene_system = GeneSystem(self)
        self.heart_system = HeartSystem(self)
        self.dream_system = DreamSystem(self)
        self.personality_system = PersonalitySystem(self)
        self.hunger_system = HungerSystem(self)
        self.diary_system = DiarySystem(self)
        self.social_system = SocialSystem(self)
        self.health_system = HealthSystem(self)
        self.skin_system = SkinSystem(self)
        self.sound_system = SoundSystem(self)

    def _create_default_config(self) -> PetConfig:
        """创建默认配置"""
        return PetConfig(
            enabled=True,
            name="虾宝",
            auto_save=True,
            save_interval=60,
        )

    def _load_data(self) -> PetData:
        """加载数据"""
        raw_data = self.storage.load()
        if raw_data:
            try:
                return PetData(**raw_data)
            except Exception:
                pass
        return PetData()

    # ==================== 核心方法 ====================

    def record_tokens(self, input_tokens: int, output_tokens: int):
        """
        记录 Token 使用

        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
        """
        total_tokens = max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))
        self.hunger_system.record_tokens(input_tokens, output_tokens)
        self.health_system._update_metrics()
        if total_tokens > 0:
            exp_gain = max(1, total_tokens // self._TOKENS_PER_EXP)
            self.add_exp(exp_gain)
            self.save()

    def update_context_window(self, max_context: int):
        """
        更新模型上下文窗口

        Args:
            max_context: 最大上下文窗口
        """
        self.gene_system.update_context_window(max_context)
        self.hunger_system.update_context_window(max_context)

    def trigger_compression(self, compressed_tokens: int):
        """
        触发上下文压缩

        Args:
            compressed_tokens: 被压缩的 token 数
        """
        self.dream_system.enter_dream(compressed_tokens)

    def complete_task(self, task_type: str):
        """
        完成任务

        Args:
            task_type: 任务类型
        """
        self.personality_system.record_behavior(task_type)
        self.diary_system.add_entry(f"完成任务: {task_type}")
        self.data.attributes.total_tasks += 1

        # 检查成就
        if self.data.attributes.total_tasks == 1:
            self.skin_system.check_achievement("first_task")

        if self.data.attributes.level >= 10:
            self.skin_system.check_achievement("level_10")
        self.add_exp(self._TASK_COMPLETION_EXP)
        self.save()

    def reward_task_completion(self, task_type: str = "task") -> int:
        """轻量记录任务完成并给予经验，不依赖完整日记链路。"""
        self.data.attributes.total_tasks += 1
        self.personality_system.record_behavior(task_type)
        self.add_exp(self._TASK_COMPLETION_EXP)
        self.save()
        return self._TASK_COMPLETION_EXP

    def reward_validation(self, kind: str = "validation", passed: bool = True) -> int:
        """对通过的验证给予小额经验奖励。"""
        if not passed:
            return 0
        reward = self._VALIDATION_EXP_REWARDS.get(kind, self._VALIDATION_EXP_REWARDS["validation"])
        self.add_exp(reward)
        self.save()
        return reward

    def add_exp(self, amount: int) -> bool:
        """
        增加经验值

        Args:
            amount: 经验值数量

        Returns:
            是否升级
        """
        self.data.attributes.exp += amount
        leveled_up = False

        while self.data.attributes.exp >= self.data.attributes.exp_to_next:
            self.data.attributes.exp -= self.data.attributes.exp_to_next
            self.data.attributes.level += 1
            self.data.attributes.exp_to_next = int(self.data.attributes.exp_to_next * 1.5)
            leveled_up = True
            self.sound_system.play_sound("level_up")

        if leveled_up:
            self.skin_system.check_achievement("level_10")
            self.save()

        return leveled_up

    def trigger_heartbeat(self):
        """触发一次心跳"""
        return self.heart_system.beat()

    def meet_model(self, model_name: str):
        """
        遇见新模型

        Args:
            model_name: 模型名称
        """
        self.social_system.meet_model(model_name)

    def interact_with_model(self, model_name: str):
        """
        与模型互动

        Args:
            model_name: 模型名称
        """
        self.social_system.interact(model_name)

    # ==================== 状态获取 ====================

    def get_status_text(self) -> str:
        """
        获取完整状态文本

        Returns:
            状态文本
        """
        attrs = self.data.attributes

        # 经验条
        exp_bar = self._format_exp_bar(attrs.exp, attrs.exp_to_next)

        # 表情
        mood_emoji = self._get_mood_emoji(attrs.mood)
        hunger_emoji = self._get_hunger_emoji(attrs.hunger)
        heartbeat = self.heart_system.get_heartbeat_animation()

        lines = [
            f"🦞 Lv.{attrs.level} {attrs.name}",
            f"⭐ 经验: [{exp_bar}] {attrs.exp}/{attrs.exp_to_next}",
            f"{mood_emoji} 心情: {attrs.mood}/100",
            f"{hunger_emoji} 饱食: {attrs.hunger}/100",
            f"{heartbeat} 心跳: {self.heart_system.get_current_rate():.1f}Hz",
        ]

        # 基因
        if self.data.gene.model_family != "unknown":
            lines.append(f"🧬 基因: {self.data.gene.model_family}系")

        return "\n".join(lines)

    def get_full_status_text(self) -> str:
        """
        获取完整状态文本（包含所有子系统）

        Returns:
            完整状态文本
        """
        sections = [
            self.get_status_text(),
            self.personality_system.get_status_text(),
            self.hunger_system.get_status_text(),
            self.health_system.get_status_text(),
            self.gene_system.get_status_text(),
            self.social_system.get_status_text(),
            self.skin_system.get_status_text(),
            self.sound_system.get_status_text(),
            self.diary_system.get_status_text(),
        ]

        return "\n".join(sections)

    def get_status_dict(self) -> Dict[str, Any]:
        """
        获取完整状态字典

        Returns:
            状态字典
        """
        return {
            "attributes": self.data.attributes.model_dump(),
            "gene": self.data.gene.model_dump(),
            "heart": self.data.heart.model_dump(),
            "dream": self.data.dream.model_dump(),
            "personality": self.data.personality.model_dump(),
            "hunger": self.data.hunger.model_dump(),
            "diary": self.data.diary.model_dump(),
            "social": self.data.social.model_dump(),
            "health": self.data.health.model_dump(),
            "skin": self.data.skin.model_dump(),
            "sound": self.data.sound.model_dump(),
        }

    # ==================== 保存/加载 ====================

    def save(self):
        """保存到文件"""
        self.storage.save(self.data.model_dump())

    def load(self):
        """从文件加载"""
        self.data = self._load_data()

    def reset(self):
        """重置宠物数据"""
        self.data = PetData()
        self.data.attributes.birth_time = datetime.now().isoformat()
        self.save()

    # ==================== 辅助方法 ====================

    @staticmethod
    def _format_exp_bar(exp: int, exp_to_next: int, length: int = 10) -> str:
        """格式化经验条"""
        if exp_to_next <= 0:
            return "░" * length
        percent = exp / exp_to_next
        filled = int(percent * length)
        return "█" * filled + "░" * (length - filled)

    @staticmethod
    def _get_mood_emoji(mood: int) -> str:
        """根据心情值获取表情"""
        if mood > 80:
            return "😊"
        elif mood > 60:
            return "🙂"
        elif mood > 40:
            return "😐"
        elif mood > 20:
            return "😢"
        return "😭"

    @staticmethod
    def _get_hunger_emoji(hunger: int) -> str:
        """根据饱食度获取表情"""
        if hunger > 70:
            return "🍖"
        elif hunger > 40:
            return "🍽️"
        elif hunger > 20:
            return "🥺"
        return "😫"


# ==================== 全局单例 ====================

_pet_instance: Optional[PetSystem] = None


def get_pet_system(config: Optional[PetConfig] = None) -> PetSystem:
    """
    获取宠物系统单例

    Args:
        config: 宠物系统配置（首次调用时使用）

    Returns:
        宠物系统实例
    """
    global _pet_instance
    if _pet_instance is None:
        _pet_instance = PetSystem(config)
    return _pet_instance


def init_pet_system(config: Optional[PetConfig] = None) -> PetSystem:
    """
    初始化宠物系统

    Args:
        config: 宠物系统配置

    Returns:
        宠物系统实例
    """
    return get_pet_system(config)


def reset_pet_system():
    """重置宠物系统"""
    global _pet_instance
    if _pet_instance:
        _pet_instance.reset()
    _pet_instance = None
