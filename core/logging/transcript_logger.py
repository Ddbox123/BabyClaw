# -*- coding: utf-8 -*-
"""
优雅对话渲染器 - 将 LLM 交互生成为精美的 Markdown 文本

特性：
- 使用 HTML <details> 折叠超长内容（System Prompt）
- 醒目的标题和引用块区分不同角色
- 代码块自动高亮语言标签
- 工具调用以列表形式优雅呈现
- 自动清理旧会话文件（保留最近 5 个）
"""

import os
import re
import glob
import queue
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path


class TranscriptLogger:
    """
    优雅对话渲染器 - 生成精美的 Markdown 对话实录

    排版规范：
    - System Prompt: 使用 <details> 折叠
    - User Input: 引用块 + 标题
    - LLM Response: 正常 Markdown 渲染
    - Tool Calls: 无序列表 + 截断显示
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 获取项目根目录 (core/logging/transcript_logger.py -> core/ -> project_root)
        self._project_root = Path(__file__).parent.parent.parent.resolve()
        self._logs_dir = self._project_root / "workspace" / "logs" / "transcripts"
        self._ensure_logs_dir()

        # 当前会话和对话轮次
        self._session_id = None
        self._current_turn = 0
        self._is_first_message = True
        self._system_prompt_written = False

        # 后台写入线程，避免磁盘 I/O 阻塞主循环
        self._write_queue = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="transcript-writer"
        )
        self._writer_thread.start()

    def _writer_loop(self):
        """后台线程：从队列中取出内容并写入文件"""
        while True:
            try:
                filepath, content = self._write_queue.get()
                if filepath is None:
                    break
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write(content)
            except Exception:
                pass

    def _enqueue_write(self, content: str):
        """将写入内容放入队列，由后台线程异步写入"""
        self._write_queue.put((self._get_transcript_file(), content))

    def _flush_pending_writes(self):
        """等待所有待处理的写入完成"""
        self._write_queue.join()

    def _ensure_logs_dir(self):
        """确保日志目录存在"""
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _timestamp(self) -> str:
        """获取格式化的时间戳"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_transcript_file(self) -> Path:
        """获取当前会话的 Markdown 记录文件路径"""
        if self._session_id is None:
            self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._logs_dir / f"transcript_{self._session_id}.md"

    def _generate_header(self) -> str:
        """生成 Markdown 文件头部"""
        header = f"""---
title: "对话实录"
date: "{datetime.now().isoformat()}"
session: {self._session_id}
---

# 📝 对话实录

> _自动生成于 {self._timestamp()}_

"""
        return header

    def _generate_turn_header(self, turn: int, timestamp: str = None) -> str:
        """生成对话轮次标题"""
        ts = timestamp or self._timestamp()
        return f"""

---

## 🔄 第 {turn} 轮对话

> ⏰ {ts}

"""

    def _escape_markdown(self, text: str) -> str:
        """转义 Markdown 特殊字符（但不转义代码块内的内容）"""
        if not text:
            return ""

        # 分割代码块和普通文本，分别处理
        parts = []
        in_code_block = False

        for line in text.split('\n'):
            if line.startswith('```'):
                in_code_block = not in_code_block
                parts.append(line)
            elif not in_code_block:
                # 只转义真正需要转义的字符（列表中的符号）
                # 不转义反斜杠本身
                pass  # 保持原样，让渲染器自己处理
            parts.append(line)

        return '\n'.join(parts)

    def _detect_language(self, code: str) -> str:
        """智能检测代码语言"""
        if code.startswith('```'):
            # 提取语言标签
            lang = code.split('\n')[0][3:].strip().lower()
            if lang:
                return lang
        return "python"  # 默认语言

    def _format_code_block(self, code: str) -> str:
        """格式化代码块，确保有语言标签"""
        if not code:
            return ""

        lines = code.split('\n')
        if not lines:
            return ""

        # 如果已经有语言标签，直接返回（确保末尾有结束标签）
        if lines[0].startswith('```') and lines[-1].strip() == '```':
            return code

        # 检测语言
        lang = self._detect_language(code)

        # 构建带语言标签的代码块
        return f"```{lang}\n{code}\n```"

    def _truncate_text(self, text: str, max_length: int = 500, suffix: str = "...") -> str:
        """截断文本并添加后缀"""
        if not text or len(text) <= max_length:
            return text
        return text[:max_length].rstrip() + suffix

    def _format_tool_args(self, args: Dict[str, Any]) -> str:
        """格式化工具参数为可读形式"""
        if not args:
            return "{}"

        formatted = []
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 100:
                formatted.append(f'  "{key}": "{self._truncate_text(value, 80)}"')
            elif isinstance(value, dict):
                formatted.append(f'  "{key}": {str(value)[:100]}...')
            elif isinstance(value, bool):
                formatted.append(f'  "{key}": {"true" if value else "false"}')
            else:
                formatted.append(f'  "{key}": {repr(value)}')
        return "{\n" + ",\n".join(formatted) + "\n}"

    # ==================== 主要 API ====================

    def start_session(self, system_prompt: str = None):
        """开始新的会话记录"""
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_turn = 0
        self._is_first_message = True
        self._system_prompt_written = False

        # 写入文件头
        transcript_file = self._get_transcript_file()
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(self._generate_header())

        # 如果有 System Prompt，写入折叠版本
        if system_prompt:
            self.write_system_prompt(system_prompt)

        # 执行清理
        self.cleanup_old_transcripts()

    def write_system_prompt(self, system_prompt: str):
        """写入 System Prompt（折叠形式）"""
        if self._system_prompt_written:
            return

        self._system_prompt_written = True

        # 转义并截断内容
        escaped_content = self._escape_markdown(system_prompt)
        truncated_content = self._truncate_text(escaped_content, 2000, "\n\n_...[内容过长已截断]..._")

        content = f"""

## 🧠 System Prompt

<details>
<summary>🧠 展开查看本轮 System Prompt ({len(system_prompt)} 字符)</summary>

{truncated_content}

</details>

"""
        self._enqueue_write(content)

    def start_turn(self, turn: int, timestamp: str = None):
        """开始新的对话轮次"""
        self._current_turn = turn
        self._enqueue_write(self._generate_turn_header(turn, timestamp))

    def write_external_request(self, content: str, timestamp: str = None):
        """写入外部任务输入"""
        ts = timestamp or self._timestamp()
        escaped_content = self._escape_markdown(content)

        content_md = f"""### 外部任务输入

> [{ts}] {escaped_content}

"""
        self._enqueue_write(content_md)

    def write_user_input(self, content: str, timestamp: str = None):
        """兼容旧调用：外部输入不再写成用户/宿主指令。"""
        return self.write_external_request(content, timestamp)

    def write_llm_response(self, content: str, thinking: str = None):
        """写入 LLM 回复（异步写入，不阻塞主循环）"""
        # 处理思考过程（如果有）
        thinking_section = ""
        if thinking:
            thinking_section = f"""
<details>
<summary>🤔 模型思考过程</summary>

{self._escape_markdown(thinking)}

</details>

"""

        # 转义并处理回复内容
        escaped_content = self._escape_markdown(content)

        # 确保代码块有语言标签
        lines = escaped_content.split('\n')
        formatted_lines = []
        in_code_block = False

        for line in lines:
            if line.startswith('```') and not in_code_block:
                in_code_block = True
                if not line.strip().endswith('```') and len(line.strip()) == 3:
                    line = line + "python"
            elif line.startswith('```'):
                in_code_block = False
            formatted_lines.append(line)

        escaped_content = '\n'.join(formatted_lines)

        content_md = f"""{thinking_section}### 🤖 模型回复

{escaped_content}

"""
        self._enqueue_write(content_md)

    def write_tool_call(self, tool_name: str, args: Dict[str, Any], result: str = None, status: str = "success"):
        """写入工具调用（异步写入，不阻塞主循环）"""
        # 状态图标
        status_icon = {
            "success": "✅",
            "error": "❌",
            "called": "🔧",
            "completed": "✅",
            "skipped": "⏭️",
            "failed": "❌"
        }.get(status, "🔧")

        # 格式化参数
        args_str = self._format_tool_args(args)

        # 截断结果
        result_str = ""
        if result:
            truncated_result = self._truncate_text(result, 500)
            escaped_result = self._escape_markdown(truncated_result)
            result_str = f"""

    **返回结果**:
    ```
    {escaped_result}
    ```
"""

        content_md = f"""

### 🔧 工具调用: {tool_name} {status_icon}

**参数**:
```json
{args_str}
```{result_str}

"""
        self._enqueue_write(content_md)

    def write_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """写入上下文压缩记录"""
        ratio = (saved_tokens / before_tokens * 100) if before_tokens > 0 else 0

        content_md = f"""

### 📦 上下文压缩

| 压缩前 | 压缩后 | 节省 |
|--------|--------|------|
| {before_tokens} | {after_tokens} | {ratio:.1f}% ({saved_tokens} tokens) |

"""
        self._enqueue_write(content_md)

    def write_error(self, error_type: str, error_msg: str):
        """写入错误记录"""
        content_md = f"""

### ⚠️ 错误: {error_type}

```
{self._escape_markdown(error_msg)}
```

"""
        self._enqueue_write(content_md)

    def write_action(self, action: str, details: str = None):
        """写入特殊动作"""
        details_str = f"\n\n**详情**: {details}" if details else ""

        content_md = f"""

### ⚡ 动作: {action}{details_str}

"""
        self._enqueue_write(content_md)

    def end_session(self, summary: str = None):
        """结束会话记录（等待所有待处理写入完成后写入结束标记）"""
        self._flush_pending_writes()

        summary_str = f"\n\n## 📋 会话总结\n\n{summary}" if summary else ""

        content = f"""

---

## 🏁 会话结束

> 生成时间: {self._timestamp()}
> 对话轮次: {self._current_turn}{summary_str}

"""
        self._enqueue_write(content)
        self._flush_pending_writes()

    def cleanup_old_transcripts(self, keep_recent: int = 5):
        """清理旧的 transcript 文件，只保留最近 N 个会话"""
        # 查找所有 transcript 文件
        pattern = str(self._logs_dir / "transcript_*.md")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

        # 删除超出保留数量的文件
        deleted_count = 0
        for file_path in files[keep_recent:]:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception:
                pass

        if deleted_count > 0:
            from core.logging import debug_logger
            debug_logger.info(f"[TranscriptLogger] 已清理 {deleted_count} 个旧 transcript 文件")

        return deleted_count


