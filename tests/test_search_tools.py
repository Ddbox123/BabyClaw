#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索工具完整测试套件

测试 tools/search_tools.py 中的所有功能：
- 全局正则搜索（grep_search_tool）
- 函数调用查找（find_function_calls_tool）
- 符号定义查找（find_definitions_tool）
- Import 语句搜索（search_imports_tool）
- 搜索并读取（search_and_read_tool）
"""

import os
import sys
import pytest
import tempfile
import shutil
import re
from pathlib import Path
from datetime import datetime

from tools.search_tools import (
    grep_search_tool,
    find_function_calls_tool,
    find_definitions_tool,
    search_imports_tool,
    search_and_read_tool,
)


# ============================================================================
# 测试辅助函数和数据
# ============================================================================

SAMPLE_PY_CONTENT = '''
#!/usr/bin/env python3
"""
示例模块 - 用于测试搜索工具
"""

import os
import sys
from typing import List, Optional

# 全局变量
CONSTANT_VALUE = 42
ANOTHER_CONSTANT = "hello"

def helper_function(arg1, arg2=None):
    """辅助函数"""
    return arg1 + (arg2 or 0)

class SampleClass:
    """示例类"""
    
    def __init__(self, name):
        self.name = name
        self._private_field = "secret"
    
    def public_method(self, x):
        """公开方法"""
        result = helper_function(x, 10)
        return result
    
    def _private_method(self):
        """私有方法"""
        return self._private_field
    
    @classmethod
    def class_method(cls):
        """类方法"""
        return "class method"

def another_function():
    """另一个函数"""
    x = helper_function(5)
    obj = SampleClass("test")
    obj.public_method(10)
    return x

# 模块级调用
result = another_function()
'''

SAMPLE_JS_CONTENT = '''
// 示例 JavaScript 文件
import React from 'react';
import { useState, useEffect } from 'react';
const axios = require('axios');

function component() {
    const [state, setState] = useState(null);
    helperFunction();
    return <div>Hello</div>;
}

function helperFunction() {
    console.log("helper");
}
'''

SAMPLE_MD_CONTENT = '''
# 测试文档

## 概述

这是用于测试搜索工具的文档。

## 使用方法

调用 `grep_search_tool` 进行搜索。

## 示例代码

```python
def test_function():
    return "test"
```

## 参考

更多信息请查看官方文档。
'''


@pytest.fixture
def temp_test_dir():
    """创建临时测试目录"""
    temp_dir = tempfile.mkdtemp(prefix="search_test_")
    yield temp_dir
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_project(temp_test_dir):
    """创建示例项目结构"""
    # 创建 Python 文件
    py_dir = os.path.join(temp_test_dir, "python_modules")
    os.makedirs(py_dir)
    
    py_file1 = os.path.join(py_dir, "module1.py")
    with open(py_file1, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_PY_CONTENT)
    
    py_file2 = os.path.join(py_dir, "module2.py")
    with open(py_file2, 'w', encoding='utf-8') as f:
        f.write('''
def standalone_function():
    """独立函数"""
    pass

class StandaloneClass:
    pass
''')
    
    # 创建 JavaScript 文件
    js_dir = os.path.join(temp_test_dir, "js")
    os.makedirs(js_dir)
    js_file = os.path.join(js_dir, "component.jsx")
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_JS_CONTENT)
    
    # 创建 Markdown 文档
    docs_dir = os.path.join(temp_test_dir, "docs")
    os.makedirs(docs_dir)
    md_file = os.path.join(docs_dir, "guide.md")
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_MD_CONTENT)
    
    # 创建嵌套目录
    nested_dir = os.path.join(py_dir, "nested", "deep")
    os.makedirs(nested_dir)
    nested_file = os.path.join(nested_dir, "deep_module.py")
    with open(nested_file, 'w', encoding='utf-8') as f:
        f.write('def deep_function():\n    pass\n')
    
    return temp_test_dir


# ============================================================================
# grep_search_tool 测试
# ============================================================================

class TestGrepSearch:
    """grep_search_tool 测试"""

    def test_search_simple_pattern(self, sample_project):
        """测试简单正则搜索"""
        result = grep_search_tool(
            regex_pattern="helper_function",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert ".py" in result
        assert "[搜索摘要]" in result
        assert "[续读]" in result

    def test_search_with_context(self, sample_project):
        """测试带上下文的搜索"""
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            context_lines=2
        )
        assert "SampleClass" in result
        # 应包含上下文行
        assert len(result.split('\n')) > 1

    def test_search_case_insensitive(self, sample_project):
        """测试不区分大小写搜索"""
        result = grep_search_tool(
            regex_pattern="HELPER_FUNCTION",
            include_ext=".py",
            search_dir=sample_project,
            case_sensitive=False
        )
        assert "helper_function" in result or "HELPER" in result

    def test_search_multiple_extensions(self, sample_project):
        """测试多扩展名搜索"""
        result = grep_search_tool(
            regex_pattern="import",
            include_ext="*",  # 所有支持的扩展名
            search_dir=sample_project
        )
        assert "import" in result
        assert ".py" in result
        assert ".js" in result or ".md" in result

    def test_search_with_max_results(self, sample_project):
        """测试结果数量限制"""
        result = grep_search_tool(
            regex_pattern="def ",
            include_ext=".py",
            search_dir=sample_project,
            max_results=2
        )
        # 结果不应超过限制
        assert "[搜索] 找到 2 个匹配" in result

    def test_search_nonexistent_dir(self):
        """测试不存在的目录"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir="/nonexistent/path/xyz"
        )
        assert ("错误" in result or "不存在" in result or 
                "error" in result.lower() or "not found" in result.lower())

    def test_search_empty_pattern(self):
        """测试空正则表达式"""
        result = grep_search_tool(
            regex_pattern="",
            include_ext=".py",
            search_dir="."
        )
        assert "错误" in result or "不能为空" in result or "empty" in result.lower()

    def test_search_invalid_regex(self):
        """测试无效正则表达式"""
        result = grep_search_tool(
            regex_pattern="[invalid(",
            include_ext=".py",
            search_dir="."
        )
        assert ("错误" in result or "无效" in result or 
                "invalid" in result.lower())

    def test_search_skips_hidden_dirs(self, sample_project):
        """测试跳过隐藏目录"""
        # 创建 .git 目录（应被跳过）
        git_dir = os.path.join(sample_project, ".git")
        os.makedirs(git_dir)
        git_file = os.path.join(git_dir, "config")
        with open(git_file, 'w') as f:
            f.write("git config content")
        
        result = grep_search_tool(
            regex_pattern="git",
            include_ext="*",
            search_dir=sample_project
        )
        # 应该找不到 .git 中的内容
        assert "git config" not in result or ".git" not in result

    def test_search_skips_large_files(self, sample_project):
        """测试跳过超大文件"""
        # 创建大于 10MB 的文件
        large_dir = os.path.join(sample_project, "large")
        os.makedirs(large_dir)
        large_file = os.path.join(large_dir, "huge.txt")
        with open(large_file, 'w') as f:
            f.write("x" * (11 * 1024 * 1024))  # 11 MB
        
        result = grep_search_tool(
            regex_pattern="x+",
            include_ext=".txt",
            search_dir=sample_project
        )
        # 大文件应被跳过，不包含在结果中
        assert "huge.txt" not in result

    def test_search_single_file_mode(self, sample_project):
        """测试单文件模式"""
        py_file = os.path.join(sample_project, "python_modules", "module1.py")
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=py_file  # 传入文件路径而非目录
        )
        assert "SampleClass" in result or "module1.py" in result


