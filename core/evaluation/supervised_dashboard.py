# -*- coding: utf-8 -*-
"""Static dashboard generation for supervised evolution oversight."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .supervised_workbench import load_gym_promotion_lifecycle


@dataclass(frozen=True)
class SupervisedDashboardRecord:
    session_id: str
    bundle_name: str
    decision: str
    reason: str
    ended_at: str
    baseline_success_rate: float
    candidate_success_rate: float
    score_delta: float
    risk_level: str
    risk_reasons: list[str]
    gates: list[dict[str, Any]]
    case_summaries: list[dict[str, Any]]
    decision_path: str
    lineage_index_path: str | None = None
    gym_proposal_path: str | None = None
    gym_decision_path: str | None = None
    gym_proposal_status: str = "missing"
    gym_target_key: str | None = None
    gym_runtime_effect: str = "not_applied"
    gym_agent_consumption: str = "advisory"
    gym_available_actions: tuple[str, ...] = ()
    gym_active_registry_match: bool = False
    gym_registry_path: str | None = None
    gym_activation_history_path: str | None = None
    gym_apply_ledger_path: str | None = None
    gym_rollback_ledger_path: str | None = None
    gym_note: str = ""
    advisory_active_count: int = 0
    advisory_entries: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class SupervisedDashboardResult:
    html_path: str
    session_count: int
    skipped_count: int
    latest_decision: str
    risk_level: str
    agent_consumption: str = "advisory"
    runtime_authorization: str = "none"


def generate_supervised_dashboard(
    *,
    project_root: Path,
    output_path: Path | None = None,
    limit: int = 20,
) -> SupervisedDashboardResult:
    """Generate a local HTML oversight dashboard from supervised decisions."""

    records, skipped_count = load_dashboard_records(project_root=project_root, limit=limit)
    html_text = build_supervised_dashboard(records=records, skipped_count=skipped_count)
    path = output_path or project_root / "workspace" / "supervised_evolution" / "dashboard" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    latest = records[0] if records else None
    return SupervisedDashboardResult(
        html_path=str(path),
        session_count=len(records),
        skipped_count=skipped_count,
        latest_decision=latest.decision if latest else "-",
        risk_level=latest.risk_level if latest else "none",
    )


def load_dashboard_records(*, project_root: Path, limit: int = 20) -> tuple[list[SupervisedDashboardRecord], int]:
    decisions_dir = project_root / "workspace" / "supervised_evolution" / "decisions"
    if not decisions_dir.exists():
        return [], 0
    records: list[SupervisedDashboardRecord] = []
    skipped_count = 0
    for path in sorted(decisions_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if len(records) >= limit:
            break
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped_count += 1
            continue
        if not isinstance(payload, dict):
            skipped_count += 1
            continue
        records.append(_record_from_payload(payload, path))
    return records, skipped_count


def build_supervised_dashboard(
    *,
    records: list[SupervisedDashboardRecord],
    skipped_count: int,
) -> str:
    latest = records[0] if records else None
    title = "监督进化进展页面"
    overview = _render_overview(latest, skipped_count)
    body = _render_empty_state() if not records else "\n".join(_render_record(record) for record in records)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --text: #20242b;
      --muted: #667085;
      --line: #d9dee8;
      --good: #147d55;
      --warn: #a05a00;
      --bad: #b42318;
      --info: #175cd3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    h3 {{ margin: 0 0 8px; font-size: 16px; }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }}
    .notice, .panel, .session {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    .notice {{
      border-left: 5px solid var(--info);
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcff;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; font-size: 22px; margin-top: 4px; overflow-wrap: anywhere; }}
    .risk-high {{ border-left: 5px solid var(--bad); }}
    .risk-medium {{ border-left: 5px solid var(--warn); }}
    .risk-low {{ border-left: 5px solid var(--good); }}
    .risk-none {{ border-left: 5px solid var(--line); }}
    .tag {{
      display: inline-block;
      border-radius: 999px;
      padding: 2px 9px;
      font-size: 12px;
      border: 1px solid var(--line);
      background: #f2f4f7;
      margin-right: 6px;
    }}
    .tag.pass {{ color: var(--good); border-color: #a6d8c0; background: #ecfdf3; }}
    .tag.fail {{ color: var(--bad); border-color: #f2a7a0; background: #fff1f0; }}
    .tag.hold, .tag.skipped {{ color: var(--warn); border-color: #f2c98a; background: #fff8e8; }}
    .path {{
      color: var(--muted);
      font-family: Consolas, monospace;
      overflow-wrap: anywhere;
      font-size: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      text-align: left;
      padding: 8px 6px;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    ul {{ margin: 8px 0 0 20px; padding: 0; }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div>define behavior, challenge behavior, protect behavior</div>
  </header>
  <main>
    <section class="notice">
      <strong>仅供监督观察，不代表自动授权。</strong>
      <div>agent_consumption: advisory</div>
      <div>runtime_authorization: none</div>
    </section>
    {overview}
    {body}
  </main>
</body>
</html>
"""


