# -*- coding: utf-8 -*-
"""
沙盘生命周期测试 - 验证生命周期防断裂加固

此脚本不调用大模型，用于测试以下场景：
1. 模拟工具调用失败，检查状态机是否正确记录错误
2. 模拟调用 trigger_self_restart，检查 workspace/ 下的数据是否正确保存
3. 验证错误阻止机制是否生效

运行方式: python tests/simulate_lifecycle.py
"""

import os
import sys
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@contextmanager
def isolated_memory_index():
    """为沙盘测试提供隔离的 memory.json，避免污染真实 workspace 记忆。"""
    old_path = os.environ.get("VIBELUTION_MEMORY_INDEX_PATH")
    with tempfile.TemporaryDirectory() as tmpdir:
        isolated_path = Path(tmpdir) / "memory.json"
        os.environ["VIBELUTION_MEMORY_INDEX_PATH"] = str(isolated_path)
        try:
            yield isolated_path
        finally:
            if old_path is None:
                os.environ.pop("VIBELUTION_MEMORY_INDEX_PATH", None)
            else:
                os.environ["VIBELUTION_MEMORY_INDEX_PATH"] = old_path


def test_1_cli_error_detection():
    """测试1: CLI 命令错误检测"""
    print("\n" + "=" * 60)
    print("测试1: CLI 命令错误检测")
    print("=" * 60)

    from tools.shell_tools import execute_shell_command

    # 测试失败的命令
    result = execute_shell_command("python -c 'raise ValueError(\"test error\")'")

    has_failure_marker = "[EXEC FAILURE" in result
    print(f"  输入: python -c 'raise ValueError(\"test error\")'")
    print(f"  输出: {result[:80]}...")
    print(f"  [EXEC FAILURE] 标记: {'PASS' if has_failure_marker else 'FAIL'}")

    # 测试成功的命令
    result_ok = execute_shell_command("echo hello")
    has_warning = "[WARNING" in result_ok or "[EXEC FAILURE" in result_ok
    print(f"\n  输入: echo hello")
    print(f"  输出: {result_ok}")
    print(f"  无错误标记: {'PASS' if not has_warning else 'FAIL'}")

    return has_failure_marker


def test_2_memory_save():
    """测试2: 记忆保存功能"""
    print("\n" + "=" * 60)
    print("测试2: 记忆保存功能")
    print("=" * 60)

    from tools.memory_tools import force_save_current_state, _load_memory

    with isolated_memory_index() as memory_path:
        # 保存测试记忆
        test_wisdom = "沙盘测试: 记忆保存功能正常"
        test_goal = "沙盘测试: 验证记忆持久化"

        result = force_save_current_state(
            core_wisdom=test_wisdom,
            next_goal=test_goal,
        )

        print(f"  保存结果: {result}")
        print(f"  隔离记忆路径: {memory_path}")

        # 验证读取
        memory = _load_memory()
        print(f"  核心智慧: {memory.get('core_wisdom')}")
        print(f"  当前目标: {memory.get('current_goal')}")

        wisdom_ok = test_wisdom in memory.get("core_wisdom", "")
        goal_ok = test_goal in memory.get("current_goal", "")

        print(f"\n  记忆正确保存: {'PASS' if wisdom_ok and goal_ok else 'FAIL'}")

        return wisdom_ok and goal_ok


