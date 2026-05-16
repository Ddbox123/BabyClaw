#!/usr/bin/env python3
"""
全局搜索工具 - 模拟 IDE 的全局正则检索

提供类似 Cursor/Aider 的全局代码搜索能力，支持：
1. 正则表达式全文搜索
2. 文件类型过滤
3. 大文件智能处理
4. 匹配上下文展示
"""

import re
import os
from pathlib import Path
from typing import Optional, List, Tuple, Dict

# ============================================================================
# 配置常量 - 从配置文件加载
# ============================================================================


def _load_search_defaults() -> dict:
    """从配置加载默认常量"""
    try:
        from config import get_config
        cfg = get_config()
        return {
            "MAX_FILE_SIZE": cfg.tools.search.max_file_size,
            "MAX_MATCHES_PER_FILE": cfg.tools.search.max_matches_per_file,
            "MAX_CONTEXT_LINES": cfg.tools.search.context_lines,
            "SKIP_DIRS": set(cfg.tools.search.skip_directories),
            "SKIP_EXTENSIONS": set(cfg.tools.search.skip_extensions),
            "INCLUDE_EXTENSIONS": set(cfg.tools.search.include_extensions),
        }
    except Exception:
        return {}


_search_defaults = _load_search_defaults()

# 搜索配置
MAX_FILE_SIZE = _search_defaults.get("MAX_FILE_SIZE", 10 * 1024 * 1024)
# 每个文件最大匹配数（强制上限50，防止单文件上下文爆炸）
MAX_MATCHES_PER_FILE = min(_search_defaults.get("MAX_MATCHES_PER_FILE", 100), 50)
MAX_CONTEXT_LINES = _search_defaults.get("MAX_CONTEXT_LINES", 3)
SKIP_DIRS = _search_defaults.get("SKIP_DIRS", {
    '__pycache__', '.git', '.svn', '.hg', 'node_modules',
    '.venv', 'venv', 'env', '.env', '.idea', '.vscode',
    'dist', 'build', '.tox', '.pytest_cache', '.mypy_cache',
    'site-packages', 'egg-info', '.eggs'
})
SKIP_EXTENSIONS = _search_defaults.get("SKIP_EXTENSIONS", {'.exe', '.dll', '.so', '.dylib', '.pyc', '.pyo', '.pyd'})
INCLUDE_EXTENSIONS = _search_defaults.get("INCLUDE_EXTENSIONS", {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.md', '.json', '.yaml', '.yml', '.toml', '.txt', '.html', '.css', '.xml', '.sh', '.bat', '.ps1'
})

EXTENSION_FAMILIES = {
    ".js": {".js", ".jsx"},
    ".ts": {".ts", ".tsx"},
}


def _normalize_path(file_path: str) -> Path:
    """规范化文件路径"""
    return Path(file_path).resolve()


def _should_skip_path(path: Path) -> bool:
    """检查是否应该跳过该路径"""
    parts = path.parts
    for skip_dir in SKIP_DIRS:
        if skip_dir in parts:
            return True
    return False


def _should_process_file(file_path: Path) -> bool:
    """检查是否应该处理该文件"""
    if not file_path.is_file():
        return False
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    try:
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _resolve_extensions(include_ext: str) -> set[str]:
    """把公开扩展名参数解析为实际扩展集合。"""
    if include_ext == "*":
        return INCLUDE_EXTENSIONS
    if include_ext.startswith("."):
        normalized = include_ext.lower()
    else:
        normalized = f".{include_ext.lstrip('.')}".lower()
    return EXTENSION_FAMILIES.get(normalized, {normalized})


def _looks_like_redos_pattern(pattern: str) -> bool:
    """轻量检测常见 ReDoS 形态，避免高危嵌套量词。"""
    if not pattern:
        return False
    heuristics = [
        r"\([^)]*[+*][^)]*\)[+*?]",   # (a+)+ / (.*)* / (.+)?
        r"\([^)]*\{[^}]+\}[^)]*\)[+*?]",  # (a{1,3})+
    ]
    return any(re.search(rule, pattern) for rule in heuristics)