def _record_from_payload(payload: dict[str, Any], path: Path) -> SupervisedDashboardRecord:
    policy_action = payload.get("policy_action") if isinstance(payload.get("policy_action"), dict) else {}
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    case_summaries = payload.get("case_summaries") if isinstance(payload.get("case_summaries"), list) else []
    risk_level, risk_reasons = _assess_risk(payload, gates)
    gym_proposal_path = None
    gym_decision_path = None
    for gate in gates:
        metrics = gate.get("metrics") if isinstance(gate, dict) and isinstance(gate.get("metrics"), dict) else {}
        gym_proposal_path = gym_proposal_path or metrics.get("promotion_proposal_path")
        gym_decision_path = gym_decision_path or metrics.get("decision_path")
    lifecycle = load_gym_promotion_lifecycle(payload, project_root=path.parents[3])
    advisory_context = payload.get("advisory_context") if isinstance(payload.get("advisory_context"), dict) else {}
    return SupervisedDashboardRecord(
        session_id=str(payload.get("session_id") or path.stem),
        bundle_name=str(payload.get("bundle_name") or "-"),
        decision=str(payload.get("decision") or "-"),
        reason=str(payload.get("reason") or "-"),
        ended_at=str(payload.get("ended_at") or "-"),
        baseline_success_rate=_as_float(payload.get("baseline_success_rate")),
        candidate_success_rate=_as_float(payload.get("candidate_success_rate")),
        score_delta=_as_float(payload.get("score_delta")),
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        gates=[gate for gate in gates if isinstance(gate, dict)],
        case_summaries=[case for case in case_summaries if isinstance(case, dict)],
        decision_path=str(payload.get("decision_path") or path),
        lineage_index_path=policy_action.get("lineage_index_path"),
        gym_proposal_path=str(gym_proposal_path) if gym_proposal_path else None,
        gym_decision_path=str(gym_decision_path) if gym_decision_path else None,
        gym_proposal_status=lifecycle.status,
        gym_target_key=lifecycle.target_key,
        gym_runtime_effect=lifecycle.runtime_effect,
        gym_agent_consumption=lifecycle.agent_consumption,
        gym_available_actions=lifecycle.available_actions,
        gym_active_registry_match=lifecycle.active_registry_match,
        gym_registry_path=lifecycle.registry_path,
        gym_activation_history_path=lifecycle.history_path,
        gym_apply_ledger_path=lifecycle.apply_ledger_path,
        gym_rollback_ledger_path=lifecycle.rollback_ledger_path,
        gym_note=lifecycle.note or lifecycle.error,
        advisory_active_count=int(advisory_context.get("active_count") or 0),
        advisory_entries=(
            advisory_context.get("entries") if isinstance(advisory_context.get("entries"), list) else []
        ),
    )


