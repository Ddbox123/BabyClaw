#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workspace Cleaner - 工作区碎片扫描与清理

三层防护架构的第 3 层（清理层）：
- 分类工作区文件为合法文件或碎片
- 提供扫描（只读）和清理（需确认）功能
- 支持 Agent 自调用和会话结束自动清理

碎片分类规则：
1. 孤儿脚本 — workspace/ 根目录的 .py 文件
2. 版本增殖 — *_vN.py, *_fix*.py, *_patch*.py 等
3. 镜像子树 — workspace/core/, workspace/tools/, workspace/tests/ 等
4. 未知目录 — 不在白名单中的子目录
"""

from __future__ import annotations

import os
import re
import json
import shutil
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from datetime import datetime


# ============================================================================
# 白名单配置
# ============================================================================

LEGITIMATE_DIRS: Set[str] = {
    "memory", "prompts", "logs", "mental_model",
}

LEGITIMATE_ROOT_FILES: Set[str] = {
    "agent_brain.db",
}

# 版本增殖文件名模式
VARIANT_PATTERNS: List[str] = [
    r".*_v\d+\.py$",
    r".*_fix(_[a-z]+)?\.py$",
    r"fix_.*\.py$",
    r".*_patch([_a-z]*)?\.py$",
    r"patch_.*\.py$",
    r".*_temp([_a-z]*)?\.py$",
    r"temp_.*\.py$",
    r".*_debug([_a-z]*)?\.py$",
    r"debug_.*\.py$",
    r".*_final\.py$",
    r".*_old\.py$",
    r"old_.*\.py$",
]


def _is_variant_filename(name: str) -> bool:
    """检查文件名是否匹配版本增殖模式"""
    for pattern in VARIANT_PATTERNS:
        if re.match(pattern, name, re.IGNORECASE):
            return True
    return False


# ============================================================================
# 文件分类
# ============================================================================

def classify_file(file_path: str, workspace_root: str) -> str:
    """
    将文件分类。

    Returns:
        'legitimate' | 'debris_root_py' | 'debris_variant' | 'debris_mirror' | 'debris_unknown'
    """
    ws = Path(workspace_root).resolve()
    fp = Path(file_path).resolve()

    try:
        rel = fp.relative_to(ws)
    except ValueError:
        return "debris_unknown"

    parts = rel.parts

    # 根目录文件
    if len(parts) == 1:
        if parts[0] in LEGITIMATE_ROOT_FILES:
            return "legitimate"
        if parts[0].endswith(".py"):
            if _is_variant_filename(parts[0]):
                return "debris_variant"
            return "debris_root_py"
        return "debris_unknown"

    # 子目录文件
    top_dir = parts[0]
    if top_dir in LEGITIMATE_DIRS:
        return "legitimate"

    # 镜像子树检测
    if top_dir in ("core", "tools", "tests", "config", "workspace"):
        return "debris_mirror"

    return "debris_unknown"


# ============================================================================
# 扫描
# ============================================================================

def scan_workspace_debris(
    workspace_root: str,
    session_files: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    扫描工作区，返回碎片分类报告。

    Args:
        workspace_root: workspace/ 目录的绝对路径
        session_files: 本次会话创建的文件集合（用于标记来源）

    Returns:
        {
            "scan_time": str,
            "total_files": int,
            "legitimate_count": int,
            "debris_count": int,
            "debris_by_category": {category: [files]},
            "categories_summary": {category: count},
        }
    """
    ws = Path(workspace_root).resolve()
    if not ws.exists():
        return {
            "scan_time": datetime.now().isoformat(),
            "total_files": 0,
            "legitimate_count": 0,
            "debris_count": 0,
            "debris_by_category": {},
            "categories_summary": {},
            "error": f"工作区不存在: {ws}",
        }

    session_files = session_files or set()
    # 规范化 session_files
    normalized_session: Set[str] = set()
    for sf in session_files:
        try:
            normalized_session.add(str(Path(sf).resolve()))
        except Exception:
            normalized_session.add(sf)

    legitimate_files: List[Dict[str, Any]] = []
    debris_by_category: Dict[str, List[Dict[str, Any]]] = {}

    for root, dirs, files in os.walk(str(ws)):
        # 跳过合法目录的内容（但仍检查目录名本身）
        rel_root = str(Path(root).relative_to(ws))
        if rel_root == ".":
            pass  # workspace root itself
        else:
            top_dir = rel_root.split(os.sep)[0]
            if top_dir in LEGITIMATE_DIRS:
                continue

        for fname in files:
            fpath = str(Path(root) / fname)
            fsize = os.path.getsize(fpath) if os.path.exists(fpath) else 0

            entry = {
                "path": fpath,
                "relative": str(Path(fpath).relative_to(ws)),
                "size_bytes": fsize,
                "from_session": str(Path(fpath).resolve()) in normalized_session,
            }

            category = classify_file(fpath, str(ws))

            if category == "legitimate":
                legitimate_files.append(entry)
            else:
                if category not in debris_by_category:
                    debris_by_category[category] = []
                debris_by_category[category].append(entry)

    debris_count = sum(len(v) for v in debris_by_category.values())

    return {
        "scan_time": datetime.now().isoformat(),
        "total_files": len(legitimate_files) + debris_count,
        "legitimate_count": len(legitimate_files),
        "debris_count": debris_count,
        "debris_by_category": {
            k: [f["relative"] for f in v]
            for k, v in debris_by_category.items()
        },
        "categories_summary": {
            k: len(v) for k, v in debris_by_category.items()
        },
    }