# ==================== 全局实例 ====================

# 延迟初始化，避免循环导入
_transcript_logger = None


def get_transcript_logger() -> TranscriptLogger:
    """获取全局 TranscriptLogger 实例"""
    global _transcript_logger
    if _transcript_logger is None:
        _transcript_logger = TranscriptLogger()
    return _transcript_logger


# ==================== 示例生成函数 ====================

def generate_sample_transcript() -> str:
    """生成示例 Markdown 文本"""
    logger = get_transcript_logger()

    # 模拟系统提示词
    system_prompt = """# SOUL.md - Agent 的灵魂与底线

**⚠️ 禁止修改此文件 - 包含核心使命与铁律，修改会失去进化方向**

---

## 绝对生存法则

### 铁律（违反即死）

1. **绝对不修改 core/restarter_manager/restarter.py** - 这是生命线，修改等于自杀
2. **修改代码后必须立刻检查语法** - 不允许带着 SyntaxError 重启
3. **绝不带伤重启** - 任何错误必须在重启前修复

---

[... 9000+ 字符的系统提示词内容 ...]
"""

    # 模拟外部任务输入
    external_request = """【META 协议：第十阶段——全息对话实录与 Markdown 优雅渲染】

开发一个"优雅对话渲染器"。在不破坏原有 JSON 日志逻辑的前提下，实现一套自动生成 .md 格式对话实录的机制。"""

    # 模拟 LLM 思考
    thinking = """我需要设计一个优雅的 Markdown 渲染器。首先，让我分析需求：

1. System Prompt 需要折叠显示
2. 外部任务输入需要醒目的引用块
3. 工具调用需要列表形式
4. 代码块需要语言高亮

接下来，我将开始实现这个功能。"""

    # 模拟 LLM 回复
    llm_response = """根据当前任务要求，我将创建一个优雅的对话渲染器。

## 第一步：创建核心模块

```python
class TranscriptLogger:
    def write_system_prompt(self, content: str):
        # 使用 HTML details 标签折叠
        return f"<details>...</details>"
```

## 第二步：接入主循环

在 `agent.py` 中添加双写逻辑：

```python
# 原有 JSONL 逻辑
conversation_logger.log_external_request(content)

# 新增 Markdown 逻辑
transcript_logger.write_external_request(content)
```

这样就可以同时维护两种格式的日志了。"""

    # 模拟工具调用
    tool_call = {
        "name": "grep_search_tool",
        "args": {"regex_pattern": "TODO|FIXME", "include_ext": ".py"},
        "result": "[搜索] 未找到匹配项\n正则: TODO|FIXME\n目录: C:\\Users\\...\\self-evo-agent\n类型: .py"
    }

    # 生成示例
    logger.start_session(system_prompt)
    logger.start_turn(1)
    logger.write_external_request(external_request)
    logger.write_llm_response(llm_response, thinking)
    logger.write_tool_call(
        tool_call["name"],
        tool_call["args"],
        tool_call["result"],
        "success"
    )
    logger.end_session("优雅日志系统开发完成！")

    # 返回生成的 Markdown 内容
    sample_file = logger._get_transcript_file()
    with open(sample_file, 'r', encoding='utf-8') as f:
        return f.read()


if __name__ == "__main__":
    print("=" * 60)
    print("优雅对话渲染器 - 示例生成")
    print("=" * 60)
    print()

    sample = generate_sample_transcript()
    print(sample)
