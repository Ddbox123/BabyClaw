#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Token 显示模块 — 简洁版
"""

from __future__ import annotations
from typing import Optional


def format_token_count(tokens: int) -> str:
    """Format token counts compactly for UI surfaces."""
    count = max(0, int(tokens or 0))
    units = ((1_000_000, "M"), (1_000, "K"))
    for size, suffix in units:
        if count >= size:
            value = count / size
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return str(count)


def print_tokens(input_tokens: int, output_tokens: Optional[int] = None,
                 iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> None:
    """打印 Token 使用信息"""
    try:
        from core.ui.cli_ui import UIManager
        if UIManager._test_mode:
            import sys
            msg = f"[TOKEN] 输入: {format_token_count(input_tokens)}"
            if output_tokens is not None:
                msg += f" | 输出: {format_token_count(output_tokens)}"
            sys.__stdout__.write(msg + "\n")
            sys.__stdout__.flush()
            return
    except ImportError:
        pass

    try:
        from core.ui.cli_ui import ui_log
        if output_tokens is not None:
            ui_log(f"Tok in:{format_token_count(input_tokens)} out:{format_token_count(output_tokens)}", "DEBUG")
        elif iteration is not None:
            ui_log(f"Tok in:{format_token_count(input_tokens)} iter:{iteration}/{max_iterations}", "DEBUG")
        else:
            ui_log(f"Tok in:{format_token_count(input_tokens)}", "DEBUG")
    except ImportError:
        pass


def print_input_tokens(input_tokens: int, iteration: int, max_iterations: int) -> None:
    print_tokens(input_tokens=input_tokens, iteration=iteration, max_iterations=max_iterations)


def print_output_tokens(input_tokens: int, output_tokens: int) -> None:
    print_tokens(input_tokens=input_tokens, output_tokens=output_tokens)


def format_token_report(input_tokens: int, output_tokens: int,
                        compression_ratio: Optional[float] = None) -> str:
    total = input_tokens + output_tokens
    report = (
        f"Token: {format_token_count(input_tokens)} + "
        f"{format_token_count(output_tokens)} = {format_token_count(total)}"
    )
    if compression_ratio is not None:
        report += f" (压缩率: {compression_ratio:.1%})"
    return report


__all__ = [
    "format_token_count",
    "print_tokens",
    "print_input_tokens",
    "print_output_tokens",
    "format_token_report",
]