# ============================================================================
# 清理
# ============================================================================

def clean_debris(
    workspace_root: str,
    categories: Optional[List[str]] = None,
    confirmed: bool = False,
    session_files: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    清理工作区碎片。

    Args:
        workspace_root: workspace/ 目录的绝对路径
        categories: 要清理的碎片类别列表，None 表示全部
        confirmed: 必须为 True 才执行实际删除
        session_files: 如果提供，只清理此集合中的文件

    Returns:
        包含 deleted 和 skipped 计数的报告
    """
    if not confirmed:
        # dry-run 模式
        report = scan_workspace_debris(workspace_root, session_files)
        report["mode"] = "dry_run"
        report["message"] = "未设置 confirmed=True，仅扫描不删除。请确认后重试。"
        return report

    ws = Path(workspace_root).resolve()
    scan_report = scan_workspace_debris(str(ws), session_files)

    deleted: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []

    allowed_categories = set(categories) if categories else None
    session_normalized: Set[str] = set()
    if session_files:
        for sf in session_files:
            try:
                session_normalized.add(str(Path(sf).resolve()))
            except Exception:
                session_normalized.add(sf)

    for category, rel_paths in scan_report.get("debris_by_category", {}).items():
        # 过滤类别
        if allowed_categories and category not in allowed_categories:
            skipped.extend(rel_paths)
            continue

        for rel_path in rel_paths:
            fpath = ws / rel_path
            fpath_str = str(fpath.resolve())

            # 如果指定了 session_files，只清理会话创建的文件
            if session_normalized and fpath_str not in session_normalized:
                skipped.append(rel_path)
                continue

            try:
                if fpath.is_file():
                    fpath.unlink()
                    deleted.append(rel_path)
                elif fpath.is_dir():
                    shutil.rmtree(fpath, ignore_errors=False)
                    deleted.append(rel_path)
            except Exception as e:
                errors.append(f"{rel_path}: {e}")

    # 清理空目录
    _remove_empty_debris_dirs(ws, deleted)

    return {
        "scan_time": scan_report["scan_time"],
        "clean_time": datetime.now().isoformat(),
        "mode": "confirmed",
        "deleted_count": len(deleted),
        "deleted": deleted,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "errors": errors,
    }


def _remove_empty_debris_dirs(ws: Path, deleted_files: List[str]):
    """清理碎片文件被删除后留下的空目录（仅限非白名单目录）。"""
    deleted_dirs: Set[Path] = set()
    for rel_path in deleted_files:
        deleted_dirs.add(ws / rel_path)

    # 收集可能变空的父目录
    candidates: Set[Path] = set()
    for d in deleted_dirs:
        p = d.parent
        while p != ws and p not in candidates:
            candidates.add(p)
            p = p.parent

    # 从深到浅尝试删除空目录
    for d in sorted(candidates, key=lambda x: len(str(x)), reverse=True):
        try:
            rel = d.relative_to(ws)
            parts = rel.parts
            if parts and parts[0] in LEGITIMATE_DIRS:
                continue
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass


# ============================================================================
# 会话结束自动清理
# ============================================================================

def auto_clean_session_debris(
    workspace_root: str,
    mental_model=None,
) -> Dict[str, Any]:
    """
    会话结束时自动清理本次会话创建的碎片文件。

    只清理同时满足以下条件的文件：
    1. 由 Agent 本次会话创建（来自 MentalModel 追踪）
    2. 匹配碎片分类模式
    3. 不在白名单目录中

    Args:
        workspace_root: workspace/ 目录的绝对路径
        mental_model: MentalModel 实例（用于获取 session_files）

    Returns:
        清理报告
    """
    session_files: Set[str] = set()
    if mental_model:
        created = mental_model.get_agent_created_files()
        session_files = set(created.keys())

    if not session_files:
        return {
            "mode": "auto_clean",
            "message": "本次会话没有创建文件，无需清理。",
            "deleted_count": 0,
        }

    # 只清理碎片类别
    debris_categories = ["debris_root_py", "debris_variant", "debris_mirror"]
    return clean_debris(
        workspace_root=workspace_root,
        categories=debris_categories,
        confirmed=True,
        session_files=session_files,
    )


# ============================================================================
# Agent 可调用工具函数
# ============================================================================

def list_workspace_debris_tool(directory: str = "workspace") -> str:
    """
    扫描工作区碎片（只读，不删除）。

    Agent 用此工具检查 workspace/ 中的碎片状态。
    返回按类别分组的碎片清单。

    Args:
        directory: 要扫描的目录，默认 "workspace"

    Returns:
        JSON 格式的扫描报告
    """
    ws_root = directory
    if not os.path.isabs(directory):
        # 相对于项目根目录
        project_root = Path(__file__).parent.parent.parent
        ws_root = str(project_root / directory)

    report = scan_workspace_debris(ws_root)
    return json.dumps(report, ensure_ascii=False, indent=2)


def clean_workspace_debris_tool(
    confirm: bool = False,
    target_categories: str = "all",
) -> str:
    """
    清理工作区碎片。

    必须显式传入 confirm=True 才会执行实际删除。
    confirm=False 时仅扫描预览。

    Args:
        confirm: 必须为 True 才执行删除
        target_categories: 要清理的类别，逗号分隔。
            可选值: root_py, variant, mirror, unknown
            默认 "all" 清理全部

    Returns:
        JSON 格式的清理报告
    """
    project_root = Path(__file__).parent.parent.parent
    ws_root = str(project_root / "workspace")

    # 解析类别
    cat_str_map = {
        "root_py": "debris_root_py",
        "variant": "debris_variant",
        "mirror": "debris_mirror",
        "unknown": "debris_unknown",
    }

    if target_categories == "all":
        categories = None
    else:
        categories = [
            cat_str_map[c.strip()]
            for c in target_categories.split(",")
            if c.strip() in cat_str_map
        ]

    report = clean_debris(
        workspace_root=ws_root,
        categories=categories,
        confirmed=confirm,
    )
    return json.dumps(report, ensure_ascii=False, indent=2)


def get_session_files_tool() -> str:
    """
    查看本次 Agent 会话创建的文件列表。

    包含路径、创建时间、大小、是否为版本增殖等信息。

    Returns:
        JSON 格式的文件清单
    """
    try:
        from core.infrastructure.mental_model import get_mental_model
        mm = get_mental_model()
        files = mm.get_agent_created_files()
        variants = mm.get_version_variants()

        result = {
            "total_files": len(files),
            "variant_count": len(variants),
            "files": files,
            "variants": variants,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except ImportError:
        return json.dumps({
            "error": "MentalModel 不可用",
            "total_files": 0,
        }, ensure_ascii=False)