def grep_search_tool(
    regex_pattern: str = "",
    include_ext: str = ".py",
    search_dir: str = ".",
    case_sensitive: bool = True,
    max_results: int = None,
    context_lines: Optional[int] = None,
    recursive: bool = True,
    max_output_chars: int = 8000
) -> str:
    """
    全局正则表达式搜索

    Args:
        regex_pattern: 正则表达式模式
        include_ext: 要搜索的文件扩展名（如 ".py", ".js", "*" 表示所有）
        search_dir: 搜索的根目录
        case_sensitive: 是否区分大小写
        max_results: 最大返回结果数（默认从配置读取，最高50）
        context_lines: 匹配前后展示的上下文行数；None 表示使用默认配置
        recursive: 兼容参数；当前实现默认递归搜索
        max_output_chars: 最大输出字符数，默认8000，防止上下文爆炸

    Returns:
        JSON 格式的搜索结果，包含文件路径、行号、匹配行内容
    """
    if max_results is None:
        max_results = _search_defaults.get("max_results", 50)
    # 强制上限，防止配置被改大导致上下文爆炸
    max_results = min(max_results, 50)
    effective_context_lines = MAX_CONTEXT_LINES if context_lines is None else max(0, int(context_lines))

    if not regex_pattern:
        import json
        return json.dumps({"status": "error", "code": "EMPTY_PATTERN", "message": "正则表达式不能为空"})
    if _looks_like_redos_pattern(regex_pattern):
        return "[搜索] 错误: 正则表达式存在潜在高复杂度嵌套量词，已拒绝执行"

    search_dir_path = _normalize_path(search_dir)
    
    # 处理文件路径的情况：如果是文件而非目录，直接搜索该文件
    is_single_file = False
    target_filename = None
    
    if search_dir_path.exists() and search_dir_path.is_file():
        # 用户传入的是文件路径，改为只搜索该文件
        is_single_file = True
        # 先保存文件名，再改变目录路径
        target_filename = search_dir_path.name  # agent.py
        search_dir_path = search_dir_path.parent  # 改为搜索其父目录
    
    if not search_dir_path.exists():
        return f"[搜索] 错误: 目录不存在 - {search_dir_path}"

    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(regex_pattern, flags)
    except re.error as e:
        return f"[搜索] 错误: 无效的正则表达式 - {e}"

    # 确定要搜索的扩展名
    extensions = _resolve_extensions(include_ext)

    results: List[Tuple[str, int, str, List[str]]] = []  # (文件路径, 行号, 匹配行, 上下文)

    try:
        for root, dirs, files in os.walk(search_dir_path):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            root_path = Path(root)

            for filename in files:
                file_path = root_path / filename

                if not _should_process_file(file_path):
                    continue

                # 检查扩展名
                if extensions and file_path.suffix.lower() not in extensions:
                    continue
                
                # 如果是单个文件模式，只处理目标文件
                if target_filename and filename != target_filename:
                    continue

                # 跳过包含 skip 路径的文件
                if _should_skip_path(file_path):
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                except Exception:
                    continue

                match_count = 0
                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        # 收集上下文
                        context_start = max(0, line_num - 1 - effective_context_lines)
                        context_end = min(len(lines), line_num + effective_context_lines)
                        context = [lines[i].rstrip() for i in range(context_start, context_end)]

                        results.append((
                            str(file_path),
                            line_num,
                            line.rstrip(),
                            context
                        ))
                        match_count += 1

                        if match_count >= MAX_MATCHES_PER_FILE:
                            break

                        if len(results) >= max_results:
                            break

                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break
            
            # 如果是单个文件模式，找到目标后就停止遍历
            if target_filename and results:
                break

    except Exception as e:
        return f"[搜索] 错误: 遍历目录时出错 - {e}"

    # 格式化输出
    if not results:
        # 如果是单个文件模式，显示正确的文件名
        display_dir = f"{search_dir_path}/{target_filename}" if is_single_file else str(search_dir_path)
        return f"[搜索] 未找到匹配项\n正则: {regex_pattern}\n目录: {display_dir}\n类型: {include_ext}"

    grouped: Dict[str, List[Tuple[int, str, List[str]]]] = {}
    for file_path, line_num, match_line, context in results:
        grouped.setdefault(file_path, []).append((line_num, match_line, context))

    output_lines = [
        f"[搜索] 正则: {regex_pattern}",
        f"[搜索] 目录: {search_dir_path if not is_single_file else search_dir_path / target_filename}",
        f"[搜索] 类型: {include_ext}",
        f"[搜索] 找到 {len(results)} 个匹配，分布在 {len(grouped)} 个文件",
        "[搜索] 阅读策略: 先看文件分组与首个命中，再按需用 read_file_tool / get_code_entity_tool 精读",
        "",
        "[搜索摘要]",
    ]

    for file_path, entries in grouped.items():
        line_numbers = [str(item[0]) for item in entries[:3]]
        more = f" ... +{len(entries) - 3}" if len(entries) > 3 else ""
        output_lines.append(
            f"- {file_path} | 命中 {len(entries)} 处 | 行 {', '.join(line_numbers)}{more}"
        )

    output_lines.extend(["", "=" * 80, "[搜索预览]"])

    max_output_chars = max(1200, int(max_output_chars or 8000))
    preview_file_limit = 3
    preview_match_limit = 6

    current_file = None
    chars_so_far = 0
    truncated = False
    preview_blocks = 0
    preview_matches = 0
    for file_path, line_num, match_line, context in results:
        if file_path != current_file:
            if preview_blocks >= preview_file_limit:
                truncated = True
                break
            current_file = file_path
            output_lines.append(f"\n📁 {file_path}")
            output_lines.append("-" * 80)
            preview_blocks += 1

        # 上下文行
        for ctx_idx, ctx_line in enumerate(context):
            if ctx_line == match_line:
                line = f"  → 第 {line_num} 行 | {ctx_line}"
            else:
                line = f"    第 {line_num - effective_context_lines + ctx_idx} 行 | {ctx_line}"
            output_lines.append(line)
            chars_so_far += len(line) + 1
            if chars_so_far > max_output_chars:
                truncated = True
                break

        if truncated:
            break
        preview_matches += 1
        if preview_matches >= preview_match_limit:
            truncated = True
            break

    if truncated:
        output_lines.append(f"\n... (搜索预览已截断，仅显示前 {preview_blocks} 个预览块)")
        if grouped:
            first_file = next(iter(grouped.keys()))
            output_lines.append(f'[续读] read_file_tool(file_path="{first_file}", offset=0, max_lines=80)')
        else:
            output_lines.append("[续读] 缩小 regex_pattern / search_dir，或对目标文件使用 read_file_tool 分页读取")
    else:
        output_lines.append("\n[续读] 若需要完整上下文，请对上面命中的目标文件继续分页读取")

    output_lines.append("\n" + "=" * 80)
    output_lines.append(f"[搜索完成] 共 {len(results)} 个匹配")

    return '\n'.join(output_lines)


