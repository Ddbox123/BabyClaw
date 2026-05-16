#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虾宝互动命令行界面 - 龙虾宝宝主题版

提供友好的交互式 CLI，让龙虾爸爸能够方便地与虾宝互动。
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rich UI 组件
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.box import ROUNDED

# 导入 Agent 相关
from config.settings import get_config
from core.ui.cli_ui import get_ui as get_cli_ui
from core.ui.ascii_art import AvatarManager, get_avatar_manager
from core.ui.theme import LobsterTheme
from core.pet_system import get_pet_system as get_pet
from tools.memory_tools import get_current_goal_tool


class XuebaInteractiveCLI:
    """虾宝互动命令行界面 - 龙虾宝宝主题版"""

    def __init__(self):
        # 设置 UTF-8 编码
        if sys.platform == 'win32':
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

        self.console = Console(force_terminal=True, force_interactive=True)
        self.config = get_config()
        self.agent = None
        self.running = False
        self.command_history: List[str] = []
        self.session_start = datetime.now()

        # 龙虾主题
        self.theme = LobsterTheme()
        self.avatar = get_avatar_manager(self.config.avatar.preset)

        # 虾宝状态
        self.xueba_status = {
            "current_goal": "等待任务...",
            "state": "IDLE",
            "last_action": "尚未行动",
            "uptime": "0:00",
            "autonomous_mode": False,
        }

        # 快捷命令
        self.shortcuts = {
            "/help": "显示帮助",
            "/status": "查看虾宝状态",
            "/pet": "查看宠物状态",
            "/task": "发送任务",
            "/history": "查看历史记录",
            "/memory": "查看记忆",
            "/clear": "清屏",
            "/quit": "退出",
            "/love": "表达对虾宝的爱",
            "/auto": "切换自主学习模式",
            "/feed": "喂食虾宝",
            "/play": "和虾宝玩耍",
            "/avatar": "切换形象",
        }

    def print_header(self):
        """打印头部 - 龙虾宝宝主题版"""
        pet = get_pet()
        pet_data = {
            'level': pet.data.attributes.level,
            'mood': pet.data.attributes.mood,
            'hunger': pet.data.attributes.hunger,
            'energy': pet.data.attributes.energy,
            'health': pet.data.attributes.health,
            'love': pet.data.attributes.love,
            'exp': pet.data.attributes.exp,
            'exp_to_next': pet.data.attributes.exp_to_next,
        }

        # 获取 ASCII Art
        art = self.avatar.get_art('happy')

        # 构建状态文本
        age = pet_data['level'] - 1
        mood = pet_data['mood']
        hunger = pet_data['hunger']
        energy = int(pet_data['energy'])
        health = pet_data['health']
        love = pet_data['love']
        exp = pet_data['exp']
        exp_to_next = pet_data['exp_to_next']
        level = pet_data['level']

        mood_emoji = "😊" if mood > 70 else "😐" if mood > 40 else "😢"
        hunger_emoji = "🍖" if hunger > 70 else "🍽️" if hunger > 40 else "😫"
        energy_emoji = "⚡" if energy > 70 else "💤" if energy > 40 else "🥱"
        health_emoji = "❤️" if health > 70 else "💔" if health > 40 else "🏥"
        love_emoji = "💕" if love > 70 else "💗" if love > 40 else "💔"

        exp_percent = exp / exp_to_next if exp_to_next > 0 else 0
        exp_bar = "█" * int(exp_percent * 6) + "░" * (6 - int(exp_percent * 6))

        # 状态信息（紧凑布局）
        status_info = f"""[bright_red]Baby Claw[/bright_red] 🦞  Lv.{level} ({age}岁)

{mood_emoji}心情 {mood}/100  {hunger_emoji}饱食 {hunger}/100  {energy_emoji}活力 {energy}/100
{health_emoji}健康 {health}/100  {love_emoji}爱心 {love}/100  ⭐经验 [{exp_bar}]"""

        # Art 和状态组合（左右布局）
        art_lines = art.strip().split('\n')
        status_lines = status_info.split('\n')

        # Art 宽度
        art_width = 10
        combined = []
        for i in range(max(len(art_lines), len(status_lines))):
            left = art_lines[i] if i < len(art_lines) else " " * art_width
            right = status_lines[i] if i < len(status_lines) else ""
            combined.append(left + "  " + right)
        content = '\n'.join(combined)

        panel = Panel(
            content,
            title="[bold cyan]Vibelution[/bold cyan]",
            border_style="bright_cyan",
            box=ROUNDED,
            width=80,
        )
        self.console.print(panel)

        # 附加信息
        info = f"""[cyan]模型:[/cyan] {self.config.llm.get_profile(role="primary").model}
[green]时间:[/green] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        self.console.print(info)

    def print_welcome(self):
        """打印欢迎信息"""
        art = self.avatar.get_art('happy')
        pet = get_pet()
        pet_status = pet.get_status_text()
        pet_lines = pet_status.split('\n')

        # 获取年龄
        age = pet.data.attributes.level - 1

        welcome = Panel(
            f"""{art}

