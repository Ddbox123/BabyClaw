# -*- coding: utf-8 -*-
"""
饥饿系统

Token 作为食物，饭量 = 上下文窗口
"""

from typing import Dict, Any
from datetime import datetime
from .base import PetSubsystem
from core.ui.token_display import format_token_count


class HungerSystem(PetSubsystem):
    """饥饿系统 - Token 作为食物"""

    def update_context_window(self, max_context: int):
        """
        更新饭量

        Args:
            max_context: 最大上下文窗口
        """
        hunger = self.pet.data.hunger
        hunger.context_window = max_context
        hunger.meal_size = int(max_context * self.config.hunger.food_per_meal)

    def record_tokens(self, input_tokens: int, output_tokens: int):
        """
        记录 Token 使用

        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
        """
        hunger = self.pet.data.hunger
        total = input_tokens + output_tokens

        hunger.daily_tokens += total
        hunger.total_tokens += total
        hunger.total_llm_calls += 1

        # 更新每日记录
        today = datetime.now().strftime("%Y-%m-%d")
        self._update_daily_record(today, input_tokens, output_tokens, total)

        # 检查是否应该投喂
        if hunger.daily_tokens >= hunger.meal_size:
            self._feed()
            hunger.daily_tokens -= hunger.meal_size

    def _update_daily_record(self, today: str, input_tokens: int, output_tokens: int, total: int):
        """更新每日记录"""
        daily_records = self.pet.data.daily_records

        # 查找今天的记录
        for record in daily_records:
            if record.date == today:
                record.input_tokens += input_tokens
                record.output_tokens += output_tokens
                record.total_tokens += total
                record.llm_calls += 1
                return

        # 创建新记录
        from ..models import DailyRecord
        new_record = DailyRecord(
            date=today,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            llm_calls=1,
        )
        daily_records.append(new_record)

    def _feed(self):
        """投喂宠物"""
        hunger = self.pet.data.hunger
        today = datetime.now().strftime("%Y-%m-%d")

        if hunger.last_feed_date != today:
            # 增加饱食度
            amount = (self.pet.data.hunger.meal_size / 1000) * 10
            self.pet.data.attributes.hunger = min(100, self.pet.data.attributes.hunger + amount)
            self.pet.data.attributes.mood = min(100, self.pet.data.attributes.mood + 5)
            hunger.last_feed_date = today

            # 播放进食声音
            self.pet.sound_system.play_sound("eating")

    def decay(self, delta_time: float):
        """
        衰减饱食度

        Args:
            delta_time: 时间增量（秒）
        """
        hunger = self.pet.data.attributes.hunger
        hunger = max(0, hunger - self.config.hunger.hunger_decay_rate * delta_time / 60)
        self.pet.data.attributes.hunger = hunger

        # 饱食度低时心情下降
        if hunger < 30:
            mood = self.pet.data.attributes.mood
            self.pet.data.attributes.mood = max(0, mood - self.config.hunger.mood_decay_rate * delta_time / 60)

    def get_food_level(self) -> str:
        """
        获取食物等级

        Returns:
            食物等级描述
        """
        hunger = self.pet.data.attributes.hunger
        if hunger > 70:
            return "full"
        elif hunger > 40:
            return "normal"
        elif hunger > 20:
            return "hungry"
        return "starving"

    def get_food_level_emoji(self) -> str:
        """
        获取食物等级表情

        Returns:
            食物等级表情
        """
        hunger = self.pet.data.attributes.hunger
        if hunger > 70:
            return "🍖 饱饱"
        elif hunger > 40:
            return "🍽️ 刚好"
        elif hunger > 20:
            return "🥺 饿了"
        return "😫 饥饿"

    def get_meal_progress(self) -> str:
        """
        获取饭量进度

        Returns:
            饭量进度条
        """
        hunger = self.pet.data.hunger
        if hunger.meal_size <= 0:
            return "░" * 10

        progress = min(1.0, hunger.daily_tokens / hunger.meal_size)
        bar_length = int(progress * 10)
        return "▓" * bar_length + "░" * (10 - bar_length)

    def get_status_text(self) -> str:
        """获取状态文本"""
        hunger = self.pet.data.hunger
        food_emoji = self.get_food_level_emoji()
        progress = self.get_meal_progress()

        return f"""
🍽️ 饥饿: {food_emoji}
   饭量: {format_token_count(hunger.meal_size)} tokens/餐
   今日: {format_token_count(hunger.daily_tokens)}/{format_token_count(hunger.meal_size)} [{progress}]
   累计: {format_token_count(hunger.total_tokens)} tokens | {hunger.total_llm_calls:,} 次调用
"""

    def get_status_dict(self) -> Dict[str, Any]:
        """获取状态字典"""
        hunger = self.pet.data.hunger
        return {
            "context_window": hunger.context_window,
            "meal_size": hunger.meal_size,
            "daily_tokens": hunger.daily_tokens,
            "total_tokens": hunger.total_tokens,
            "total_llm_calls": hunger.total_llm_calls,
            "food_level": self.get_food_level(),
        }