def find_function_calls_tool(
    function_name: str,
    search_dir: str = ".",
    include_ext: str = ".py"
) -> str:
    """
    查找特定函数的所有调用位置

    Args:
        function_name: 函数名
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有调用位置的列表
    """
    pattern = rf'\b{re.escape(function_name)}\s*\('
    return grep_search_tool(pattern, include_ext, search_dir)


def find_definitions_tool(
    symbol_name: str,
    search_dir: str = ".",
    include_ext: str = ".py"
) -> str:
    """
    查找符号（函数、类、变量）的定义位置

    Args:
        symbol_name: 符号名
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有定义位置的列表
    """
    # 匹配 def func_name 或 class ClassName 或 var_name =
    patterns = [
        rf'\bdef\s+{re.escape(symbol_name)}\s*\(',
        rf'\bclass\s+{re.escape(symbol_name)}\s*[\(:]',
        rf'\b{re.escape(symbol_name)}\s*=\s*(?!=)',
    ]
    combined_pattern = '|'.join(patterns)
    return grep_search_tool(combined_pattern, include_ext, search_dir, context_lines=10)


def search_imports_tool(
    module_or_name: str = "",
    module_name: Optional[str] = None,
    search_dir: str = ".",
    include_ext: str = "*"
) -> str:
    """
    查找特定的 import 语句

    Args:
        module_or_name: 模块名或导入的名称
        module_name: 兼容旧调用的别名；若提供则优先使用
        search_dir: 搜索目录
        include_ext: 文件类型

    Returns:
        所有 import 该模块/名称的位置
    """
    # 兼容旧的 positional 调用：search_imports_tool(module_name, search_dir)
    if (
        isinstance(module_name, str)
        and module_name
        and search_dir == "."
        and include_ext == "*"
        and not module_name.startswith(".")
        and ("\\" in module_name or "/" in module_name)
    ):
        search_dir = module_name
        module_name = None

    target = module_name or module_or_name
    if not target:
        return "[搜索] 错误: 模块名不能为空"

    patterns = [
        rf'^import\s+.*{re.escape(target)}',
        rf'^from\s+.*{re.escape(target)}\s+import',
    ]
    combined_pattern = '|'.join(patterns)
    return grep_search_tool(combined_pattern, include_ext, search_dir)