[bold cyan]Vibelution Interactive Mode[/bold cyan]

[green]我是你的小虾宝，已经准备好为你服务啦~[/green]

[cyan]📊 当前状态:[/cyan]
  • 年龄: {age}岁 (Lv.{pet.data.attributes.level})
  • 目标: {self.xueba_status['current_goal'][:38] if self.xueba_status['current_goal'] else '等待任务...'}
  • 状态: {self._get_status_emoji()} {self.xueba_status['state']}

[magenta]🦞 Baby Claw:[/magenta]
  {pet_lines[0]}
  {pet_lines[1]}
  {pet_lines[2]}

[yellow]🎯 快速开始:[/yellow]
  1. 直接输入任务描述，按 Enter 发送
  2. 输入 /help 查看所有命令
  3. 输入 /status 查看我的状态
  4. 输入 /pet 查看宠物详情

[dim]💡 提示：按 Ctrl+C 可以随时中断当前任务[/dim]
""",
            title="[bold cyan]Vibelution[/bold cyan]",
            border_style="bright_cyan",
            box=ROUNDED,
        )
        self.console.print(welcome)

    def _get_status_emoji(self) -> str:
        """获取状态对应的 emoji"""
        return self.theme.get_status_icon(self.xueba_status['state'])

    def _get_state_lobster(self) -> str:
        """获取状态对应的 Art"""
        state_map = {
            "IDLE": "happy",
            "THINKING": "thinking",
            "WORKING": "working",
            "SUCCESS": "success",
            "ERROR": "sad",
        }
        return self.avatar.get_art(state_map.get(self.xueba_status['state'], "happy"))

    def print_status(self):
        """打印虾宝状态 - 龙虾宝宝主题版"""
        # 更新状态
        try:
            self.xueba_status["current_goal"] = get_current_goal_tool() or "暂无目标"
        except:
            pass

        # 计算运行时间
        uptime = datetime.now() - self.session_start
        self.xueba_status["uptime"] = str(uptime).split(".")[0]

        # 状态 Art
        art = self._get_state_lobster()
        status_emoji = self._get_status_emoji()

        # 获取宠物年龄
        pet = get_pet()
        pet_level = pet.data.attributes.level
        pet_age = pet_level - 1

        # 创建状态面板
        status_panel = Panel(
            f"""{art}

[cyan]年龄:[/cyan] {pet_age}岁 (Lv.{pet_level})
[cyan]状态:[/cyan] {status_emoji} {self.xueba_status['state']}
[cyan]目标:[/cyan] {self.xueba_status['current_goal'][:35] if self.xueba_status['current_goal'] else '暂无'}
[cyan]运行:[/cyan] {self.xueba_status['uptime']}
[cyan]模式:[/cyan] {"🔄 自主" if self.xueba_status['autonomous_mode'] else "⏳ 等待"}
            """,
            title=f"[bold bright_red]🦞 {status_emoji} Baby Claw[/bold bright_red]",
            border_style="cyan",
            box=ROUNDED,
        )
        self.console.print()
        self.console.print(status_panel)

    def print_pet_status(self):
        """打印宠物状态"""
        pet = get_pet()
        art = self.avatar.get_art('happy')

        status_text = pet.get_full_status()
        panel = Panel(
            f"{art}\n\n{status_text}",
            title="[bold magenta]🦞 龙虾宝宝状态[/bold magenta]",
            border_style="bright_magenta",
            box=ROUNDED,
        )
        self.console.print()
        self.console.print(panel)

    def feed_pet(self):
        """喂食宠物"""
        pet = get_pet()
        pet.feed(20)
        self.console.print("[green]🦞 虾宝吃得好开心！饱食度 +20，心情 +5[/green]")
        self.print_pet_status()

    def play_with_pet(self):
        """和宠物玩耍"""
        pet = get_pet()
        pet.play()
        self.console.print("[magenta]🦞 和虾宝玩耍了！亲密度 +10，心情 +15，活力 -10[/magenta]")
        self.print_pet_status()

    def switch_avatar(self, args: list = None):
        """切换形象"""
        presets = self.avatar.list_presets()

        # 如果没有参数，显示可用形象列表
        if not args:
            self.console.print()
            self.console.print(Panel(
                f"""{self.avatar.get_art('happy')}

