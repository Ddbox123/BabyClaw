"""CLI entrypoint for the runtime manager."""

from __future__ import annotations

import argparse
import json
import sys

from .command_queue import submit_command, wait_for_result
from .daemon import ensure_daemon_running, is_daemon_running, load_runtime_snapshot, run_daemon


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vibelution runtime manager")
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("daemon", help="Run the background runtime-manager daemon")

    command_parser = subparsers.add_parser("command", help="Submit a runtime-manager command")
    command_parser.add_argument("command_type")
    command_parser.add_argument("--requested-by", default="cli")
    command_parser.add_argument("--reason", default="")
    command_parser.add_argument("--no-browser", action="store_true")
    command_parser.add_argument("--wait", action="store_true")
    command_parser.add_argument("--timeout", type=float, default=45.0)
    command_parser.add_argument("--json", action="store_true", dest="json_output")

    status_parser = subparsers.add_parser("status", help="Show the current runtime-manager snapshot")
    status_parser.add_argument("--json", action="store_true", dest="json_output")

    return parser


def _print_status(snapshot: dict) -> None:
    workbench = snapshot.get("workbench") or {}
    print(f"Mode      : runtime_manager")
    print(f"Project   : {snapshot.get('projectRoot') or ''}")
    print(f"Manager   : {'running' if snapshot.get('daemonRunning') else 'stopped'} (PID={snapshot.get('managerPid') or 0})")
    print(
        f"Workbench : {workbench.get('observedState') or 'closed'} "
        f"(desired={workbench.get('desiredState') or 'closed'}, phase={workbench.get('phase') or 'steady'})"
    )
    backend_pid = int(workbench.get("backendPid") or 0)
    browser_pid = int(workbench.get("browserWindowPid") or 0)
    print(f"Backend   : {'running' if backend_pid else 'stopped'} (PID={backend_pid or '-'})")
    print(f"Browser   : {'running' if browser_pid else 'stopped'} (window PID={browser_pid or '-'})")
    print(f"URL       : {workbench.get('url') or ''}")
    print(f"State     : {snapshot.get('statePath') or ''}")
    runtime_manager = snapshot.get("runtimeManager") if isinstance(snapshot.get("runtimeManager"), dict) else {}
    if runtime_manager and runtime_manager.get("sourceMatches") is False:
        print("Manager   : source changed; next command will restart the runtime manager")
    if workbench.get("failureMessage"):
        print(f"Error     : {workbench.get('failureMessage')}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.action == "daemon":
        run_daemon()
        return 0

    if args.action == "command":
        ensure_daemon_running()
        payload_args = {}
        if getattr(args, "reason", ""):
            payload_args["reason"] = args.reason
        if getattr(args, "no_browser", False):
            payload_args["noBrowser"] = True

        command = submit_command(args.command_type, args=payload_args, requested_by=args.requested_by)
        if not args.wait:
            output = {
                "accepted": True,
                "completed": False,
                "commandId": command["commandId"],
            }
            if args.json_output:
                print(json.dumps(output, ensure_ascii=False))
            else:
                print(f"Queued runtime-manager command {command['commandId']} ({args.command_type}).")
            return 0

        try:
            result = wait_for_result(command["commandId"], timeout_seconds=args.timeout)
        except TimeoutError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(result.get("message") or f"Completed runtime-manager command {command['commandId']}.")
        return 0 if result.get("ok") else 1

    snapshot = load_runtime_snapshot()
    snapshot["projectRoot"] = str(snapshot.get("projectRoot") or "")
    snapshot["statePath"] = str(snapshot.get("statePath") or "")
    if args.json_output:
        print(json.dumps(snapshot, ensure_ascii=False))
    else:
        _print_status(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