def search_and_read_tool(
    query: str = "",
    search_pattern: Optional[str] = None,
    context_lines: int = 5,
    include_ext: str = ".py",
    search_dir: str = ".",
    max_matches: int = 50,
    max_results: Optional[int] = None
) -> str:
    """
    搜索并读取 - 一步到位的代码检索

    在项目中全局搜索 query，对于每个匹配项，自动携带上下文行返回代码。
    将原来需要 2-3 轮 LLM 交互的操作（grep -> read -> 读取更多上下文）压缩为 1 轮。

    Args:
        query: 搜索关键词（支持正则表达式）
        search_pattern: 兼容旧调用的别名；若提供则优先使用
        context_lines: 每个匹配项返回的上下文行数（前后各 context_lines 行）
        include_ext: 文件类型过滤
        search_dir: 搜索目录
        max_matches: 最大匹配数（超过则截断）
        max_results: 兼容旧调用的别名；若提供则优先使用

    Returns:
        格式化的搜索结果，每个匹配包含完整的上下文代码块
    """
    # 兼容更老的 positional 调用：search_and_read_tool(query, include_ext, search_dir)
    if (
        isinstance(search_pattern, str)
        and search_pattern.startswith(".")
        and isinstance(context_lines, str)
        and include_ext == ".py"
        and search_dir == "."
    ):
        search_dir = context_lines
        include_ext = search_pattern
        search_pattern = None
        context_lines = 5

    # 兼容旧的 positional 调用：search_and_read_tool(query, include_ext, search_dir)
    if isinstance(context_lines, str) and isinstance(include_ext, str) and search_dir == ".":
        search_dir = include_ext
        include_ext = context_lines
        context_lines = 5

    target_query = search_pattern or query
    if not target_query:
        return "[搜索读取] 错误: 查询不能为空"
    effective_max_matches = int(max_results) if max_results is not None else int(max_matches)

    search_dir_path = _normalize_path(search_dir)
    if not search_dir_path.exists():
        return f"[搜索读取] 错误: 目录不存在 - {search_dir_path}"

    # 编译正则
    try:
        pattern = re.compile(target_query)
    except re.error as e:
        return f"[搜索读取] 错误: 无效的正则表达式 - {e}"

    # 确定扩展名
    extensions = _resolve_extensions(include_ext)

    # 收集所有匹配
    all_matches = []
    total_collected_matches = 0

    try:
        for root, dirs, files in os.walk(search_dir_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            root_path = Path(root)

            for filename in files:
                file_path = root_path / filename

                if not _should_process_file(file_path):
                    continue
                if file_path.suffix.lower() not in extensions:
                    continue
                if _should_skip_path(file_path):
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                except Exception:
                    continue

                file_matches = []
                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        # 计算上下文范围
                        start_ctx = max(0, line_num - 1 - context_lines)
                        end_ctx = min(len(lines), line_num + context_lines)

                        # 提取上下文代码块
                        context_block = []
                        for i in range(start_ctx, end_ctx):
                            is_match_line = (i == line_num - 1)
                            marker = ">>>" if is_match_line else "   "
                            context_block.append((i + 1, marker, lines[i].rstrip()))

                        file_matches.append({
                            'line': line_num,
                            'context': context_block,
                            'match_line': line.rstrip(),
                        })
                        total_collected_matches += 1
                        if total_collected_matches >= effective_max_matches:
                            break

                if file_matches:
                    all_matches.append({
                        'file': str(file_path),
                        'matches': file_matches,
                    })

                if total_collected_matches >= effective_max_matches:
                    break

            if total_collected_matches >= effective_max_matches:
                break

    except Exception as e:
        return f"[搜索读取] 错误: 遍历目录时出错 - {e}"

    if not all_matches:
        return (
            f"[搜索读取] 未找到匹配项\n"
            f"查询: {query}\n"
            f"目录: {search_dir_path}\n"
            f"类型: {include_ext}"
        )

    # 格式化输出
    total_matches = sum(len(f['matches']) for f in all_matches)

    output = [
        f"[搜索读取] 查询: {query}",
        f"[搜索读取] 目录: {search_dir_path}",
        f"[搜索读取] 类型: {include_ext}",
        f"[搜索读取] 找到 {total_matches} 处匹配，分布在 {len(all_matches)} 个文件中\n",
        "=" * 80,
    ]

    for file_idx, file_data in enumerate(all_matches, 1):
        output.append(f"\n{'=' * 40}")
        output.append(f"📁 {file_data['file']}")
        output.append(f"{'=' * 40}")

        for match_idx, match in enumerate(file_data['matches'], 1):
            output.append(f"\n--- 匹配 {match_idx} (第 {match['line']} 行) ---")

            # 收集代码块
            code_lines = []
            for line_num, marker, content in match['context']:
                code_lines.append(f"{marker} {line_num:4d} | {content}")

            output.append("```python")
            output.extend(code_lines)
            output.append("```")

    output.append("\n" + "=" * 80)
    output.append(f"[搜索读取完成] 共 {total_matches} 处匹配")

    return '\n'.join(output)