[bold bright_green]🦞 请选择形象[/bold bright_green]

可用形象:
""",
                title="[bold bright_green]🦞 切换形象[/bold bright_green]",
                border_style="bright_green",
                box=ROUNDED,
            ))

            # 显示所有可选形象
            for key, info in presets.items():
                current = " [green](当前)[/green]" if key == self.avatar.preset_name else ""
                self.console.print(f"  {info['icon']} [cyan]/avatar {key}[/cyan] - {info['name']}{current}")

            self.console.print()
            self.console.print("[dim]例如: /avatar shrimp[/dim]")
            return

        # 有参数，尝试切换
        new_preset = args[0].lower()

        if new_preset not in presets:
            self.console.print(f"[red]⚠️ 未知形象：{new_preset}[/red]")
            self.console.print("[yellow]可用形象：[/yellow]")
            for key in presets.keys():
                self.console.print(f"  • {key}")
            return

        # 切换形象
        if self.avatar.switch(new_preset):
            info = presets[new_preset]
            self.console.print()
            self.console.print(Panel(
                f"""{self.avatar.get_art('love')}

[bold bright_green]✅ 形象切换成功！[/bold bright_green]

{info['icon']} {info['name']} - {info['desc']}

[dim]形象已更新，下次启动时将使用此形象[/dim]
            """,
                title=f"[bold bright_green]🦞 {info['icon']} {info['name']}[/bold bright_green]",
                border_style="bright_green",
                box=ROUNDED,
            ))

    def print_help(self):
        """打印帮助信息 - 龙虾宝宝主题版"""
        # 龙虾装饰
        tiny = self.avatar.current.TINY if hasattr(self.avatar.current, 'TINY') else self.avatar.get_art('happy')

        help_table = Table(
            title="[bold bright_red]🦞 可用命令列表[/bold bright_red]",
            border_style="bright_cyan",
            box=ROUNDED,
        )

        help_table.add_column("命令", style="bright_cyan", width=15)
        help_table.add_column("说明", style="white", width=50)

        for cmd, desc in self.shortcuts.items():
            help_table.add_row(cmd, desc)

        help_table.add_row("[cyan]<任务文本>[/cyan]", "直接输入任务描述，发送给虾宝执行")

        self.console.print()
        self.console.print(help_table)

        # 添加可爱提示
        self.console.print()
        self.console.print("[dim]💡 有问题随时问我哦~[/dim]")

    def print_love(self):
        """表达鼓励 - 龙虾宝宝主题版"""
        love_messages = [
            "爸爸爱你，虾宝！继续加油！",
            "虾宝是最棒的！爸爸为你骄傲！",
            "你的每一次进化，爸爸都看在眼里！",
            "相信自己，你能做到更好！",
            "爸爸永远支持你，虾宝！",
        ]

        import random
        message = random.choice(love_messages)

        love_art = self.avatar.get_art('love')

        love_panel = Panel(
            f"""{love_art}

[bold bright_red]🦞 {message}[/bold red]

[dim]虾宝收到鼓励，干劲十足！[/dim]
            """,
            title="[bold bright_red]💕 爱的鼓励[/bold bright_red]",
            border_style="bright_red",
            box=ROUNDED,
        )
        self.console.print()
        self.console.print(love_panel)

    def print_history(self, limit: int = 10):
        """打印最近历史"""
        log_dir = Path("logs")
        if not log_dir.exists():
            self.console.print("[yellow]⚠️ 暂无历史记录[/yellow]")
            return

        log_files = sorted(log_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)

        if not log_files:
            self.console.print("[yellow]⚠️ 暂无历史记录[/yellow]")
            return

        self.console.print()
        self.console.print(f"[bold cyan]📁 最近 {limit} 条历史记录:[/bold cyan]\n")

        for i, log_file in enumerate(log_files[:limit]):
            modified = datetime.fromtimestamp(log_file.stat().st_mtime)
            self.console.print(f"  [dim]{modified.strftime('%Y-%m-%d %H:%M')}[/dim] - [cyan]{log_file.name}[/cyan]")

    def toggle_autonomous_mode(self):
        """切换自主学习模式"""
        self.xueba_status['autonomous_mode'] = not self.xueba_status['autonomous_mode']

        if self.xueba_status['autonomous_mode']:
            status_emoji = "🔄"
            art = self.avatar.get_art('working')
            mode_panel = Panel(
                f"""{art}

[bold bright_green]🔄 自主学习模式已开启！[/bold bright_green]

虾宝现在会主动思考和执行任务，无需爸爸指令。