# ============================================================================
# find_function_calls_tool 测试
# ============================================================================

class TestFindFunctionCalls:
    """find_function_calls_tool 测试"""

    def test_find_builtin_function_calls(self, sample_project):
        """测试查找内置函数调用"""
        result = find_function_calls_tool(
            function_name="print",
            search_dir=sample_project
        )
        # 示例中没有 print，应返回空
        assert isinstance(result, str)
        assert "未找到" in result or "0 处" in result or "not found" in result.lower()

    def test_find_custom_function_calls(self, sample_project):
        """测试查找自定义函数调用"""
        result = find_function_calls_tool(
            function_name="helper_function",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "module1.py" in result

    def test_find_method_calls(self, sample_project):
        """测试查找方法调用"""
        result = find_function_calls_tool(
            function_name="public_method",
            search_dir=sample_project
        )
        assert "public_method" in result
        assert "调用" in result or "call" in result.lower()

    def test_find_nonexistent_function(self, sample_project):
        """测试查找不存在的函数"""
        result = find_function_calls_tool(
            function_name="nonexistent_function_xyz_12345",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 处" in result or 
                "not found" in result.lower())

    def test_find_function_with_syntax_error_file(self, temp_test_dir):
        """测试包含语法错误文件的情况"""
        bad_file = os.path.join(temp_test_dir, "bad.py")
        with open(bad_file, 'w') as f:
            f.write("def broken(\n    pass\n")  # 语法错误
        
        result = find_function_calls_tool(
            function_name="test",
            search_dir=temp_test_dir
        )
        # 应该能容错，不崩溃
        assert isinstance(result, str)

    def test_find_function_in_nested_dirs(self, sample_project):
        """测试在嵌套目录中查找"""
        result = find_function_calls_tool(
            function_name="deep_function",
            search_dir=sample_project
        )
        assert "deep_function" in result
        assert "nested" in result or "deep" in result


# ============================================================================
# find_definitions_tool 测试
# ============================================================================

class TestFindDefinitions:
    """find_definitions_tool 测试"""

    def test_find_function_definition(self, sample_project):
        """测试查找函数定义"""
        result = find_definitions_tool(
            symbol_name="helper_function",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "def helper_function" in result or "定义" in result

    def test_find_class_definition(self, sample_project):
        """测试查找类定义"""
        result = find_definitions_tool(
            symbol_name="SampleClass",
            search_dir=sample_project
        )
        assert "SampleClass" in result
        assert "class SampleClass" in result or "类" in result

    def test_find_variable_definition(self, sample_project):
        """测试查找变量定义"""
        result = find_definitions_tool(
            symbol_name="CONSTANT_VALUE",
            search_dir=sample_project
        )
        assert "CONSTANT_VALUE" in result

    def test_find_standalone_class(self, sample_project):
        """测试查找独立类"""
        result = find_definitions_tool(
            symbol_name="StandaloneClass",
            search_dir=sample_project
        )
        assert "StandaloneClass" in result
        assert "module2.py" in result

    def test_find_nonexistent_symbol(self, sample_project):
        """测试查找不存在的符号"""
        result = find_definitions_tool(
            symbol_name="NonexistentSymbol_XYZ",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 个" in result or 
                "not found" in result.lower())

    def test_find_method_inside_class(self, sample_project):
        """测试查找类内方法"""
        result = find_definitions_tool(
            symbol_name="public_method",
            search_dir=sample_project
        )
        assert "public_method" in result
        assert "SampleClass" in result

    def test_find_private_member(self, sample_project):
        """测试查找私有成员"""
        result = find_definitions_tool(
            symbol_name="_private_method",
            search_dir=sample_project
        )
        assert "_private_method" in result


# ============================================================================
# search_imports_tool 测试
# ============================================================================

class TestSearchImports:
    """search_imports_tool 测试"""

    def test_search_standard_import(self, sample_project):
        """测试标准 import 语句"""
        result = search_imports_tool(
            module_name="os",
            search_dir=sample_project
        )
        assert "import os" in result or "os" in result

    def test_search_from_import(self, sample_project):
        """测试 from...import 语句"""
        result = search_imports_tool(
            module_name="typing",
            search_dir=sample_project
        )
        assert "from typing import" in result or "typing" in result

    def test_search_third_party_import(self, sample_project):
        """测试第三方包导入"""
        result = search_imports_tool(
            module_name="react",
            search_dir=sample_project
        )
        assert "react" in result.lower()
        assert ".js" in result

    def test_search_import_nonexistent(self, sample_project):
        """测试搜索不存在的导入"""
        result = search_imports_tool(
            module_name="nonexistent_module_xyz_12345",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 处" in result or 
                "not found" in result.lower())

    def test_search_import_partial_match(self, sample_project):
        """测试部分匹配（应精确匹配）"""
        result = search_imports_tool(
            module_name="react",  # 搜索精确的 "react"
            search_dir=sample_project
        )
        # 应匹配到 import React 和 from 'react'
        assert "react" in result.lower()

    def test_search_import_in_nested_dirs(self, sample_project):
        """测试在嵌套目录搜索导入"""
        result = search_imports_tool(
            module_name="react",
            search_dir=sample_project
        )
        assert "js" in result or "component" in result

    def test_search_import_with_alias(self, sample_project):
        """测试带别名的导入"""
        # 创建带别名的导入
        alias_file = os.path.join(sample_project, "alias.py")
        with open(alias_file, 'w') as f:
            f.write("import numpy as np\nimport pandas as pd\n")
        
        result = search_imports_tool(
            module_name="numpy",
            search_dir=sample_project
        )
        assert "numpy" in result
        assert "np" in result


# ============================================================================
# search_and_read_tool 测试
# ============================================================================

class TestSearchAndRead:
    """search_and_read_tool 测试"""

    def test_search_and_read_simple(self, sample_project):
        """测试搜索并读取"""
        result = search_and_read_tool(
            search_pattern="helper_function",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "module1.py" in result
        # 应包含文件内容片段
        assert "def helper_function" in result or "辅助函数" in result

    def test_search_and_read_with_context(self, sample_project):
        """测试带上下文的搜索并读取"""
        result = search_and_read_tool(
            search_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            context_lines=3
        )
        assert "SampleClass" in result
        # 应包含定义和上下文
        assert "class SampleClass" in result or "示例类" in result

    def test_search_and_read_js_files(self, sample_project):
        """测试搜索 JavaScript 文件"""
        result = search_and_read_tool(
            search_pattern="useState",
            include_ext=".js",
            search_dir=sample_project
        )
        assert "useState" in result
        assert "component.jsx" in result

    def test_search_and_read_md_files(self, sample_project):
        """测试搜索 Markdown 文件"""
        result = search_and_read_tool(
            search_pattern="使用方法",
            include_ext=".md",
            search_dir=sample_project
        )
        assert "使用方法" in result or "使用" in result

    def test_search_and_read_max_results(self, sample_project):
        """测试结果数限制"""
        result = search_and_read_tool(
            search_pattern="def ",
            include_ext=".py",
            search_dir=sample_project,
            max_results=2
        )
        # 结果应有限制
        assert "[搜索读取完成] 共 2 处匹配" in result

    def test_search_and_read_nonexistent_pattern(self, sample_project):
        """测试搜索不存在的模式"""
        result = search_and_read_tool(
            search_pattern="xyz_nonexistent_pattern_12345",
            include_ext=".py",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 个" in result or 
                "not found" in result.lower())


# ============================================================================
# 跨工具集成测试
# ============================================================================

class TestSearchIntegration:
    """搜索工具集成测试"""

    def test_full_search_workflow(self, sample_project):
        """测试完整搜索工作流"""
        # 1. 搜索函数调用
        calls = find_function_calls_tool("helper_function", sample_project)
        assert "helper_function" in calls
        
        # 2. 搜索函数定义
        defs = find_definitions_tool("helper_function", sample_project)
        assert "helper_function" in defs
        
        # 3. 全局 grep
        greps = grep_search_tool("helper_function", ".py", sample_project)
        assert "helper_function" in greps
        
        # 4. 搜索并读取
        read = search_and_read_tool("helper_function", ".py", sample_project)
        assert "helper_function" in read

    def test_search_across_extensions(self, sample_project):
        """测试跨扩展名搜索"""
        # 搜索 "import" 应在所有文件类型中找到
        result = grep_search_tool("import", "*", sample_project)
        assert "import" in result
        assert ".py" in result
        assert ".js" in result

    def test_function_vs_definition_consistency(self, sample_project):
        """测试函数调用与定义的一致性"""
        func_name = "public_method"
        
        calls = find_function_calls_tool(func_name, sample_project)
        defs = find_definitions_tool(func_name, sample_project)
        
        # 两者都应找到
        assert func_name in calls
        assert func_name in defs

    def test_import_search_consistency(self, sample_project):
        """测试导入搜索一致性"""
        module = "os"
        imports = search_imports_tool(module, sample_project)
        assert "os" in imports


# ============================================================================
# 特殊场景测试
# ============================================================================

class TestSpecialScenarios:
    """特殊场景测试"""

    def test_search_in_file_with_unicode(self, sample_project):
        """测试搜索包含 Unicode 的文件"""
        # 创建 Unicode 文件
        unicode_file = os.path.join(sample_project, "unicode.py")
        with open(unicode_file, 'w', encoding='utf-8') as f:
            f.write('''# 中文注释
def 中文函数():
    """中文函数"""
    return "中文结果"
''')
        
        result = grep_search_tool(
            regex_pattern="中文函数",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "中文函数" in result

    def test_search_in_empty_directory(self, temp_test_dir):
        """测试搜索空目录"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir=temp_test_dir
        )
        assert ("未找到" in result or "0 个" in result or 
                "empty" in result.lower())

    def test_search_very_long_line(self, sample_project):
        """测试超长行文件"""
        long_file = os.path.join(sample_project, "long.py")
        long_line = "x = " + "a" * 10000 + "\n"
        with open(long_file, 'w') as f:
            f.write(long_line)
            f.write("def short():\n    pass\n")
        
        result = grep_search_tool(
            regex_pattern="short",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "short" in result

    def test_search_with_special_regex_chars(self, sample_project):
        """测试特殊正则字符转义"""
        # 创建包含特殊正则字符的文件
        special_file = os.path.join(sample_project, "special.py")
        with open(special_file, 'w') as f:
            f.write("price = $100 [special]\n")
        
        # 搜索特殊字符（需要转义）
        result = grep_search_tool(
            regex_pattern=r"\$100",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "$100" in result or "100" in result


# ============================================================================
# 性能测试
# ============================================================================

class TestSearchPerformance:
    """搜索性能测试"""

    def test_grep_search_performance(self, sample_project):
        """测试 grep 搜索性能"""
        import time
        
        # 创建大量文件
        for i in range(100):
            file_path = os.path.join(sample_project, f"perf_test_{i}.py")
            with open(file_path, 'w') as f:
                f.write(f"def func_{i}():\n    return {i}\n" * 10)
        
        start = time.time()
        result = grep_search_tool(
            regex_pattern="def func_",
            include_ext=".py",
            search_dir=sample_project,
            max_results=200
        )
        elapsed = time.time() - start
        
        assert elapsed < 10.0  # 应在 10 秒内完成
        assert len(result) > 0

    def test_find_function_calls_performance(self, sample_project):
        """测试查找函数调用性能"""
        import time
        
        start = time.time()
        result = find_function_calls_tool(
            function_name="helper_function",
            search_dir=sample_project
        )
        elapsed = time.time() - start
        
        assert elapsed < 5.0

    def test_search_and_read_performance(self):
        """测试搜索并读取性能"""
        import time
        
        # 在项目根目录搜索
        project_root = os.path.dirname(os.path.dirname(__file__))
        
        start = time.time()
        result = search_and_read_tool(
            search_pattern="def ",
            include_ext=".py",
            search_dir=project_root,
            max_results=50
        )
        elapsed = time.time() - start
        
        assert elapsed < 15.0  # 应在 15 秒内完成


# ============================================================================
# 安全测试
# ============================================================================

class TestSearchSecurity:
    """搜索安全测试"""

    def test_regex_denial_of_service_protected(self):
        """测试正则表达式 DoS 防护"""
        # 灾难性回溯正则表达式
        catastrophic_regex = r'(a+)+b'
        
        result = grep_search_tool(
            regex_pattern=catastrophic_regex,
            include_ext=".py",
            search_dir="."
        )
        # 应该被 re 模块捕获或超时处理
        assert ("错误" in result or "无效" in result or 
                "timeout" in result.lower() or "invalid" in result.lower())

    def test_path_traversal_in_search_dir(self):
        """测试路径遍历攻击"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir="..\\..\\..\\Windows\\System32"
        )
        # 应该被拒绝（路径不在项目中或不存在）
        assert ("错误" in result or "不存在" in result or 
                "not found" in result.lower())

    def test_search_does_not_write_files(self, sample_project):
        """测试搜索不写入文件"""
        # 搜索前后文件系统应只读
        import hashlib
        
        def get_dir_hash(path):
            """计算目录哈希"""
            hashes = []
            for root, dirs, files in os.walk(path):
                for file in sorted(files):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'rb') as f:
                            file_hash = hashlib.md5(f.read()).hexdigest()
                            hashes.append((filepath, file_hash))
                    except:
                        pass
            return sorted(hashes)
        
        before = get_dir_hash(sample_project)
        
        # 执行多次搜索
        for _ in range(5):
            grep_search_tool("helper_function", ".py", sample_project)
        
        after = get_dir_hash(sample_project)
        
        # 哈希应相同（无文件修改）
        assert before == after


# ============================================================================
# 返回值格式测试
# ============================================================================

class TestReturnFormats:
    """返回值格式测试"""

    def test_grep_returns_formatted_string(self, sample_project):
        """测试 grep 返回格式化字符串"""
        result = grep_search_tool("def", ".py", sample_project)
        assert isinstance(result, str)
        # 应包含文件路径和匹配行
        assert ":" in result  # file:line:content 格式

    def test_find_calls_returns_structured(self, sample_project):
        """测试函数调用返回结构化"""
        result = find_function_calls_tool("helper_function", sample_project)
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_find_defs_returns_structured(self, sample_project):
        """测试定义查找返回结构化"""
        result = find_definitions_tool("SampleClass", sample_project)
        assert isinstance(result, str)
        assert "SampleClass" in result

    def test_search_imports_returns_structured(self, sample_project):
        """测试导入搜索返回结构化"""
        result = search_imports_tool("os", sample_project)
        assert isinstance(result, str)
        assert "import" in result or "os" in result

    def test_search_and_read_includes_content(self, sample_project):
        """测试搜索并读取包含内容"""
        result = search_and_read_tool("public_method", ".py", sample_project)
        assert isinstance(result, str)
        # 应包含文件内容片段
        assert len(result) > 100  # 内容应足够丰富


# ============================================================================
# 参数组合测试
# ============================================================================

class TestParameterCombinations:
    """参数组合测试"""

    def test_case_sensitive_off_with_special_chars(self, sample_project):
        """测试不区分大小写 + 特殊字符"""
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            case_sensitive=False
        )
        assert "SampleClass" in result

    def test_max_results_with_large_resultset(self, sample_project):
        """测试大结果集限制"""
        # 创建大量匹配的文件
        for i in range(200):
            file_path = os.path.join(sample_project, f"many_{i}.py")
            with open(file_path, 'w') as f:
                f.write("def target():\n    pass\n")
        
        result = grep_search_tool(
            regex_pattern="def target",
            include_ext=".py",
            search_dir=sample_project,
            max_results=50
        )
        # 应只返回 50 个结果
        assert result.count("target") <= 50

    def test_nested_directory_search(self, sample_project):
        """测试嵌套目录递归搜索"""
        result = grep_search_tool(
            regex_pattern="deep_function",
            include_ext=".py",
            search_dir=sample_project,
            recursive=True
        )
        assert "deep_function" in result
        assert "nested" in result

    def test_max_output_chars_is_respected(self, sample_project):
        for i in range(12):
            file_path = os.path.join(sample_project, f"preview_{i}.py")
            with open(file_path, "w", encoding="utf-8") as f:
                for j in range(20):
                    f.write(f"def preview_target_{i}_{j}():\n    return 'demo'\n")

        result = grep_search_tool(
            regex_pattern="preview_target",
            include_ext=".py",
            search_dir=sample_project,
            max_results=30,
            max_output_chars=1500,
        )

        assert "[续读]" in result
        assert result.count("📁 ") <= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
