# -*- coding: utf-8 -*-
"""
代码库结构地图 — AST 扫描 + 增量更新 + 变更日志

职责：
- 扫描 tools/、core/、tests/、config/ 及根目录 .py 文件
- 对每个文件调用 AST 获取类/函数骨架
- 写入 workspace/prompts/CODEBASE_MAP.md 供提示词章节读取
- 支持增量更新：单文件变更时只更新对应条目
- 维护最近变更日志（最多 10 条）
"""

from __future__ import annotations

import os
import re
import hashlib
import threading
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from core.logging import debug_logger

_SCAN_DIRS = ["tools", "core", "tests", "config"]

_EXCLUDE_FILES = {
    "__pycache__",
    "__init__.py",
    "conftest.py",
    "__init__.cpython",
}

_CACHE_TTL_HOURS = 24

# ── 变更日志（内存中，最多保留 10 条）──────────────────────────────
_change_log: List[Dict[str, str]] = []
_change_log_lock = threading.Lock()


def _record_change(filepath: str, action: str = "modified"):
    """记录一次文件变更（线程安全）。"""
    global _change_log
    with _change_log_lock:
        _change_log.insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "file": filepath,
            "action": action,
        })
        if len(_change_log) > 10:
            _change_log.pop()


def _get_change_log_entries() -> List[Dict[str, str]]:
    """获取变更日志快照。"""
    with _change_log_lock:
        return list(_change_log)


# ═══════════════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_project_root() -> Path:
    p = Path(__file__).parent.parent.parent.resolve()
    if (p / "agent.py").exists():
        return p
    import sys
    for sp in sys.path:
        candidate = os.path.join(sp, "agent.py")
        if os.path.exists(candidate):
            return Path(sp).resolve()
    return p


def _get_prompts_dir() -> Path:
    project_root = _resolve_project_root()
    prompts_dir = project_root / "workspace" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def _get_codebase_map_path() -> Path:
    return _get_prompts_dir() / "CODEBASE_MAP.md"


# ═══════════════════════════════════════════════════════════════════════════════
# AST 扫描
# ═══════════════════════════════════════════════════════════════════════════════


