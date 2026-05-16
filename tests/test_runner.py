#!/usr/bin/env python3
"""
统一测试运行器 - 进化沙盒

在 Agent 执行 trigger_self_restart 之前，必须通过所有测试。
这确保自我进化不会破坏核心功能。

使用方法：
    python tests/test_runner.py              # 运行所有测试
    python tests/test_runner.py --verbose   # 详细输出
    python tests/test_runner.py --fast      # 跳过慢速测试

返回：
    0 = 所有测试通过，可以安全重启
    1 = 有测试失败，禁止重启
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


class TestRunner:
    """统一测试运行器"""
    __test__ = False

    TEST_MODULES = None  # Auto-discovered if None
    ENVIRONMENT_SMOKE_MODULES = [
        ("test_environment_doctor.py", "Environment Doctor"),
        ("test_environment_smoke.py", "Environment Smoke"),
    ]

    def _discover_test_modules(self) -> List[Tuple[str, str]]:
        """Auto-discover test files, excluding backups, runners, and utilities."""
        test_dir = PROJECT_ROOT / "tests"
        test_files = sorted(
            f for f in test_dir.glob("test_*.py")
            if f.name not in ("test_runner.py",)
        )
        return [
            (f.name, f.stem.replace("test_", "").replace("_", " ").title())
            for f in test_files
        ]

    def __init__(self, verbose: bool = False, fast: bool = False, environment_smoke: bool = False):
        self.verbose = verbose
        self.fast = fast
        self.environment_smoke = environment_smoke
        self.results: List[Dict] = []
        self.start_time = datetime.now()

    def build_pytest_command(self, *targets: str) -> List[str]:
        """构建统一的 pytest 调用命令。"""
        cmd = [
            sys.executable, "-m", "pytest",
            *targets,
            "-v" if self.verbose else "-q",
            "--tb=short",
            "--no-header",
            "-p", "no:warnings",
        ]

        if self.fast:
            cmd.extend(["-k", "not slow"])

        return cmd

    def run_module_tests(self, test_file: str, description: str) -> Tuple[bool, Dict]:
        """运行单个测试模块"""
        print(f"\n{'='*60}")
        print(f"📦 测试模块: {description}")
        print(f"{'='*60}")

        test_path = PROJECT_ROOT / "tests" / test_file

        if not test_path.exists():
            return False, {
                "module": test_file,
                "description": description,
                "status": "SKIP",
                "message": f"测试文件不存在: {test_path}",
            }

        # 构建 pytest 命令
        cmd = self.build_pytest_command(str(test_path))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=120,  # 2分钟超时
            )

            output = result.stdout + result.stderr

            # 解析结果 — 从 pytest 标准摘要行提取计数
            import re
            summary_match = re.search(
                r'(\d+)\s+passed,\s*(\d+)\s+failed(?:,\s*(\d+)\s+skipped)?',
                output
            )
            if summary_match:
                passed = int(summary_match.group(1))
                failed = int(summary_match.group(2))
                skipped = int(summary_match.group(3) or 0)
            else:
                # Fallback: use return code
                passed = 0 if result.returncode != 0 else 1
                failed = 1 if result.returncode != 0 else 0
                skipped = 0
            total = passed + failed + skipped

            success = result.returncode == 0

            print(output)

            return success, {
                "module": test_file,
                "description": description,
                "status": "PASS" if success else "FAIL",
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "total": total,
                "output": output if self.verbose else "",
            }

        except subprocess.TimeoutExpired:
            return False, {
                "module": test_file,
                "description": description,
                "status": "TIMEOUT",
                "message": "测试超时（>2分钟）",
            }
        except Exception as e:
            return False, {
                "module": test_file,
                "description": description,
                "status": "ERROR",
                "message": str(e),
            }

    def run_all_tests(self) -> bool:
        """运行所有测试"""
        print("="*60)
        print("🧪 自我进化沙盒 - 测试套件")
        print("="*60)
        print(f"项目目录: {PROJECT_ROOT}")
        print(f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"模式: {'详细' if self.verbose else '简洁'}{' (快速)' if self.fast else ''}")

        modules = self.TEST_MODULES or (
            self.ENVIRONMENT_SMOKE_MODULES if self.environment_smoke else self._discover_test_modules()
        )
        all_passed = True

        for test_file, description in modules:
            success, result = self.run_module_tests(test_file, description)
            self.results.append(result)

            if not success:
                all_passed = False

        return all_passed

    def print_summary(self) -> bool:
        """打印测试摘要"""
        elapsed = (datetime.now() - self.start_time).total_seconds()

        print("\n" + "="*60)
        print("📊 测试摘要")
        print("="*60)

        total_passed = 0
        total_failed = 0
        total_tests = 0

        for result in self.results:
            status_icon = {
                "PASS": "✅",
                "FAIL": "❌",
                "SKIP": "⏭️",
                "TIMEOUT": "⏰",
                "ERROR": "💥",
            }.get(result["status"], "❓")

            if result["status"] == "PASS":
                total_passed += result.get("passed", 0)
                total_failed += result.get("failed", 0)
                total_tests += result.get("total", 0)
            elif result["status"] == "FAIL":
                total_failed += 1
                total_tests += 1

            print(f"{status_icon} {result['description']}: {result['status']}")

            if result["status"] != "PASS":
                msg = result.get("message", "")
                if msg:
                    print(f"   └─ {msg}")

        print("-"*60)
        print(f"总计: {total_tests} 测试, {total_passed} 通过, {total_failed} 失败")
        print(f"耗时: {elapsed:.2f} 秒")
        print("="*60)

        return total_failed == 0

    def generate_report(self) -> str:
        """生成测试报告 JSON"""
        import json

        elapsed = (datetime.now() - self.start_time).total_seconds()

        total_passed = sum(r.get("passed", 0) for r in self.results)
        total_failed = sum(r.get("failed", 0) for r in self.results)

        report = {
            "timestamp": self.start_time.isoformat(),
            "elapsed_seconds": elapsed,
            "overall_status": "PASS" if all(r["status"] == "PASS" for r in self.results) else "FAIL",
            "summary": {
                "total_tests": total_passed + total_failed,
                "passed": total_passed,
                "failed": total_failed,
            },
            "modules": self.results,
        }

        return json.dumps(report, ensure_ascii=False, indent=2)


def check_evolution_ready() -> Tuple[bool, str]:
    """
    检查是否可以安全执行自我进化。

    在 Agent 调用 trigger_self_restart 之前必须调用此函数。

    Returns:
        (can_continue, message): 是否可以继续，以及原因
    """
    runner = TestRunner(verbose=False, fast=False)

    print("\n" + "="*60)
    print("🔬 进化前自检 - 正在验证代码完整性...")
    print("="*60)

    all_passed = runner.run_all_tests()
    summary_passed = runner.print_summary()

    if all_passed and summary_passed:
        report = runner.generate_report()
        return True, f"✅ 所有测试通过，可以安全进化\n{report}"
    else:
        failed_modules = [
            r["description"] for r in runner.results
            if r["status"] != "PASS"
        ]
        return False, f"❌ 测试失败，禁止进化\n失败模块: {', '.join(failed_modules)}"


def run_environment_smoke(verbose: bool = False) -> Tuple[bool, str]:
    """运行稳定环境 smoke 套件。"""
    runner = TestRunner(verbose=verbose, fast=False, environment_smoke=True)
    all_passed = runner.run_all_tests()
    summary_passed = runner.print_summary()
    if all_passed and summary_passed:
        return True, "✅ 环境 smoke 验证通过"
    return False, "❌ 环境 smoke 验证失败"


def test_runner_builds_pytest_module_command():
    runner = TestRunner(verbose=False, fast=False, environment_smoke=True)
    cmd = runner.build_pytest_command("tests/test_environment_smoke.py")

    assert cmd[:3] == [sys.executable, "-m", "pytest"]
    assert "tests/test_environment_smoke.py" in cmd


def test_runner_environment_smoke_targets_are_stable():
    runner = TestRunner(environment_smoke=True)

    assert runner.ENVIRONMENT_SMOKE_MODULES == [
        ("test_environment_doctor.py", "Environment Doctor"),
        ("test_environment_smoke.py", "Environment Smoke"),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自我进化测试运行器")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    parser.add_argument("--fast", action="store_true", help="跳过慢速测试")
    parser.add_argument("--environment-smoke", action="store_true", help="只运行稳定环境 smoke 套件")
    args = parser.parse_args()

    runner = TestRunner(
        verbose=args.verbose,
        fast=args.fast,
        environment_smoke=args.environment_smoke,
    )

    # 运行所有测试
    runner.run_all_tests()
    summary_passed = runner.print_summary()

    # 输出报告
    if runner.verbose:
        print("\n📄 完整报告:")
        print(runner.generate_report())

    # 退出码
    sys.exit(0 if summary_passed else 1)
