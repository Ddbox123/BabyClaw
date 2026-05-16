# UI 模块 - 用户界面组件

from __future__ import annotations

_EXPORTS = {
    "AvatarManager": ("core.ui.ascii_art", "AvatarManager"),
    "get_avatar_manager": ("core.ui.ascii_art", "get_avatar_manager"),
    "get_lobster_banner": ("core.ui.ascii_art", "get_lobster_banner"),
    "get_status_lobster": ("core.ui.ascii_art", "get_status_lobster"),
    "UIManager": ("core.ui.cli_ui", "UIManager"),
    "get_ui": ("core.ui.cli_ui", "get_ui"),
    "ui_error": ("core.ui.cli_ui", "ui_error"),
    "ui_print_header": ("core.ui.cli_ui", "ui_print_header"),
    "ui_thinking": ("core.ui.cli_ui", "ui_thinking"),
    "ui_print_tool": ("core.ui.cli_ui", "ui_print_tool"),
    "ui_warning": ("core.ui.cli_ui", "ui_warning"),
    "ui_success": ("core.ui.cli_ui", "ui_success"),
    "ui_log": ("core.ui.cli_ui", "ui_log"),
    "ui_update_status": ("core.ui.cli_ui", "ui_update_status"),
    "ui_task_board": ("core.ui.cli_ui", "ui_task_board"),
    "ui_lobster_status": ("core.ui.cli_ui", "ui_lobster_status"),
    "ui_welcome": ("core.ui.cli_ui", "ui_welcome"),
    "ui_print_welcome": ("core.ui.cli_ui", "ui_print_welcome"),
    "run_interactive_mode": ("core.ui.cli_ui", "run_interactive_mode"),
    "XuebaInteractiveCLI": ("core.ui.interactive_cli", "XuebaInteractiveCLI"),
    "AgentWorkbenchShell": ("core.ui.workbench", "AgentWorkbenchShell"),
    "LobsterTheme": ("core.ui.theme", "LobsterTheme"),
    "LobsterStyle": ("core.ui.theme", "LobsterStyle"),
    "get_theme": ("core.ui.theme", "get_theme"),
    "get_style": ("core.ui.theme", "get_style"),
    "print_tokens": ("core.ui.token_display", "print_tokens"),
    "print_input_tokens": ("core.ui.token_display", "print_input_tokens"),
    "print_output_tokens": ("core.ui.token_display", "print_output_tokens"),
    "format_token_report": ("core.ui.token_display", "format_token_report"),
    "format_token_count": ("core.ui.token_display", "format_token_count"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
