from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List

from config import get_config
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.event_bus import Event, EventNames, get_event_bus
from core.infrastructure.workspace_manager import get_workspace


class EvolutionGovernor:
    """Enforce mutation boundaries during active evolution transactions."""

    _RISKY_PATH_PREFIXES = ("core/", "tools/", "config/", "workspace/prompts/")
    _RISKY_PATHS = {"agent.py", "reset.py"}
    _FILE_PATH_TOOLS = {
        "write_file_tool",
        "create_file",
        "create_file_tool",
        "apply_diff_edit_tool",
    }
    _DYNAMIC_PROMPT_TOOLS = {
        "write_dynamic_prompt_tool",
        "add_insight_to_dynamic_tool",
    }

    def __init__(self) -> None:
        self._bus = get_event_bus()
        self._ensure_subscriptions()

    def check_mutation_allowed(
        self,
        tool_name: str,
        tool_args: dict,
        active_txn_id: str | None,
    ) -> str | None:
        targets = self._resolve_targets(tool_name, tool_args)
        if not targets:
            return None
        if not active_txn_id:
            risky = [path for path in targets if self._is_risky_target(path)]
            if not risky:
                return None
            risky_display = ", ".join(self._to_project_relative(path) for path in risky)
            return (
                "[演化治理] 这个写入会修改高风险演化路径，必须先调用 "
                f"`open_evolution_transaction_tool` 开启事务。目标: {risky_display}"
            )
        allowed_roots = self._allowed_roots()
        denied = [path for path in targets if not self._is_under_allowed_roots(path, allowed_roots)]
        if not denied:
            return None
        denied_display = ", ".join(self._to_project_relative(path) for path in denied)
        allowed_display = ", ".join(self._to_project_relative(path) for path in allowed_roots) or "(none)"
        message = (
            f"[演化治理] 当前演化事务 `{active_txn_id}` 只允许修改白名单目录。"
            f" 允许: {allowed_display}; 拒绝: {denied_display}"
        )
        self._append_audit_record({
            "event": "mutation_blocked",
            "txn_id": active_txn_id,
            "tool_name": tool_name,
            "allowed_roots": [self._to_project_relative(path) for path in allowed_roots],
            "target_paths": [self._to_project_relative(path) for path in targets],
            "reason": "outside_allowed_target_dirs",
        })
        return message

    def record_mutation_result(
        self,
        tool_name: str,
        tool_args: dict,
        result: Any,
        active_txn_id: str | None,
    ) -> None:
        if not active_txn_id:
            return
        targets = self._resolve_targets(tool_name, tool_args)
        if not targets:
            return
        status = "success" if self._looks_successful(result) else "failed"
        target_paths = [self._to_project_relative(path) for path in targets]
        target_dirs = sorted({str(Path(path).parent).replace("\\", "/") for path in target_paths})
        self._append_audit_record({
            "event": "mutation_recorded",
            "txn_id": active_txn_id,
            "tool_name": tool_name,
            "status": status,
            "target_paths": target_paths,
            "complexity": {
                "target_count": len(target_paths),
                "directory_count": len(target_dirs),
                "complexity_units": len(target_paths),
            },
        })

    def build_fitness_summary(self, recent_limit: int = 5) -> dict:
        records = self._read_audit_records()
        transaction_stats: dict[str, dict[str, Any]] = {}
        validation = {"total": 0, "passed": 0, "failed": 0, "by_kind": {}}
        mutations = {"blocked": 0, "recorded": 0, "successful": 0, "failed": 0}

        for record in records:
            event = str(record.get("event") or "")
            txn_id = str(record.get("txn_id") or "").strip()
            if txn_id:
                txn = transaction_stats.setdefault(
                    txn_id,
                    {
                        "txn_id": txn_id,
                        "opened_at": None,
                        "closed_at": None,
                        "status": "open",
                        "validation_passed": 0,
                        "validation_failed": 0,
                        "mutations_recorded": 0,
                        "mutations_blocked": 0,
                    },
                )
            else:
                txn = None

            if event == "txn_opened" and txn is not None:
                txn["opened_at"] = record.get("timestamp")
                txn["status"] = "open"
            elif event == "txn_closed" and txn is not None:
                txn["closed_at"] = record.get("timestamp")
                txn["status"] = str(record.get("status") or "unknown")
            elif event == "validation_completed":
                validation["total"] += 1
                passed = bool(record.get("passed"))
                kind = str(record.get("kind") or "validation")
                bucket = validation["by_kind"].setdefault(kind, {"passed": 0, "failed": 0})
                if passed:
                    validation["passed"] += 1
                    bucket["passed"] += 1
                    if txn is not None:
                        txn["validation_passed"] += 1
                else:
                    validation["failed"] += 1
                    bucket["failed"] += 1
                    if txn is not None:
                        txn["validation_failed"] += 1
            elif event == "mutation_blocked":
                mutations["blocked"] += 1
                if txn is not None:
                    txn["mutations_blocked"] += 1
            elif event == "mutation_recorded":
                mutations["recorded"] += 1
                status = str(record.get("status") or "")
                if status == "success":
                    mutations["successful"] += 1
                else:
                    mutations["failed"] += 1
                if txn is not None:
                    txn["mutations_recorded"] += 1

        txns = list(transaction_stats.values())
        closed = [item for item in txns if item.get("status") in {"success", "failed", "cancelled"}]
        successful = [item for item in closed if item.get("status") == "success"]
        success_rate = round(len(successful) / len(closed), 3) if closed else None
        validation_pass_rate = round(validation["passed"] / validation["total"], 3) if validation["total"] else None

        recent_transactions = sorted(
            txns,
            key=lambda item: str(item.get("closed_at") or item.get("opened_at") or ""),
            reverse=True,
        )[: max(1, recent_limit)]

        return {
            "audit_record_count": len(records),
            "transactions": {
                "opened": len(txns),
                "closed": len(closed),
                "successful": len(successful),
                "failed": len([item for item in closed if item.get("status") == "failed"]),
                "cancelled": len([item for item in closed if item.get("status") == "cancelled"]),
                "success_rate": success_rate,
                "recent": recent_transactions,
            },
            "validation": {
                **validation,
                "pass_rate": validation_pass_rate,
            },
            "mutations": mutations,
        }

    def _resolve_targets(self, tool_name: str, tool_args: dict) -> List[Path]:
        if tool_name in self._FILE_PATH_TOOLS:
            file_path = str((tool_args or {}).get("file_path") or "").strip()
            if not file_path:
                return []
            return [self._resolve_project_path(file_path)]
        if tool_name in self._DYNAMIC_PROMPT_TOOLS:
            return [get_workspace().get_prompt_path("DYNAMIC.md").resolve()]
        return []

    def _allowed_roots(self) -> List[Path]:
        evolution = get_config().evolution
        roots = [self._resolve_project_path(item) for item in (evolution.allowed_target_dirs or []) if str(item).strip()]
        return roots

    @staticmethod
    def _looks_successful(result: Any) -> bool:
        text = str(result or "")
        lowered = text.lower()
        if any(marker in text for marker in ("[错误]", "[FAIL]", "[ERROR]")):
            return False
        if '"status": "error"' in lowered or '"status":"error"' in lowered:
            return False
        if '"status": "failed"' in lowered or '"status":"failed"' in lowered:
            return False
        return True

    @staticmethod
    def _is_under_allowed_roots(path: Path, allowed_roots: Iterable[Path]) -> bool:
        normalized = path.resolve()
        for root in allowed_roots:
            try:
                normalized.relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _resolve_project_path(path_str: str) -> Path:
        candidate = Path(path_str)
        if candidate.is_absolute():
            return candidate.resolve()
        return (get_workspace().project_root / candidate).resolve()

    @classmethod
    def _is_risky_target(cls, path: Path) -> bool:
        relative = cls._to_project_relative(path)
        return relative in cls._RISKY_PATHS or relative.startswith(cls._RISKY_PATH_PREFIXES)

    @staticmethod
    def _to_project_relative(path: Path) -> str:
        project_root = get_workspace().project_root.resolve()
        try:
            return str(path.resolve().relative_to(project_root)).replace("\\", "/")
        except ValueError:
            return str(path.resolve()).replace("\\", "/")

    def _append_audit_record(self, payload: dict) -> None:
        evolution = get_config().evolution
        audit_path = self._resolve_project_path(evolution.audit_log_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            **payload,
        }
        with open(audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_audit_records(self) -> List[dict]:
        evolution = get_config().evolution
        audit_path = self._resolve_project_path(evolution.audit_log_path)
        if not audit_path.exists():
            return []
        records: List[dict] = []
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def _ensure_subscriptions(self) -> None:
        for event_name, handler, callback_id in (
            (EventNames.EVOLUTION_TXN_OPENED, self._on_txn_opened, "evolution_governor_txn_opened"),
            (EventNames.EVOLUTION_TXN_CLOSED, self._on_txn_closed, "evolution_governor_txn_closed"),
            (EventNames.VALIDATION_COMPLETED, self._on_validation_completed, "evolution_governor_validation"),
        ):
            self._bus.unsubscribe_by_id(callback_id)
            self._bus.subscribe(event_name, handler, callback_id=callback_id)

    def _on_txn_opened(self, event: Event) -> None:
        data = getattr(event, "data", {}) or {}
        self._append_audit_record(
            {
                "event": "txn_opened",
                "txn_id": str(data.get("txn_id") or ""),
                "base_rev": data.get("base_rev"),
            }
        )

    def _on_txn_closed(self, event: Event) -> None:
        data = getattr(event, "data", {}) or {}
        self._append_audit_record(
            {
                "event": "txn_closed",
                "txn_id": str(data.get("txn_id") or ""),
                "status": str(data.get("status") or "unknown"),
            }
        )

    def _on_validation_completed(self, event: Event) -> None:
        data = getattr(event, "data", {}) or {}
        self._append_audit_record(
            {
                "event": "validation_completed",
                "txn_id": get_session_state().get_active_evolution_txn(),
                "kind": str(data.get("kind") or "validation"),
                "passed": bool(data.get("passed")),
                "message": str(data.get("message") or ""),
            }
        )


_governor: EvolutionGovernor | None = None


def get_evolution_governor() -> EvolutionGovernor:
    global _governor
    if _governor is None:
        _governor = EvolutionGovernor()
    return _governor