def test_3_restart_snapshot():
    """测试3: 重启前的强制快照"""
    print("\n" + "=" * 60)
    print("测试3: 重启前的强制快照")
    print("=" * 60)

    from tools.memory_tools import force_save_current_state

    with isolated_memory_index() as memory_path:
        # 模拟重启前的记忆快照
        snapshot_wisdom = "沙盘测试: 重启前快照成功"
        snapshot_goal = "沙盘测试: 验证重启流程"

        result = force_save_current_state(
            core_wisdom=snapshot_wisdom,
            next_goal=snapshot_goal,
        )

        print(f"  快照结果: {result}")

        exists = memory_path.exists()
        print(f"\n  记忆索引文件存在: {exists}")
        print(f"  路径: {memory_path}")

        if exists:
            with open(memory_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            print(f"  智慧: {data.get('core_wisdom')}")

            snapshot_ok = snapshot_wisdom in data.get("core_wisdom", "")
            print(f"\n  快照验证: {'PASS' if snapshot_ok else 'FAIL'}")
            return snapshot_ok

        return False


def test_4_workspace_structure():
    """测试4: 工作区与提示词控制面完整性"""
    print("\n" + "=" * 60)
    print("测试4: 工作区与提示词控制面完整性")
    print("=" * 60)

    from core.infrastructure.workspace_manager import get_workspace

    ws = get_workspace()

    checks = []

    # 检查目录
    for d in ["memory", "memory/archives", "prompts", "logs"]:
        path = ws.root / d
        exists = path.exists()
        checks.append(("目录 " + d, exists))
        print(f"  workspace/{d}: {'OK' if exists else 'MISSING'}")

    # 检查核心提示词控制面（当前项目真实布局）
    prompt_checks = [
        ("core/core_prompt/SOUL.md", PROJECT_ROOT / "core" / "core_prompt" / "SOUL.md"),
        ("core/core_prompt/SPEC.md", PROJECT_ROOT / "core" / "core_prompt" / "SPEC.md"),
        ("workspace/prompts", ws.root / "prompts"),
    ]
    for label, path in prompt_checks:
        exists = path.exists()
        content_ok = exists and (path.is_dir() or len(path.read_text(encoding="utf-8")) > 0)
        checks.append(("提示词 " + label, content_ok))
        print(f"  {label}: {'OK' if content_ok else 'MISSING'}")

    # 检查数据库
    db_exists = ws.db_path.exists()
    checks.append(("数据库", db_exists))
    print(f"  workspace/agent_brain.db: {'OK' if db_exists else 'MISSING'}")

    # 检查记忆索引
    mi_exists = ws.memory_index.exists()
    checks.append(("记忆索引", mi_exists))
    print(f"  workspace/memory/memory.json: {'OK' if mi_exists else 'MISSING'}")

    all_ok = all(c[1] for c in checks)
    print(f"\n  结构完整性: {'PASS' if all_ok else 'FAIL'}")

    return all_ok


def test_5_restart_bootstrap_path():
    """测试5: 重启后启动路径应绕开工作台，直接回到 agent 主线"""
    print("\n" + "=" * 60)
    print("测试5: 重启后启动路径")
    print("=" * 60)

    import agent as agent_module

    args = SimpleNamespace(
        test=False,
        prompt=None,
        auto=False,
        shell=False,
        no_shell=False,
    )

    old_reason = os.environ.get("AGENT_RESTART_REASON")
    os.environ["AGENT_RESTART_REASON"] = "sandbox_restart"
    try:
        should_launch = agent_module.should_launch_workbench(args, None)
        print(f"  AGENT_RESTART_REASON=sandbox_restart")
        print(f"  should_launch_workbench(...): {should_launch}")
        print(f"\n  启动路径校验: {'PASS' if not should_launch else 'FAIL'}")
        return should_launch is False
    finally:
        if old_reason is None:
            os.environ.pop("AGENT_RESTART_REASON", None)
        else:
            os.environ["AGENT_RESTART_REASON"] = old_reason


def main():
    """运行所有测试"""
    print("\n" + "#" * 60)
    print("# 沙盘生命周期测试")
    print("#" * 60)

    results = []

    try:
        results.append(("CLI错误检测", test_1_cli_error_detection()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("CLI错误检测", False))

    try:
        results.append(("记忆保存", test_2_memory_save()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("记忆保存", False))

    try:
        results.append(("重启快照", test_3_restart_snapshot()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("重启快照", False))

    try:
        results.append(("workspace结构", test_4_workspace_structure()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("workspace结构", False))

    try:
        results.append(("重启启动路径", test_5_restart_bootstrap_path()))
    except Exception as e:
        print(f"  [ERROR] {e}")
        results.append(("重启启动路径", False))

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: [{status}]")

    print(f"\n  通过: {passed}/{total}")

    if passed == total:
        print("\n  所有测试通过!")
        return 0
    else:
        print(f"\n  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