def _scan_file(file_path: Path) -> Optional[dict]:
    """Parse a .py file: docstring, project-internal imports, line count, test counts."""
    try:
        import ast
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(file_path))

        doc = ast.get_docstring(tree)
        docstring = doc.split("\n")[0].strip() if doc else ""

        _INTERNAL = ("core", "tools", "config")
        imports: List[str] = []
        n_classes = 0
        n_functions = 0
        n_methods = 0
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                n_classes += 1
                n_methods += sum(1 for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n_functions += 1
            # Collect imports (same pass)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(p) for p in _INTERNAL):
                        imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(node.module.startswith(p) for p in _INTERNAL):
                    imports.append(node.module)

        return {
            "line_count": len(source.splitlines()),
            "docstring": docstring,
            "imports": list(dict.fromkeys(imports)),
            "n_classes": n_classes,
            "n_tests": n_methods + n_functions,
        }
    except Exception:
        return None


def _collect_python_files(project_root: Path) -> List[Path]:
    """收集所有需要扫描的 .py 文件（含根目录）。"""
    files: List[Path] = []

    # 根目录 .py 文件
    for fpath in project_root.glob("*.py"):
        if fpath.name not in _EXCLUDE_FILES:
            files.append(fpath)

    # 子目录
    for scan_dir in _SCAN_DIRS:
        dir_path = project_root / scan_dir
        if not dir_path.is_dir():
            continue
        for root, _, filenames in os.walk(dir_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                if fname in _EXCLUDE_FILES:
                    continue
                fpath = Path(root) / fname
                if "__pycache__" in str(fpath):
                    continue
                files.append(fpath)
    return files


def _build_file_entry(fpath: Path, rel_root: Path) -> str:
    """Build a single file's map entry — description and imports only (no class/function listing)."""
    info = _scan_file(fpath)
    rel_path = fpath.relative_to(rel_root).as_posix()
    if info is None:
        return f"**`{rel_path}`**  _(parse failed)_"

    lc = info["line_count"]
    doc = info["docstring"]
    desc = f" — {doc}" if doc else " — _(无描述)_"
    lines = [f"**`{rel_path}`** ({lc}行){desc}"]

    # Test files: show class/test count
    if "tests/" in rel_path or rel_path.startswith("test_"):
        lines.append(f"  {info['n_classes']} test classes, {info['n_tests']} tests")

    return "\n".join(lines)


def _get_agent_py_lines(project_root: Path) -> int:
    """获取 agent.py 当前行数。"""
    agent_py = project_root / "agent.py"
    if agent_py.exists():
        try:
            return len(agent_py.read_text(encoding="utf-8").splitlines())
        except Exception:
            pass
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# 子系统概览（自动发现，非硬编码——新增目录自动出现）
# ═══════════════════════════════════════════════════════════════════════════════

# Risk level heuristics — matches path prefix; first match wins. New dirs default to "safe".
_RISK_RULES = [
    ("core/infrastructure",   "core"),
    ("core/prompt_manager",   "core"),
    ("core/orchestration",    "core"),
    ("core/restarter_manager","core"),
    ("config",                "careful"),
    ("tools",                 "modifiable"),
]

# Human-readable labels for known directories. Unknown dirs show their relative path.
_SUBSYSTEM_LABELS = {
    "core/infrastructure":    "基础设施 (状态/事件/安全)",
    "core/prompt_manager":    "提示词引擎 (组装/缓存/代码地图)",
    "core/orchestration":     "任务编排 (TaskManager)",
    "core/restarter_manager": "自我重启守护进程",
    "core/logging":           "日志系统",
    "core/ui":                "CLI 交互界面",
    "core/pet_system":        "宠物系统 (10 大子系统)",
    "tools":                  "Agent 工具集",
    "config":                 "配置系统 (Pydantic+TOML)",
    "tests":                  "测试套件",
}


def _classify_risk(rel_path: str) -> str:
    for prefix, risk in _RISK_RULES:
        if rel_path.startswith(prefix):
            return risk
    return "safe"


def _build_overview(project_root: Path, by_parent, root_files) -> str:
    """Auto-discover subsystems from actual directory structure (not hardcoded)."""
    # Aggregate all parent dirs we know about
    all_by_parent = dict(by_parent)
    all_by_parent[project_root] = root_files

    # Build (rel_prefix, count, risk) from what actually exists on disk
    seen: Dict[str, tuple] = {}  # rel_prefix -> (count, risk)
    for parent, flist in all_by_parent.items():
        try:
            rel = parent.relative_to(project_root).as_posix()
        except ValueError:
            continue
        if rel == ".":
            continue  # root files handled separately in the map
        if "/" not in rel:
            # Top-level scan dir (tools, tests, config, core)
            prefix = rel
        else:
            # Subdirectory under a scan dir (core/infrastructure, core/pet_system/subsystems, etc.)
            # Roll up into the first-level subdir for the overview
            prefix = "/".join(rel.split("/")[:2]) if rel.startswith("core/") else rel.split("/")[0]

        if prefix not in seen:
            seen[prefix] = (0, _classify_risk(rel))
        count, risk = seen[prefix]
        seen[prefix] = (count + len(flist), risk)

    lines = ["## 子系统概览", "", "| 子系统 | 路径 | 文件 | 风险 |", "|--------|------|------|------|"]
    # Sort: core dirs first, then by risk level, then alphabetically
    _risk_order = {"core": 0, "careful": 1, "modifiable": 2, "safe": 3}
    for prefix, (count, risk) in sorted(seen.items(), key=lambda x: (_risk_order.get(x[1][1], 4), x[0])):
        label = _SUBSYSTEM_LABELS.get(prefix, prefix)
        lines.append(f"| {label} | `{prefix}/` | {count} | `{risk}` |")

    lines.append("")
    return "\n".join(lines)


def _build_reverse_deps(files: List[Path], project_root: Path) -> str:
    """Compute reverse dependency ranking: which project modules are imported by the most files."""
    imported_by: Dict[str, List[str]] = defaultdict(list)
    for fpath in files:
        info = _scan_file(fpath)
        if info is None:
            continue
        rel = fpath.relative_to(project_root).as_posix()
        for imp in info["imports"]:
            imported_by[imp].append(rel)

    ranked = sorted(imported_by.items(), key=lambda x: -len(x[1]))[:10]
    if not ranked:
        return ""

    lines = ["## 核心依赖 (被依赖最多的模块 Top-10)", ""]
    for module, deps in ranked:
        n = len(deps)
        # Resolve module name to real path (handle packages vs modules)
        parts = module.split(".")
        as_file = project_root / (module.replace(".", "/") + ".py")
        as_pkg = project_root / (module.replace(".", "/"))
        if as_file.exists():
            target = module.replace(".", "/") + ".py"
        elif as_pkg.is_dir():
            target = module.replace(".", "/") + "/"
        else:
            target = module  # fallback: show as dotted name
        dep_sample = ", ".join(deps[:3])
        if len(deps) > 3:
            dep_sample += " …"
        lines.append(f"- `{target}` ← {n} 文件 ({dep_sample})")

    return "\n".join(lines) + "\n"


def _build_test_coverage(files: List[Path], project_root: Path) -> str:
    """Check which source files have corresponding test files. Show summary + top critical uncovered."""
    tests_dir = project_root / "tests"
    if not tests_dir.is_dir():
        return ""

    uncovered: List[str] = []
    for fpath in files:
        rel = fpath.relative_to(project_root).as_posix()
        if rel.startswith("tests/") or rel.endswith("/__init__.py"):
            continue
        stem = Path(rel).stem
        test_file = tests_dir / f"test_{stem}.py"
        if not test_file.exists():
            alt_names = [
                tests_dir / f"test_{stem.replace('_', '')}.py",
                tests_dir / f"test_{stem.rsplit('_', 1)[-1]}.py",
            ]
            if not any(alt.exists() for alt in alt_names):
                uncovered.append(rel)

    if not uncovered:
        return "## 测试覆盖 ✓ — 所有源文件均有对应测试\n"

    total_source = len([f for f in files if not f.relative_to(project_root).as_posix().startswith("tests/")])
    covered = total_source - len(uncovered)
    pct = int(covered / total_source * 100) if total_source else 0

    lines = ["## 测试覆盖", ""]
    lines.append(f"覆盖率: {pct}% ({covered}/{total_source}) | 未覆盖: {len(uncovered)} 个模块")
    lines.append("")

    # 仅列出关键模块（core/ 下的核心文件）
    critical = [u for u in uncovered if u.startswith("core/infrastructure/") or u == "agent.py"]
    other_core = [u for u in uncovered if u.startswith("core/") and u not in critical]
    rest = [u for u in uncovered if u not in critical and u not in other_core]

    if critical:
        lines.append("**关键未覆盖**:")
        for rel in critical:
            lines.append(f"- `{rel}`")
    if other_core:
        lines.append(f"\n其他 core/ 未覆盖 ({len(other_core)}): `{', '.join(other_core)}`")
    if rest:
        lines.append(f"其余 ({len(rest)}): `{', '.join(rest)}`")

    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════════════════
# 核心：全量构建
# ═══════════════════════════════════════════════════════════════════════════════


def scan_and_build_codebase_map(project_root: Optional[Path] = None, force: bool = False) -> str:
    """扫描代码库，生成/更新 CODEBASE_MAP.md。

    Args:
        project_root: 项目根目录（默认自动推断）
        force: True 时强制重新扫描

    Returns:
        生成的地图内容（Markdown 字符串）
    """
    if project_root is None:
        project_root = _resolve_project_root()

    files = _collect_python_files(project_root)
    total_files = len(files)

    # 按目录分组，目录内按文件名排序
    by_parent: defaultdict[Path, List[Path]] = defaultdict(list)
    root_files: List[Path] = []

    for f in files:
        parent = f.parent
        if parent == project_root:
            root_files.append(f)
        else:
            by_parent[parent].append(f)
    for d in by_parent:
        by_parent[d].sort(key=lambda p: p.name)
    root_files.sort(key=lambda p: p.name)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agent_lines = _get_agent_py_lines(project_root)
    changes = _get_change_log_entries()

    lines: List[str] = [
        "---",
        "name: CODEBASE_MAP",
        "priority: 30",
        "description: 代码库结构地图，文件修改后自动更新",
        f"last_updated: {timestamp}",
        f"agent_py_lines: {agent_lines}",
        f"total_files: {total_files}",
        "---",
        "",
        "# 代码库结构地图",
        "",
        f"_更新: {timestamp} | agent.py: {agent_lines}行 | {total_files}文件_",
        "",
    ]

    # ── 最近变更 ──
    if changes:
        lines.append("## 最近变更")
        lines.append("")
        for c in changes[:8]:
            lines.append(f"- `{c['time']}` {c['action']}: `{c['file']}`")
        lines.append("")

    # ── 子系统概览 ──
    lines.append(_build_overview(project_root, by_parent, root_files))

    # ── 核心依赖 ──
    rev_deps = _build_reverse_deps(files, project_root)
    if rev_deps:
        lines.append(rev_deps)

    # ── 测试覆盖 ──
    coverage = _build_test_coverage(files, project_root)
    if coverage:
        lines.append(coverage)

    lines.append("---")
    lines.append("")

    # ── 根目录文件 ──
    if root_files:
        lines.append("## 📄 根目录")
        lines.append("")
        for fpath in root_files:
            lines.append(_build_file_entry(fpath, project_root))
            lines.append("")
        lines.append("---")
        lines.append("")

    # ── 按扫描目录顺序输出（支持嵌套子目录）──
    for scan_dir in _SCAN_DIRS:
        dir_path = project_root / scan_dir
        if not dir_path.is_dir():
            continue

        # 收集该扫描目录下所有 by_parent 条目
        sub_groups: Dict[str, List[Path]] = {}
        for parent, flist in by_parent.items():
            try:
                parent_rel = parent.relative_to(dir_path)
            except ValueError:
                continue
            key = "" if parent_rel == Path(".") else parent_rel.as_posix()
            sub_groups.setdefault(key, []).extend(flist)

        if not sub_groups:
            continue

        label = scan_dir.upper()
        lines.append(f"## 📁 {label}/")
        lines.append("")

        # 直接在该目录下的文件（无子目录）
        root_entries = sorted(sub_groups.pop("", []), key=lambda p: p.name)
        if scan_dir == "tests":
            # 测试目录摘要化：只显示数量和关键统计
            test_count = len(root_entries)
            total_classes = 0
            total_tests = 0
            for fpath in root_entries:
                info = _scan_file(fpath)
                if info:
                    total_classes += info.get("n_classes", 0)
                    total_tests += info.get("n_tests", 0)
            lines.append(f"**{test_count} 个测试文件** — {total_classes} test classes, {total_tests} tests")
            lines.append("")
        else:
            for fpath in root_entries:
                lines.append(_build_file_entry(fpath, project_root))
                lines.append("")

        # 子目录按名称排序
        for subdir in sorted(sub_groups.keys()):
            sub_label = f"{scan_dir}/{subdir}"
            sub_files = sorted(sub_groups[subdir], key=lambda p: p.name)
            # 深层子目录（>1 层）摘要化：只显示文件数量和名称
            if "/" in subdir:
                file_names = ", ".join(f.name for f in sub_files)
                total_lines = sum(_scan_file(f).get("line_count", 0) if _scan_file(f) else 0 for f in sub_files)
                lines.append(f"### 📂 {sub_label}/ — {len(sub_files)} 文件, {total_lines} 行")
                lines.append(f"> `{file_names}`")
                lines.append("")
            else:
                lines.append(f"### 📂 {sub_label}/")
                lines.append("")
                for fpath in sub_files:
                    lines.append(_build_file_entry(fpath, project_root))
                    lines.append("")

        lines.append("---")
        lines.append("")

    content = "\n".join(lines).strip()

    # 写入文件
    map_path = _get_codebase_map_path()
    try:
        map_path.write_text(content, encoding="utf-8")
        debug_logger.info(f"[CodebaseMap] 地图已写入: {map_path}")
    except Exception as e:
        debug_logger.warning(f"[CodebaseMap] 写入失败: {e}")

    # 写入 .meta 文件
    _write_meta(map_path, files, timestamp)

    return content


def _write_meta(map_path: Path, files: List[Path], timestamp: str):
    """写入 .meta 缓存文件。"""
    try:
        meta_path = map_path.with_suffix(".meta")
        file_list_hash = hashlib.md5(
            "|".join(str(f) for f in sorted(files)).encode()
        ).hexdigest()[:8]
        meta_path.write_text(
            f"generated_at={timestamp}\nfile_hash={file_list_hash}\n",
            encoding="utf-8",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 增量更新
# ═══════════════════════════════════════════════════════════════════════════════


def incremental_update_file(filepath: str) -> bool:
    """增量更新单个文件的条目。

    当文件被修改时调用。重新扫描该文件并替换 CODEBASE_MAP.md 中对应条目。
    若文件不存在（已删除），则移除对应条目。

    Args:
        filepath: 相对于项目根目录的文件路径

    Returns:
        True 表示更新成功
    """
    project_root = _resolve_project_root()
    abs_path = project_root / filepath

    _record_change(filepath, "modified")

    # 只处理 .py 文件
    if not filepath.endswith(".py"):
        # 非 .py 文件变更可能导致目录结构变化，触发全量重建
        return _schedule_rebuild()

    map_path = _get_codebase_map_path()
    if not map_path.exists():
        return _schedule_rebuild()

    try:
        existing = map_path.read_text(encoding="utf-8")
    except Exception:
        return _schedule_rebuild()

    # 文件被删除 → 移除条目
    if not abs_path.exists():
        _record_change(filepath, "deleted")
        new_content = _remove_file_entry_from_map(existing, filepath)
        if new_content != existing:
            _update_map_file(map_path, new_content, project_root)
            return True
        return _schedule_rebuild()

    # 文件被修改 → 重建该条目并替换
    new_entry = _build_file_entry(abs_path, project_root)
    new_content = _replace_file_entry_in_map(existing, filepath, new_entry)
    if new_content != existing:
        existing = new_content
    # 始终更新时间戳和变更日志
    _update_map_file(map_path, existing, project_root)
    return True


def incremental_add_file(filepath: str) -> bool:
    """新增文件时更新地图。

    Args:
        filepath: 相对于项目根目录的文件路径
    """
    _record_change(filepath, "added")

    map_path = _get_codebase_map_path()
    if not map_path.exists():
        return _schedule_rebuild()

    # 新文件 → 全量重建以正确处理目录结构
    return _schedule_rebuild()


def _update_map_file(map_path: Path, new_content: str, project_root: Path):
    """更新地图文件内容（同步文件级 front matter 注释）。

    这里的 front matter 只用于文件自描述与缓存元数据，不参与 prompt section
    的运行时注册。
    """
    agent_lines = _get_agent_py_lines(project_root)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 更新 front matter 中的时间戳和行数
    new_content = re.sub(
        r'last_updated: .*',
        f'last_updated: {timestamp}',
        new_content
    )
    new_content = re.sub(
        r'agent_py_lines: \d+',
        f'agent_py_lines: {agent_lines}',
        new_content
    )
    # 更新下方摘要行
    new_content = re.sub(
        r'_更新: .*_',
        f'_更新: {timestamp} | agent.py: {agent_lines}行_',
        new_content
    )

    # 更新变更日志部分
    new_content = _update_change_log_section(new_content)

    try:
        map_path.write_text(new_content, encoding="utf-8")
        debug_logger.info(f"[CodebaseMap] 增量更新完成")
    except Exception as e:
        debug_logger.warning(f"[CodebaseMap] 增量写入失败: {e}")


def _replace_file_entry_in_map(content: str, filepath: str, new_entry: str) -> str:
    """在地图内容中替换单个文件的条目。"""
    escaped = re.escape(filepath)
    # 匹配 `filepath` (NNN行) 开头的行，到下一个空行或 **` 或 ##
    pattern = rf'\*\*`{escaped}`\*\*.*?(?=\n\n|\n\*\*`|\n##|\n---|\Z)'
    replacement = new_entry
    if re.search(pattern, content, re.DOTALL):
        return re.sub(pattern, replacement, content, flags=re.DOTALL)
    # 未找到精确匹配，尝试只匹配文件名
    fname = Path(filepath).name
    pattern2 = rf'\*\*`[^`]*{re.escape(fname)}`\*\*.*?(?=\n\n|\n\*\*`|\n##|\n---|\Z)'
    if re.search(pattern2, content, re.DOTALL):
        return re.sub(pattern2, replacement, content, flags=re.DOTALL)
    return content


def _remove_file_entry_from_map(content: str, filepath: str) -> str:
    """从地图内容中移除文件条目。"""
    escaped = re.escape(filepath)
    pattern = rf'\*\*`{escaped}`\*\*.*?(?=\n\n|\n\*\*`|\n##|\n---|\Z)\n*'
    return re.sub(pattern, '', content, flags=re.DOTALL)


def _update_change_log_section(content: str) -> str:
    """更新地图中的变更日志部分。"""
    changes = _get_change_log_entries()
    if not changes:
        return content

    change_lines = ["## 最近变更", ""]
    for c in changes[:8]:
        change_lines.append(f"- `{c['time']}` {c['action']}: `{c['file']}`")

    new_section = "\n".join(change_lines)

    # 替换现有的变更日志部分
    pattern = r'## 最近变更\n\n(?:- .*\n)*'
    if re.search(pattern, content):
        return re.sub(pattern, new_section + "\n", content)
    # 没有变更日志部分，插入到标题后
    return content.replace(
        "---\n\n",
        "---\n\n" + new_section + "\n\n---\n\n",
        1,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 调度重建
# ═══════════════════════════════════════════════════════════════════════════════

_rebuild_scheduled = False
_rebuild_lock = threading.Lock()
_rebuild_timer: Optional[threading.Timer] = None


def _schedule_rebuild(delay: float = 2.0) -> bool:
    """延迟调度全量重建（防抖：多次调用只触发一次）。"""
    global _rebuild_scheduled, _rebuild_timer
    with _rebuild_lock:
        if _rebuild_timer is not None:
            _rebuild_timer.cancel()
        _rebuild_timer = threading.Timer(delay, _do_rebuild)
        _rebuild_timer.daemon = True
        _rebuild_timer.start()
        _rebuild_scheduled = True
    return True


def _do_rebuild():
    """执行后台全量重建。"""
    try:
        scan_and_build_codebase_map()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 缓存验证
# ═══════════════════════════════════════════════════════════════════════════════


def should_rescan(project_root: Optional[Path] = None) -> bool:
    """检查是否需要重新扫描。

    Returns:
        True = 需要扫描（文件不存在 / 已过期 / 代码有变更）
    """
    if project_root is None:
        project_root = _resolve_project_root()

    map_path = _get_codebase_map_path()
    if not map_path.exists():
        return True

    # 检查 TTL
    try:
        age_seconds = time.time() - map_path.stat().st_mtime
        if age_seconds > _CACHE_TTL_HOURS * 3600:
            return True
    except Exception:
        return True

    # 检查代码文件是否变更
    try:
        meta_path = map_path.with_suffix(".meta")
        if meta_path.exists():
            current_files = _collect_python_files(project_root)
            current_hash = hashlib.md5(
                "|".join(str(f) for f in sorted(current_files)).encode()
            ).hexdigest()[:8]
            meta_content = meta_path.read_text(encoding="utf-8")
            for line in meta_content.splitlines():
                if line.startswith("file_hash="):
                    cached_hash = line.split("=", 1)[1].strip()
                    if current_hash != cached_hash:
                        return True
                    break
    except Exception:
        pass

    return False


def _strip_front_matter(content: str) -> str:
    """剥离 YAML front matter（--- ... ---），保留正文供提示词使用。

    CODEBASE_MAP 文件头不是 section 元信息真源，只是文件级注释。
    """
    if content.startswith("---\n"):
        idx = content.find("\n---\n", 4)
        if idx != -1:
            return content[idx + 5:].lstrip()
    return content


def _extract_markdown_section(content: str, heading: str) -> str:
    """提取指定二级标题及其正文。"""
    pattern = rf"(^## {re.escape(heading)}\n.*?)(?=^## |\Z)"
    match = re.search(pattern, content, flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _get_prompt_runtime_context() -> Tuple[str, str]:
    """读取当前任务相关上下文。"""
    goal = ""
    state_memory = ""
    try:
        from core.prompt_manager.prompt_manager import get_prompt_manager
        pm = get_prompt_manager()
        goal = (pm.get_current_goal() or "").strip()
        state_memory = (pm.state_memory or "").strip()
    except Exception:
        pass
    return goal, state_memory


def _score_file_relevance(fpath: Path, project_root: Path, context_text: str, hot_paths: set[str]) -> int:
    rel = fpath.relative_to(project_root).as_posix()
    score = 0
    if rel in hot_paths:
        score += 10
    for path in hot_paths:
        if rel.startswith(path.rstrip("/")):
            score += 6
    info = _scan_file(fpath) or {}
    haystack = " ".join([
        rel.lower(),
        str(info.get("docstring", "")).lower(),
        " ".join(info.get("imports", [])).lower(),
    ])
    keywords = [token for token in re.findall(r"[a-zA-Z_\-\u4e00-\u9fff]{2,}", context_text.lower()) if len(token) >= 2]
    for keyword in keywords[:20]:
        if keyword and keyword in haystack:
            score += 2
    if rel.startswith(("core/prompt_manager/", "core/infrastructure/", "agent.py", "config/")):
        score += 1
    return score


def _module_name_for_path(fpath: Path, project_root: Path) -> str:
    rel = fpath.relative_to(project_root).as_posix()
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _build_dependency_index(files: List[Path], project_root: Path) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """构建模块反向依赖索引。"""
    reverse_imports: Dict[str, List[str]] = defaultdict(list)
    module_to_path: Dict[str, str] = {}
    for fpath in files:
        rel = fpath.relative_to(project_root).as_posix()
        module_name = _module_name_for_path(fpath, project_root)
        module_to_path[module_name] = rel

    for fpath in files:
        rel = fpath.relative_to(project_root).as_posix()
        module_name = _module_name_for_path(fpath, project_root)
        info = _scan_file(fpath) or {}
        for imported in info.get("imports", []):
            target = imported
            while target:
                if target in module_to_path:
                    reverse_imports[module_to_path[target]].append(rel)
                    break
                if "." not in target:
                    break
                target = target.rsplit(".", 1)[0]
    return reverse_imports, module_to_path


def _candidate_tests_for_path(rel_path: str) -> List[str]:
    """根据源文件路径推测测试文件。"""
    path = Path(rel_path)
    if rel_path.startswith("tests/") or path.name.startswith("test_"):
        return [rel_path]
    stem = path.stem
    candidates = [
        f"tests/test_{stem}.py",
        f"tests/test_{stem.replace('_', '')}.py",
    ]
    if path.parent.parts:
        parent = path.parent.parts[-1]
        candidates.append(f"tests/test_{parent}.py")
        candidates.append(f"tests/{parent}/test_{stem}.py")
    return list(dict.fromkeys(candidates))


def _build_impact_chain_view(
    top_files: List[Path],
    files: List[Path],
    project_root: Path,
) -> str:
    """为当前热点文件构建影响链路视图。"""
    if not top_files:
        return ""

    reverse_imports, _ = _build_dependency_index(files, project_root)
    lines = ["## 影响链路"]
    for fpath in top_files[:3]:
        rel = fpath.relative_to(project_root).as_posix()
        impacted = reverse_imports.get(rel, [])
        affected_tests = _candidate_tests_for_path(rel)
        lines.append(f"- `{rel}`")
        if impacted:
            preview = ", ".join(f"`{item}`" for item in impacted[:3])
            if len(impacted) > 3:
                preview += " ..."
            lines.append(f"  - 可能牵动模块: {preview}")
        if affected_tests:
            preview = ", ".join(f"`{item}`" for item in affected_tests[:3])
            lines.append(f"  - 建议先看测试: {preview}")
    return "\n".join(lines)


def _build_task_focused_view(project_root: Path, full_content: str) -> str:
    """构建面向当前任务的局部导航视图。"""
    goal, state_memory = _get_prompt_runtime_context()
    session = None
    attention = {}
    recent_changes = []
    try:
        from core.infrastructure.agent_session import get_session_state
        session = get_session_state()
        attention = session.get_attention_snapshot()
    except Exception:
        attention = {}
    try:
        from core.infrastructure.git_memory import get_git_memory_service
        recent_changes = get_git_memory_service().get_recent_project_changes(limit=4)
    except Exception:
        recent_changes = []

    hot_paths = set(attention.get("modified_paths") or [])
    for change in recent_changes:
        if getattr(change, "path", None):
            hot_paths.add(change.path)

    files = _collect_python_files(project_root)
    context_text = "\n".join(part for part in [goal, state_memory] if part).strip()
    scored = []
    for fpath in files:
        score = _score_file_relevance(fpath, project_root, context_text, hot_paths)
        if score > 0:
            scored.append((score, fpath))
    scored.sort(key=lambda item: (-item[0], item[1].as_posix()))
    top_files = [f for _, f in scored[:6]]

    lines = ["## 当前任务局部地图"]
    if goal:
        lines.append(f"- 当前目标: {goal}")
    if attention.get("modified_paths"):
        display = ", ".join(f"`{path}`" for path in (attention.get("modified_paths") or [])[:4])
        lines.append(f"- 当前焦点路径: {display}")
    if attention.get("modified_entities"):
        display = ", ".join(f"`{name}`" for name in (attention.get("modified_entities") or [])[:6])
        lines.append(f"- 当前焦点实体: {display}")
    if top_files:
        lines.append("- 建议先读:")
        for fpath in top_files[:4]:
            rel = fpath.relative_to(project_root).as_posix()
            info = _scan_file(fpath) or {}
            doc = info.get("docstring") or "无描述"
            lines.append(f"  - `{rel}`: {doc}")
    if recent_changes:
        lines.append("- 最近牵动链路:")
        for change in recent_changes[:3]:
            suffix = f" ({change.subject})" if getattr(change, "subject", None) else ""
            lines.append(f"  - `{change.path}`: {change.change_type}{suffix}")
    if attention.get("last_validation_summary"):
        lines.append(f"- 最近验证焦点: {attention['last_validation_summary']}")

    impact_chain = _build_impact_chain_view(top_files, files, project_root)

    overview = _extract_markdown_section(full_content, "子系统概览")
    dependency = _extract_markdown_section(full_content, "核心依赖 (被依赖最多的模块 Top-10)")
    coverage = _extract_markdown_section(full_content, "测试覆盖")

    compact_sections = ["## 全局骨架摘要"]
    if overview:
        compact_sections.append(overview)
    if dependency:
        dep_lines = dependency.splitlines()
        compact_sections.append("\n".join(dep_lines[:6]))
    if coverage:
        cov_lines = coverage.splitlines()
        compact_sections.append("\n".join(cov_lines[:4]))

    sections = [
        "\n".join(lines).strip(),
    ]
    if impact_chain:
        sections.append(impact_chain.strip())
    sections.append("\n".join(compact_sections).strip())
    return "\n\n".join(section for section in sections if section).strip()


def get_codebase_map(force_refresh: bool = False) -> str:
    """获取代码库地图（优先读取缓存，不含 YAML front matter）。

    Args:
        force_refresh: True 时强制重新扫描

    Returns:
        地图内容字符串（已剥离 front matter）
    """
    if force_refresh or should_rescan():
        content = scan_and_build_codebase_map()
    else:
        map_path = _get_codebase_map_path()
        if map_path.exists():
            try:
                content = map_path.read_text(encoding="utf-8")
            except Exception:
                content = scan_and_build_codebase_map()
        else:
            content = scan_and_build_codebase_map()
    stripped = _strip_front_matter(content)
    project_root = _resolve_project_root()
    task_view = _build_task_focused_view(project_root, stripped)
    if not task_view:
        return stripped
    return f"{task_view}\n\n---\n\n{stripped}"


# ═══════════════════════════════════════════════════════════════════════════════
# 工具入口（供 ToolExecutor 钩子调用）
# ═══════════════════════════════════════════════════════════════════════════════

_FILE_MODIFYING_TOOLS = {
    "write_file_tool",
    "write_file",
    "edit_file",
    "replace_in_file",
    "create_file",
}


def is_file_modifying_tool(tool_name: str) -> bool:
    """判断工具是否会修改文件。"""
    return tool_name in _FILE_MODIFYING_TOOLS


def extract_file_path(tool_name: str, tool_args: dict) -> Optional[str]:
    """从工具参数中提取被修改的文件路径。

    Args:
        tool_name: 工具名称
        tool_args: 工具参数字典

    Returns:
        相对文件路径，或 None
    """
    filepath = tool_args.get("file_path") or tool_args.get("path") or ""
    if not filepath:
        return None

    # 标准化为相对路径
    project_root = _resolve_project_root()
    try:
        abs_path = Path(filepath).resolve()
        rel_path = abs_path.relative_to(project_root).as_posix()
        return rel_path
    except (ValueError, OSError):
        return filepath


def on_file_modified(filepath: str):
    """文件修改后的回调（由 ToolExecutor 钩子调用）。

    在后台线程中执行增量更新，不阻塞主循环。
    """
    if not filepath.endswith(".py"):
        return
    # 只追踪项目内的 Python 文件
    if any(part.startswith(".") for part in Path(filepath).parts):
        return
    if "workspace" in filepath or "log_info" in filepath or "__pycache__" in filepath:
        return

    # 后台线程执行增量更新
    t = threading.Thread(
        target=lambda: incremental_update_file(filepath),
        daemon=True,
        name="map-updater",
    )
    t.start()


__all__ = [
    "scan_and_build_codebase_map",
    "should_rescan",
    "get_codebase_map",
    "incremental_update_file",
    "incremental_add_file",
    "on_file_modified",
    "is_file_modifying_tool",
    "extract_file_path",
]
