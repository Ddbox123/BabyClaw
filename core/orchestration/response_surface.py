# -*- coding: utf-8 -*-
"""响应后的感知、展示与落账控制器。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Sequence

from core.mental_model_flags import is_mental_model_enabled


def _resolve_mental_model_enabled(override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    return is_mental_model_enabled()


def _read_nested_int(data: Dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return 0


class ResponseSurfaceController:
    """集中处理响应后的感知、副作用记录、UI 输出和 token 落账。"""

    def __init__(
        self,
        *,
        estimate_tokens: Callable[[Sequence[Any]], int],
        ui_getter: Callable[[], Any],
        logger: Any,
        debug_logger: Any,
        pet_getter: Callable[[], Any],
        print_tokens: Callable[[int, int], None],
    ) -> None:
        self._estimate_tokens = estimate_tokens
        self._ui_getter = ui_getter
        self._logger = logger
        self._debug_logger = debug_logger
        self._pet_getter = pet_getter
        self._print_tokens = print_tokens

    def build_state_block(
        self,
        *,
        raw_content: str,
        has_tool_calls: bool,
        consecutive_failures: int,
        iteration: int,
        messages: Sequence[Any],
        mental_model: Any,
        effective_max_token_limit: int,
        mental_model_enabled: bool | None = None,
    ) -> str:
        if not _resolve_mental_model_enabled(mental_model_enabled):
            return ""
        should_sense = has_tool_calls or consecutive_failures >= 2 or iteration == 1
        if not should_sense:
            return ""
        try:
            recent_tools = list(getattr(mental_model, "_tool_history", []))[-5:]
            tool_summary = "\n".join(
                f"- {t.tool_name}({'✓' if t.success else '✗'}) {t.args_summary}"
                for t in recent_tools
            ) or "尚无工具调用"
            current_tokens = self._estimate_tokens(messages)
            token_ratio = (
                current_tokens / effective_max_token_limit
                if effective_max_token_limit > 0
                else 0.0
            )
            return mental_model.sense_state(
                think_content=raw_content,
                tool_summary=tool_summary,
                token_ratio=token_ratio,
                iteration=iteration,
            )
        except Exception:
            return ""

    def apply_state_feedback(
        self,
        *,
        processed: Any,
        record_language_drift: Callable[[str], None],
        record_inference_activity: Callable[[str], None],
        mental_model_enabled: bool | None = None,
    ) -> Dict[str, str]:
        raw_content_clean = processed.raw_content_clean
        record_language_drift(raw_content_clean)
        record_inference_activity(raw_content_clean)

        if not _resolve_mental_model_enabled(mental_model_enabled):
            return {}

        state_info = processed.state_info or {}
        if state_info.get("mood"):
            ui = self._ui_getter()
            ui.set_pet_mental_state(
                mood=state_info.get("mood", ""),
                feeling=state_info.get("feeling", ""),
                whisper=state_info.get("whisper", ""),
            )
            mood = state_info["mood"]
            if mood not in ("专注", "自信"):
                self._debug_logger.info(
                    f"[感知] {mood} | {state_info.get('feeling', '')} | {state_info.get('whisper', '')}",
                    tag="STATE",
                )
        return state_info

    def record_token_usage(
        self,
        *,
        response: Any,
        round_state: Any,
        current_turn: int,
        messages: Sequence[Any] | None = None,
        raw_content: str = "",
        estimate_output_tokens: Callable[[str], int] | None = None,
    ) -> tuple[int, int]:
        ui = self._ui_getter()
        input_tokens = 0
        output_tokens = 0
        usage = self._extract_usage_payload(response)
        if usage:
            input_tokens, output_tokens = self._extract_usage_tokens(usage)

        estimated = False
        if not input_tokens and messages is not None:
            input_tokens = max(0, int(self._estimate_tokens(messages) or 0))
            estimated = input_tokens > 0
        if not output_tokens and raw_content and estimate_output_tokens is not None:
            output_tokens = max(0, int(estimate_output_tokens(raw_content) or 0))
            estimated = estimated or output_tokens > 0

        if estimated:
            self._debug_logger.info(
                f"[TOKEN] usage metadata missing/incomplete; estimated input={input_tokens} output={output_tokens}",
                tag="TOKEN",
            )

        if input_tokens or output_tokens:
            round_state.add_token_usage(input_tokens, output_tokens)

            self._print_tokens(input_tokens, output_tokens)
            self._logger.log_token_usage(input_tokens, output_tokens, current_turn)

            try:
                pet = self._pet_getter()
                pet.record_tokens(input_tokens, output_tokens)
                pet.trigger_heartbeat()
            except Exception:
                pass
            ui.note_token_usage(input_tokens, output_tokens, observed=True)
        else:
            ui.note_token_usage(observed=False)
        return input_tokens, output_tokens

    @staticmethod
    def _extract_usage_payload(response: Any) -> Dict[str, Any]:
        for attr in ("usage_metadata", "usage"):
            usage = getattr(response, attr, None)
            if isinstance(usage, dict) and usage:
                return usage

        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            for key in ("token_usage", "usage", "usage_metadata"):
                usage = response_metadata.get(key)
                if isinstance(usage, dict) and usage:
                    return usage

        return {}

    @staticmethod
    def _extract_usage_tokens(usage: Dict[str, Any] | Any) -> tuple[int, int]:
        if not isinstance(usage, dict):
            return 0, 0

        def _read_int(*keys: str) -> int:
            for key in keys:
                value = usage.get(key)
                if value not in (None, ""):
                    try:
                        return max(0, int(value))
                    except (TypeError, ValueError):
                        continue
            return 0

        input_tokens = _read_int("input_tokens", "prompt_tokens", "input_token_count")
        output_tokens = _read_int("output_tokens", "completion_tokens", "output_token_count")

        if not input_tokens and isinstance(usage.get("input_token_details"), dict):
            input_tokens = _read_nested_int(usage["input_token_details"], "input_tokens", "prompt_tokens")
        if not output_tokens and isinstance(usage.get("output_token_details"), dict):
            output_tokens = _read_nested_int(usage["output_token_details"], "output_tokens", "completion_tokens")

        total_tokens = _read_int("total_tokens")
        if total_tokens > 0:
            if input_tokens and not output_tokens:
                output_tokens = max(0, total_tokens - input_tokens)
            elif output_tokens and not input_tokens:
                input_tokens = max(0, total_tokens - output_tokens)

        return input_tokens, output_tokens

    def emit_visible_response(
        self,
        *,
        raw_content: str,
        processed: Any,
        tool_call_count: int,
    ) -> Dict[str, Any]:
        if not raw_content.strip():
            return {
                "last_visible_response_text": "",
                "last_response_tool_calls": 0,
            }

        ui = self._ui_getter()
        stream_response = getattr(ui, "stream_response", None)
        if callable(stream_response):
            stream_response(processed.visible_text, done=True)
        else:
            ui.stream_thought(processed.visible_text, done=True)
        if not tool_call_count:
            for chunk in processed.visible_text.splitlines():
                if chunk.strip():
                    ui.add_content(chunk)
        return {
            "last_visible_response_text": processed.visible_text,
            "last_response_tool_calls": tool_call_count,
        }