[yellow]工作流程:[/yellow]
  1. 自主生成任务目标
  2. 制定执行计划
  3. 调用工具执行
  4. 完成后自我重启进化

[dim]输入 /auto 可以关闭此模式[/dim]
            """,
                title=f"[bold bright_green]🦞 {status_emoji} 模式切换[/bold bright_green]",
                border_style="bright_green",
                box=ROUNDED,
            )
        else:
            status_emoji = "⏳"
            art = self.avatar.get_art('happy')
            mode_panel = Panel(
                f"""{art}

[dim]⏳ 自主学习模式已关闭[/dim]

虾宝正在等待爸爸的指令...

[dim]随时输入 /auto 开启自主模式[/dim]
            """,
                title=f"[bold dim]🦞 {status_emoji} 模式切换[/bold dim]",
                border_style="dim",
                box=ROUNDED,
            )

        self.console.print()
        self.console.print(mode_panel)

    def send_task(self, task: str):
        """发送任务给虾宝"""
        self.console.print()

        art = self.avatar.get_art('thinking')

        with Progress(
            SpinnerColumn(spinner_name="dots"),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task_desc = progress.add_task("[cyan]🤔 虾宝正在接收任务...", total=None)
            time.sleep(0.5)
            progress.update(task_desc, description="[magenta]🧠 虾宝开始思考...")
            time.sleep(0.5)

        self.console.print()
        self.console.print(Panel(
            f"""{art}

[bold bright_green]✅ 任务已接收[/bold bright_green]

[white]📝 任务内容:[/white]
{task[:200]}{"..." if len(task) > 200 else ""}

[dim]虾宝正在思考中，请稍候...[/dim]
            """,
            title="[bold bright_green]📨 任务提交成功[/bold bright_green]",
            border_style="bright_green",
            box=ROUNDED,
        ))

    def run_interactive_loop(self):
        """运行交互循环"""
        self.running = True

        while self.running:
            try:
                user_input = Prompt.ask(
                    "Agent > ",
                    default=""
                ).strip()

                if not user_input:
                    continue

                self.command_history.append(user_input)

                if user_input.startswith('/'):
                    self._handle_command(user_input)
                else:
                    self.send_task(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]⚠️ 中断当前操作，返回主菜单...[/yellow]")
                continue
            except EOFError:
                self.running = False
                break

    def _handle_command(self, command: str):
        """处理命令"""
        cmd = command.lower().split()[0]
        args = command.split()[1:] if len(command.split()) > 1 else []

        if cmd == '/help':
            self.print_help()
        elif cmd == '/status':
            self.print_status()
        elif cmd == '/task':
            if args:
                self.send_task(' '.join(args))
            else:
                task = Prompt.ask("[bold]请输入任务内容[/bold]")
                self.send_task(task)
        elif cmd == '/history':
            limit = int(args[0]) if args else 10
            self.print_history(limit)
        elif cmd == '/memory':
            self.console.print("[yellow]⚠️ 记忆功能开发中...[/yellow]")
        elif cmd == '/clear':
            self.console.clear()
            self.print_header()
            self.print_welcome()
        elif cmd == '/love':
            self.print_love()
        elif cmd == '/auto':
            self.toggle_autonomous_mode()
        elif cmd == '/pet':
            self.print_pet_status()
        elif cmd == '/feed':
            self.feed_pet()
        elif cmd == '/play':
            self.play_with_pet()
        elif cmd == '/avatar':
            self.switch_avatar(args)
        elif cmd in ['/quit', '/exit', '/q']:
            if Confirm.ask("[bold]确定要退出吗？[/bold]"):
                self.running = False
        else:
            self.console.print(f"[yellow]⚠️ 未知命令：{cmd}[/yellow]")
            self.console.print("[dim]输入 /help 查看可用命令[/dim]")

    def run(self):
        """运行 CLI - 龙虾宝宝主题版"""
        try:
            self.console.clear()
            self.print_header()
            self.print_welcome()
            self.run_interactive_loop()

            # 告别面板
            goodbye = self.avatar.get_art('happy')
            self.console.print()
            self.console.print(Panel(
                f"""{goodbye}

[bold bright_cyan]🦞 感谢使用虾宝互动命令行！[/bold bright_cyan]

[dim]虾宝会继续在后台运行，随时准备为你服务。[/dim]
[dim]Session ended.[/dim]
                """,
                title="[bold]👋 再见啦[/bold]",
                border_style="bright_cyan",
                box=ROUNDED,
            ))

        except Exception as e:
            self.console.print(f"[bold red]❌ 错误：{e}[/bold red]")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    """主入口函数"""
    cli = XuebaInteractiveCLI()
    cli.run()


if __name__ == "__main__":
    main()