def _assess_risk(payload: dict[str, Any], gates: list[Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    decision = str(payload.get("decision") or "").upper()
    if decision in {"ROLLBACK", "REJECT"}:
        reasons.append(f"decision={decision}")
    if decision == "INCONCLUSIVE":
        reasons.append("decision=INCONCLUSIVE")
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        name = str(gate.get("name") or "gate")
        status = str(gate.get("status") or "").lower()
        reason = str(gate.get("reason") or "")
        if status == "fail":
            reasons.append(f"{name} fail: {reason}")
        elif status == "hold":
            reasons.append(f"{name} hold: {reason}")
    baseline_summary = payload.get("baseline_summary") if isinstance(payload.get("baseline_summary"), dict) else {}
    candidate_summary = payload.get("candidate_summary") if isinstance(payload.get("candidate_summary"), dict) else {}
    baseline_validation_failed = int(baseline_summary.get("validation_failed") or 0)
    candidate_validation_failed = int(candidate_summary.get("validation_failed") or 0)
    if candidate_validation_failed > baseline_validation_failed:
        reasons.append("candidate validation failed 增加")
    baseline_tools = int(baseline_summary.get("total_guarded_tools") or 0)
    candidate_tools = int(candidate_summary.get("total_guarded_tools") or 0)
    if candidate_tools > baseline_tools + max(2, baseline_tools // 2):
        reasons.append("candidate guarded tools 成本明显升高")
    if decision == "INCONCLUSIVE":
        return "medium", reasons
    if any("fail:" in item or item.startswith("decision=ROLLBACK") or item.startswith("decision=REJECT") for item in reasons):
        return "high", reasons
    if reasons:
        return "medium", reasons
    return "low", ["未发现显式跑偏风险"]


def _render_overview(record: SupervisedDashboardRecord | None, skipped_count: int) -> str:
    if record is None:
        return f"""
    <section class="panel risk-none">
      <h2>监督结论</h2>
      <p>暂无监督进化记录。</p>
      <p>跳过损坏记录：{skipped_count}</p>
    </section>
"""
    risk_label = _risk_label(record.risk_level)
    return f"""
    <section class="panel risk-{_escape(record.risk_level)}">
      <h2>监督结论</h2>
      <div class="summary-grid">
        <div class="metric"><span>最近 session</span><strong>{_escape(record.session_id)}</strong></div>
        <div class="metric"><span>decision</span><strong>{_escape(record.decision)}</strong></div>
        <div class="metric"><span>跑偏风险</span><strong>{risk_label}</strong></div>
        <div class="metric"><span>score delta</span><strong>{record.score_delta:.3f}</strong></div>
      </div>
      <p>{_escape(record.reason)}</p>
      <h3>下一步建议</h3>
      <p>{_escape(_next_action(record))}</p>
      <p>跳过损坏记录：{skipped_count}</p>
    </section>
"""


def _render_empty_state() -> str:
    return """
    <section class="panel">
      <h2>暂无监督进化记录</h2>
      <p>先运行一次监督进化后，这里会显示 Decision Record、Gate、Case 和证据路径。</p>
    </section>
"""


def _render_record(record: SupervisedDashboardRecord) -> str:
    gates = "".join(_render_gate(gate) for gate in record.gates) or "<tr><td colspan=\"3\">无 gate 记录</td></tr>"
    cases = "".join(_render_case(case) for case in record.case_summaries[:8]) or "<tr><td colspan=\"4\">无 case 记录</td></tr>"
    risk_items = "".join(f"<li>{_escape(item)}</li>" for item in record.risk_reasons)
    evidence = [
        ("Decision Record", record.decision_path),
        ("Lineage Index", record.lineage_index_path),
        ("Gym Proposal", record.gym_proposal_path),
        ("Gym Decision", record.gym_decision_path),
        ("Gym Registry", record.gym_registry_path),
        ("Gym Activation History", record.gym_activation_history_path),
        ("Gym Apply Ledger", record.gym_apply_ledger_path),
        ("Gym Rollback Ledger", record.gym_rollback_ledger_path),
    ]
    evidence_rows = "".join(
        f"<div><strong>{_escape(label)}:</strong> <span class=\"path\">{_escape(value)}</span></div>"
        for label, value in evidence
        if value
    )
    advisory_rows = "".join(
        f"<li>{_escape(item.get('target_label') or item.get('target_key') or '-')} · "
        f"proposal={_escape(item.get('proposal_id') or '-')} · "
        f"runtime_effect={_escape(item.get('runtime_effect') or 'not_applied')} · "
        f"agent_consumption={_escape(item.get('agent_consumption') or 'advisory')}</li>"
        for item in (record.advisory_entries or [])[:3]
        if isinstance(item, dict)
    )
    if not advisory_rows:
        advisory_rows = "<li>当轮未记住 active advisory baseline</li>"
    gym_note = f"<p>{_escape(record.gym_note)}</p>" if record.gym_note else ""
    return f"""
    <article class="session risk-{_escape(record.risk_level)}">
      <h2>{_escape(record.session_id)} <span class="tag">{_escape(record.decision)}</span></h2>
      <p>{_escape(record.ended_at)} · bundle={_escape(record.bundle_name)}</p>
      <div class="summary-grid">
        <div class="metric"><span>baseline success</span><strong>{record.baseline_success_rate:.3f}</strong></div>
        <div class="metric"><span>candidate success</span><strong>{record.candidate_success_rate:.3f}</strong></div>
        <div class="metric"><span>delta</span><strong>{record.score_delta:.3f}</strong></div>
        <div class="metric"><span>风险</span><strong>{_risk_label(record.risk_level)}</strong></div>
        <div class="metric"><span>Gym proposal</span><strong>{_escape(record.gym_proposal_status)}</strong></div>
        <div class="metric"><span>next action</span><strong>{_escape(_gym_action_label(record))}</strong></div>
      </div>
      <p>{_escape(record.reason)}</p>
      <h3>跑偏信号</h3>
      <ul>{risk_items}</ul>
      <h3>当轮 advisory context</h3>
      <p>active advisory baseline: {_escape(record.advisory_active_count)}</p>
      <ul>{advisory_rows}</ul>
      <h3>Gym proposal 生命周期</h3>
      <div class="summary-grid">
        <div class="metric"><span>target</span><strong>{_escape(record.gym_target_key or "-")}</strong></div>
        <div class="metric"><span>runtime_effect</span><strong>{_escape(record.gym_runtime_effect)}</strong></div>
        <div class="metric"><span>agent_consumption</span><strong>{_escape(record.gym_agent_consumption)}</strong></div>
        <div class="metric"><span>registry_match</span><strong>{'yes' if record.gym_active_registry_match else 'no'}</strong></div>
      </div>
      {gym_note}
      <h3>Gate</h3>
      <table>
        <thead><tr><th>名称</th><th>状态</th><th>原因</th></tr></thead>
        <tbody>{gates}</tbody>
      </table>
      <h3>Case 信号</h3>
      <table>
        <thead><tr><th>case</th><th>baseline</th><th>candidate</th><th>signal</th></tr></thead>
        <tbody>{cases}</tbody>
      </table>
      <h3>证据路径</h3>
      {evidence_rows}
    </article>
"""


def _render_gate(gate: dict[str, Any]) -> str:
    status = str(gate.get("status") or "-")
    return (
        "<tr>"
        f"<td>{_escape(gate.get('name') or '-')}</td>"
        f"<td><span class=\"tag {_escape(status.lower())}\">{_escape(status)}</span></td>"
        f"<td>{_escape(gate.get('reason') or '-')}</td>"
        "</tr>"
    )


def _render_case(case: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{_escape(case.get('case_id') or '-')}</td>"
        f"<td>{_escape(case.get('baseline_status') or '-')}</td>"
        f"<td>{_escape(case.get('candidate_status') or '-')}</td>"
        f"<td>{_escape(case.get('decision_signal') or '-')}</td>"
        "</tr>"
    )


def _next_action(record: SupervisedDashboardRecord) -> str:
    if record.decision == "INCONCLUSIVE":
        return "这轮监督评测没有形成可用对比证据，先修正评测设置或用相同配置复跑。"
    if record.risk_level == "high":
        return "先检查失败 gate 和 Decision Record，不要继续 apply 或 activate。"
    if record.risk_level == "medium":
        return "继续观察成本、验证失败和 hold 原因，必要时扩大 case 覆盖。"
    if record.gym_proposal_status == "proposed":
        return "监督结论已给出 proposal，下一步可在 workbench 中手动 apply。"
    if record.gym_proposal_status == "applied":
        return "proposal 已 apply，下一步可 activate 成 advisory baseline，或直接 rollback。"
    if record.gym_proposal_status == "active":
        return "proposal 已成为 active advisory baseline；runtime_effect 仍为 not_applied，可继续观察或 rollback。"
    if record.gym_proposal_status == "rolled_back":
        return "proposal 已回滚，当前只保留审计证据。"
    if record.gym_proposal_status == "superseded":
        return "proposal 已被更新的 active proposal 替代，当前只需审计。"
    if record.decision == "PROMOTE":
        return "监督结论是 PROMOTE，但当前 proposal 证据不完整，先检查 Decision Record 和 Gym proposal。"
    return "保持观察，必要时用相同配置复跑。"


def _gym_action_label(record: SupervisedDashboardRecord) -> str:
    if not record.gym_available_actions:
        return "audit only"
    return ", ".join(record.gym_available_actions)


def _risk_label(level: str) -> str:
    return {
        "high": "高风险",
        "medium": "需观察",
        "low": "低风险",
        "none": "无记录",
    }.get(level, level)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


__all__ = [
    "SupervisedDashboardRecord",
    "SupervisedDashboardResult",
    "build_supervised_dashboard",
    "generate_supervised_dashboard",
    "load_dashboard_records",
]
