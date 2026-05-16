# -*- coding: utf-8 -*-
"""
代码分析工具模块 - 整合自 code_tools.py 和 ast_tools.py

提供两大类工具：

## Diff 编辑工具 (code_tools)
- apply_diff_edit: 支持 SEARCH/REPLACE 块的精准代码替换
- validate_diff_format: 验证 diff 格式
- preview_diff: 预览修改效果

## AST 分析工具 (ast_tools)
- get_code_entity: 根据名称提取代码实体
- get_file_entities: 获取文件中所有实体
- list_file_entities: 列出文件中的所有实体

## 特性

Diff 编辑：
- 支持多种空白符差异
- 多块连续编辑
- 模糊匹配增强
- 详细的错误报告

AST 分析：
- 基于 Python 语法树精准提取
- 自动计算行号范围
- 支持嵌套实体（类中的方法）
- 处理装饰器和文档字符串
"""

import ast
import re
import os
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any


# ============================================================================
# 配置
# ============================================================================

# ============================================================================
# AST 实体提取器
# ============================================================================

class ASTEntityExtractor(ast.NodeVisitor):
    """AST 节点遍历器，用于提取代码实体"""

    def __init__(self):
        self.entities: Dict[str, List[Dict[str, Any]]] = {
            'class': [],
            'function': [],
            'async_function': [],
        }
        self.current_class = None

    def visit_ClassDef(self, node: ast.ClassDef):
        """提取类定义"""
        self.current_class = node.name
        class_info = self._extract_entity_info(node, 'class')
        class_info['methods'] = self._extract_class_methods(node)
        self.entities['class'].append(class_info)

        old_class = self.current_class
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """提取函数定义"""
        self.entities['function'].append(self._extract_entity_info(node, 'function'))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """提取异步函数定义"""
        self.entities['async_function'].append(self._extract_entity_info(node, 'async_function'))

    def _extract_entity_info(self, node: ast.AST, entity_type: str) -> Dict[str, Any]:
        """提取实体的基本信息"""
        info = {
            'type': entity_type,
            'name': node.name,
            'lineno': node.lineno,
            'end_lineno': node.end_lineno,
            'col_offset': node.col_offset,
            'end_col_offset': node.end_col_offset if hasattr(node, 'end_col_offset') else None,
            'decorators': [self._get_decorator_name(d) for d in getattr(node, 'decorator_list', [])],
            'docstring': ast.get_docstring(node),
        }
        if self.current_class:
            info['class_name'] = self.current_class
        return info

    def _extract_class_methods(self, node: ast.ClassDef) -> List[Dict[str, Any]]:
        """提取类中的所有方法"""
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_info = self._extract_entity_info(item, 'method')
                method_info['is_static'] = any(
                    self._get_decorator_name(d) == 'staticmethod'
                    for d in getattr(item, 'decorator_list', [])
                )
                method_info['is_classmethod'] = any(
                    self._get_decorator_name(d) == 'classmethod'
                    for d in getattr(item, 'decorator_list', [])
                )
                methods.append(method_info)
        return methods

    def _get_decorator_name(self, decorator: ast.AST) -> str:
        """获取装饰器名称"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        elif isinstance(decorator, ast.Call):
            return self._get_decorator_name(decorator.func)
        return 'unknown'


# ============================================================================
# AST 工具函数
# ============================================================================

def parse_file_ast(file_path: str) -> Optional[ast.Module]:
    """解析 Python 文件为 AST"""
    path = Path(file_path)
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            source = f.read()
        return ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        from core.logging import debug_logger; debug_logger.error(f"Failed to parse {file_path}: {e}")
        return None


def get_file_entities(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取文件中的所有实体（类和函数）

    Args:
        file_path: Python 文件路径

    Returns:
        包含所有实体的字典
    """
    tree = parse_file_ast(file_path)
    if tree is None:
        return {}

    extractor = ASTEntityExtractor()
    extractor.visit(tree)
    return extractor.entities


def get_code_entity(file_path: str, entity_name: str, include_imports: bool = False) -> str:
    """
    根据名称提取代码实体

    一击必中：直接提取类或函数的完整源代码。

    Args:
        file_path: Python 文件路径
        entity_name: 要提取的实体名称（类名或函数名或 "类名.方法名" 格式）
        include_imports: 是否包含文件的 import 语句

    Returns:
        实体代码文本，包含行号范围
    """
    path = Path(file_path)
    if not path.exists():
        return f"[AST] 错误: 文件不存在 - {file_path}"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return f"[AST] 错误: 无法读取文件（编码问题）- {file_path}"

    tree = parse_file_ast(file_path)
    if tree is None:
        return f"[AST] 错误: 无法解析 AST - {file_path}"

    # 解析类名.方法名格式
    target_class_name = None
    target_method_name = entity_name
    
    if '.' in entity_name:
        parts = entity_name.rsplit('.', 1)
        if len(parts) == 2 and parts[0][0].isupper():
            target_class_name = parts[0]
            target_method_name = parts[1]

    extractor = ASTEntityExtractor()
    extractor.visit(tree)

    target_entity = None

    if target_class_name:
        for entity in extractor.entities['class']:
            if entity['name'] == target_class_name:
                if 'methods' in entity:
                    for method in entity['methods']:
                        if method['name'] == target_method_name:
                            target_entity = method
                            break
                break
    
    if target_entity is None:
        for entity in extractor.entities['class']:
            if entity['name'] == target_method_name:
                target_entity = entity
                break

    if target_entity is None:
        for entity_list in [extractor.entities['function'], extractor.entities['async_function']]:
            for entity in entity_list:
                if entity['name'] == target_method_name:
                    target_entity = entity
                    break
            if target_entity:
                break

    if target_entity is None:
        return _search_entity_by_text(lines, entity_name, file_path, target_class_name, target_method_name)

    start_line = target_entity['lineno']
    decorators = target_entity.get('decorators') or []
    if decorators:
        decorator_count = len(decorators)
        start_line = max(1, start_line - decorator_count)
    end_line = target_entity['end_lineno']
    entity_lines = lines[start_line - 1:end_line]
    code = ''.join(entity_lines)

    result = [
        f"[AST] 实体: {target_entity['name']}",
        f"[AST] 类型: {target_entity['type']}" + (f" (方法)" if 'class_name' in target_entity else ""),
        f"[AST] 位置: 第 {start_line} - {end_line} 行",
    ]

    if target_entity.get('decorators'):
        result.append(f"[AST] 装饰器: {', '.join(target_entity['decorators'])}")

    if target_entity.get('docstring'):
        result.append(f"[AST] 文档:\n\"\"\"{target_entity['docstring']}\"\"\"")

    if include_imports:
        import_lines = [
            line for line in lines
            if line.strip().startswith('import ') or line.strip().startswith('from ')
        ]
        if import_lines:
            result.append(f"\n[AST] 导入:\n```python")
            result.append(''.join(import_lines).rstrip())
            result.append("```")

    result.append(f"\n[AST] 代码:\n```python")
    result.append(code.rstrip())
    result.append("```")

    return '\n'.join(result)


def _search_entity_by_text(lines: List[str], entity_name: str, file_path: str, 
                         target_class_name: str = None, target_method_name: str = None) -> str:
    """通过文本搜索实体（当 AST 解析失败时的备选方案）"""
    if target_class_name is None:
        patterns = [
            rf'^class\s+{re.escape(entity_name)}\s*[:(]',
            rf'^def\s+{re.escape(entity_name)}\s*\(',
            rf'^async\s+def\s+{re.escape(entity_name)}\s*\(',
        ]
        
        start_line = None
        end_line = None
        indent_level = None
        entity_type = "unknown"
        found_name = entity_name

        for i, line in enumerate(lines):
            for pattern in patterns:
                if re.match(pattern, line):
                    start_line = i
                    indent_level = len(line) - len(line.lstrip())
                    entity_type = "class" if "class" in pattern else "function"
                    break
            if start_line is not None:
                break

        if start_line is None:
            return f"[AST] 错误: 未找到实体 '{entity_name}' - {file_path}"
        
    else:
        class_pattern = rf'^class\s+{re.escape(target_class_name)}\s*[:(]'
        class_start = None
        class_indent = None
        
        for i, line in enumerate(lines):
            if re.match(class_pattern, line):
                class_start = i
                class_indent = len(line) - len(line.lstrip())
                break
        
        if class_start is None:
            return f"[AST] 错误: 未找到类 '{target_class_name}' - {file_path}"
        
        class_end = None
        for i in range(class_start + 1, len(lines)):
            line = lines[i]
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= class_indent:
                    class_end = i
                    break
        if class_end is None:
            class_end = len(lines)
        
        method_pattern = rf'^(\s*)def\s+{re.escape(target_method_name)}\s*\('
        method_start = None
        method_indent = None
        
        for i in range(class_start, class_end):
            match = re.match(method_pattern, lines[i])
            if match:
                method_start = i
                method_indent = len(match.group(1)) + len(lines[i]) - len(lines[i].lstrip())
                break
        
        if method_start is None:
            return f"[AST] 错误: 在类 '{target_class_name}' 中未找到方法 '{target_method_name}' - {file_path}"
        
        start_line = method_start
        indent_level = method_indent
        found_name = f"{target_class_name}.{target_method_name}"
        entity_type = "method"
        
        for i in range(method_start + 1, class_end):
            line = lines[i]
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent_level:
                    end_line = i
                    break
        else:
            end_line = class_end
        
        code = ''.join(lines[start_line:end_line])
        return (
            f"[AST] 实体: {found_name}\n"
            f"[AST] 类型: {entity_type} (方法)\n"
            f"[AST] 位置: 第 {start_line + 1} - {end_line} 行\n"
            f"\n[AST] 代码:\n```python\n{code.rstrip()}\n```"
        )

    for i in range(start_line + 1, len(lines)):
        line = lines[i]
        if line.strip():
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent_level:
                end_line = i
                break
    else:
        end_line = len(lines)

    code = ''.join(lines[start_line:end_line])

    return (
        f"[AST] 实体: {found_name}\n"
        f"[AST] 类型: {entity_type}\n"
        f"[AST] 位置: 第 {start_line + 1} - {end_line} 行\n"
        f"\n[AST] 代码:\n```python\n{code.rstrip()}\n```"
    )


def list_file_entities(file_path: str, entity_type: str = "all") -> str:
    """
    列出文件中的所有实体

    Args:
        file_path: Python 文件路径
        entity_type: 过滤类型 ('class', 'function', 'all')

    Returns:
        实体列表
    """
    entities = get_file_entities(file_path)

    if not entities:
        return f"[AST] 错误: 无法解析或文件为空 - {file_path}"

    result = [
        f"[AST] 文件: {file_path}",
        f"[AST] 概览:\n",
    ]

    all_entities = []
    if entity_type == "all" or entity_type is None:
        for cls in entities['class']:
            all_entities.append(('class', cls))
        for func in entities['function'] + entities['async_function']:
            all_entities.append(('function', func))
    elif entity_type == 'class':
        for cls in entities['class']:
            all_entities.append(('class', cls))
    elif entity_type == 'function':
        for func in entities['function'] + entities['async_function']:
            all_entities.append(('function', func))

    for etype, entity in all_entities:
        location = f"第 {entity['lineno']} 行"
        if 'class_name' in entity:
            location = f"{entity['class_name']}.{entity['name']} ({location})"

        doc = ""
        if entity.get('docstring'):
            doc = f" - {entity['docstring'][:50]}..."

        result.append(f"  {entity['name']} ({etype}) {location}{doc}")

        if etype == 'class' and entity.get('methods'):
            for method in entity['methods']:
                method_type = 'classmethod' if method.get('is_classmethod') else 'staticmethod' if method.get('is_static') else 'method'
                result.append(f"      └─ {method['name']} ({method_type}) 第 {method['lineno']} 行")

    return '\n'.join(result)


def extract_method_from_class(file_path: str, class_name: str, method_name: str) -> str:
    """从类中提取特定方法"""
    return get_code_entity(file_path, f"{class_name}.{method_name}")


def _find_match_position(content: str, search_block: str, allow_fuzzy: bool = False) -> Optional[Tuple[int, int]]:
    """
    在内容中查找匹配块的位置
    
    支持行级模糊匹配：
    - 忽略行首缩进差异
    - 忽略行尾空白
    - 允许关键行顺序匹配
    """
    lines = content.split('\n')
    search_lines_raw = search_block.split('\n')
    
    def _normalize_line(line: str) -> str:
        return line.strip()

    search_key_lines = [_normalize_line(l) for l in search_lines_raw if l.strip()]
    if not search_key_lines:
        return None
    
    search_len = len(search_key_lines)
    
    # 精确匹配
    for i in range(len(lines) - search_len + 1):
        match = True
        for j, search_line in enumerate(search_key_lines):
            content_line = _normalize_line(lines[i + j])
            if content_line != search_line:
                match = False
                break
        if match:
            start_line = i
            end_line = i + search_len
            start_pos = sum(len(lines[k]) + 1 for k in range(start_line))
            end_pos = sum(len(lines[k]) + 1 for k in range(end_line))
            return (start_pos, end_pos)
    
    # 模糊匹配
    if allow_fuzzy:
        for i in range(len(lines) - search_len * 2 + 1):
            matches = 0
            content_idx = i
            
            for search_line in search_key_lines:
                found = False
                for cj in range(content_idx, min(i + search_len * 2, len(lines))):
                    if _normalize_line(lines[cj]) == search_line:
                        matches += 1
                        content_idx = cj + 1
                        found = True
                        break
                if not found:
                    break
            
            if matches >= search_len * 0.8:
                start_line = i
                end_line = content_idx
                start_pos = sum(len(lines[k]) + 1 for k in range(start_line))
                end_pos = sum(len(lines[k]) + 1 for k in range(end_line))
                return (start_pos, end_pos)
    
    return None


def _parse_diff_blocks(diff_text: str) -> List[Tuple[str, str]]:
    """解析 diff_text 中的所有 SEARCH/REPLACE 块"""
    blocks = []
    
    # 格式1: <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE
    pattern1 = r'<<<<<<<\s*SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>\s*REPLACE'
    matches = list(re.finditer(pattern1, diff_text, re.DOTALL))
    
    if matches:
        for match in matches:
            search_block = match.group(1).strip()
            replace_block = match.group(2).strip()
            blocks.append((search_block, replace_block))
        return blocks
    
    # 格式2: <<<<<<< ... ======= ... >>>>>>>（无 SEARCH 标记）
    pattern2 = r'<<<<<<<\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>'
    matches = list(re.finditer(pattern2, diff_text, re.DOTALL))
    
    if matches:
        for match in matches:
            search_block = match.group(1).strip()
            replace_block = match.group(2).strip()
            blocks.append((search_block, replace_block))
        return blocks
    
    # 格式3: *** Begin Patch / *** Update File: ... / @@ ... / *** End Patch
    # 这种格式是旧系统用的，为向后兼容也支持
    # 结构：*** Begin Patch\n*** Update File: filename\n@@\n- old line\n+ new line\n*** End Patch
    # 提取所有 @@ 块中的 - 和 + 行
    # 找到每个 *** Update File 块
    update_blocks = re.findall(
        r'\*\*\*\s*Update File:.+?\n@@\s*\n(.*?)\n(?=\*\*\*|$)',
        diff_text, re.DOTALL
    )
    
    for block in update_blocks:
        lines = block.split('\n')
        old_lines = []
        new_lines = []

        def flush_current_block():
            if old_lines and new_lines:
                blocks.append(('\n'.join(old_lines), '\n'.join(new_lines)))
                old_lines.clear()
                new_lines.clear()

        for line in lines:
            if line.startswith('- '):
                if new_lines:
                    flush_current_block()
                old_lines.append(line[2:].strip())
            elif line.startswith('+ '):
                new_lines.append(line[2:].strip())
            else:
                flush_current_block()
        
        flush_current_block()
    
    return blocks


def _find_similar_snippet(content: str, search_block: str, context_lines: int = 5) -> str:
    """找到并返回最相似的代码片段"""
    if not search_block:
        return ""
    
    content_lines = content.split('\n')
    search_lines_raw = search_block.split('\n')
    
    search_key_lines = [l.rstrip() for l in search_lines_raw if l.strip()]
    if not search_key_lines:
        return ""
    
    best_match = None
    best_match_start = 0
    best_ratio = 0

    for i in range(len(content_lines)):
        snippet_lines = content_lines[i:i + len(search_key_lines)]
        if len(snippet_lines) < len(search_key_lines):
            break

        matches = 0
        for sl, cl in zip(search_key_lines, snippet_lines):
            if sl == cl.rstrip():
                matches += 1

        ratio = matches / len(search_key_lines)
        if ratio > best_ratio and ratio > 0.3:
            best_ratio = ratio
            best_match_start = i
            start = max(0, i - 1)
            end = min(len(content_lines), i + len(search_key_lines) + context_lines)
            best_match = content_lines[start:end]

    if best_match:
        preview_lines = []
        for idx, line in enumerate(best_match):
            line_num = start + idx + 1  # start is 0-indexed, line numbers are 1-indexed
            display_line = line if len(line) <= 80 else line[:77] + "..."
            preview_lines.append(f"  {line_num:>4}: {display_line}")
        return f"[提示] 文件中相似的代码:\n" + "\n".join(preview_lines)
    
    return ""


def _parse_patch_update_operations(diff_text: str) -> List[Tuple[str, str, str]]:
    """解析 *** Begin Patch 风格的多文件更新操作。"""
    text = (diff_text or "").strip()
    if not text.startswith("*** Begin Patch"):
        return []

    operations: List[Tuple[str, str, str]] = []
    current_file = None
    old_lines: List[str] = []
    new_lines: List[str] = []
    in_hunk = False

    def flush_current_block():
        if current_file and old_lines and new_lines:
            operations.append((current_file, "\n".join(old_lines), "\n".join(new_lines)))
            old_lines.clear()
            new_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if line == "*** Begin Patch":
            continue
        if line == "*** End Patch":
            flush_current_block()
            break
        if line.startswith("*** Update File: "):
            flush_current_block()
            current_file = line[len("*** Update File: "):].strip()
            in_hunk = False
            continue
        if line.strip() == "@@":
            flush_current_block()
            in_hunk = True
            continue
        if not in_hunk or current_file is None:
            continue
        if line.startswith("- "):
            if new_lines:
                flush_current_block()
            old_lines.append(line[2:].strip())
            continue
        if line.startswith("+ "):
            new_lines.append(line[2:].strip())
            continue

        flush_current_block()

    return operations


def apply_diff_edit(file_path: str, diff_text: str, allow_fuzzy: bool = False) -> str:
    """
    应用 Diff Block 编辑

    支持以下格式：
    <<<<<<< SEARCH
    old code line 1
    old code line 2
    =======
    new code line 1
    new code line 2
    >>>>>>> REPLACE

    可包含多个块连续替换。

    Args:
        file_path: 要编辑的文件路径
        diff_text: SEARCH/REPLACE 块文本
        allow_fuzzy: 是否允许模糊匹配

    Returns:
        操作结果描述
    """
    path = Path(file_path)
    if not path.exists():
        return f"[编辑] 错误: 文件不存在 - {file_path}"

    if not path.is_file():
        return f"[编辑] 错误: 路径不是文件 - {file_path}"

    patch_operations = _parse_patch_update_operations(diff_text)
    if patch_operations:
        changed_files = []
        base_dir = path.parent
        for target_file, search_block, replace_block in patch_operations:
            target_path = Path(target_file)
            if not target_path.is_absolute():
                target_path = base_dir / target_path
            result = apply_diff_edit(str(target_path), f"<<<<<<< SEARCH\n{search_block}\n=======\n{replace_block}\n>>>>>>> REPLACE", allow_fuzzy=allow_fuzzy)
            if result.startswith("[编辑] 错误"):
                return result
            changed_files.append(str(target_path))
        return f"[编辑] 成功修改 {len(changed_files)} 个文件"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return f"[编辑] 错误: 无法读取文件 - {e}"

    blocks = _parse_diff_blocks(diff_text)

    if not blocks:
        return (
            f"[编辑] 错误: 无法解析 diff_text\n"
            f"请确保使用正确的格式:\n"
            f"<<<<<<< SEARCH\n"
            f"要替换的旧代码\n"
            f"=======\n"
            f"新代码\n"
            f">>>>>>> REPLACE"
        )

    new_content = content
    changes_made = []

    for idx, (search_block, replace_block) in enumerate(blocks):
        search_display = search_block.strip()
        match_pos = _find_match_position(new_content, search_block, allow_fuzzy=False)

        if match_pos is None and allow_fuzzy:
            match_pos = _find_match_position(new_content, search_block, allow_fuzzy=True)

        if match_pos is None:
            match_pos = _find_match_position(new_content, search_block, allow_fuzzy=True)

        if match_pos is None:
            similar = _find_similar_snippet(new_content, search_block)
            return (
                f"[编辑] 错误: 在文件中找不到匹配的代码块\n\n"
                f"[搜索块内容 - 前200字符]:\n{search_display[:200]}...\n\n"
                f"{similar}\n\n"
                f"提示: 请确保 SEARCH 块的代码与文件中的完全一致（包括缩进）"
            )

        start_pos, end_pos = match_pos
        new_content = new_content[:start_pos] + replace_block + new_content[end_pos:]
        changes_made.append(f"块 {idx + 1}: 替换成功")

    try:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
    except Exception as e:
        return f"[编辑] 错误: 无法写入文件 - {e}"

    result = [f"[编辑] 成功修改 {file_path}"]
    result.append(f"共处理 {len(blocks)} 个块:")
    for change in changes_made:
        result.append(f"  {change}")

    return '\n'.join(result)


def validate_diff_format(diff_text: str) -> Tuple[bool, str]:
    """
    验证 diff_text 格式是否正确

    Args:
        diff_text: 要验证的 diff 文本

    Returns:
        (是否有效, 错误信息)
    """
    text = (diff_text or "").strip()
    if not text:
        return False, "diff 不能为空"

    if "***" in text:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "*** Begin Patch":
            return False, "格式错误: 缺少 *** Begin Patch"
        if lines[-1].strip() != "*** End Patch":
            return False, "格式错误: 缺少 *** End Patch"
        if not any(line.startswith("*** Update File: ") for line in lines):
            return False, "格式错误: 缺少 *** Update File: 行"
        if "@@" not in text:
            return False, "格式错误: 缺少 @@ hunk 标记"

        hunk_lines = []
        in_hunk = False
        for line in lines[1:-1]:
            if line.strip() == "@@":
                in_hunk = True
                continue
            if line.startswith("*** Update File: "):
                continue
            if in_hunk:
                hunk_lines.append(line)

        if not hunk_lines:
            return False, "格式错误: hunk 不能为空"
        if not any(line.startswith("- ") for line in hunk_lines):
            return False, "格式错误: hunk 缺少删除行"
        if not any(line.startswith("+ ") for line in hunk_lines):
            return False, "格式错误: hunk 缺少新增行"
        for line in hunk_lines:
            if not line.strip():
                continue
            if line.startswith(("- ", "+ ", "  ")):
                continue
            return False, "格式错误: hunk 行必须以 '+ '、'- ' 或双空格开头"

        return True, ""

    blocks = _parse_diff_blocks(diff_text)

    if not blocks:
        return False, "未找到有效的 SEARCH/REPLACE 块。请使用以下格式:\n<<<<<<< SEARCH\n...old code...\n=======\n...new code...\n>>>>>>> REPLACE"

    return True, ""


def preview_diff(file_path: str, diff_text: str) -> str:
    """
    预览 diff 效果（不实际修改文件）

    Args:
        file_path: 文件路径
        diff_text: diff 块

    Returns:
        预览结果
    """
    path = Path(file_path)
    if not path.exists():
        return f"[预览] 错误: 文件不存在 - {file_path}"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return f"[预览] 错误: 无法读取文件 - {e}"

    blocks = _parse_diff_blocks(diff_text)
    if not blocks:
        return "[预览] 错误: 无法解析 diff 块"

    lines = content.split('\n')
    result = ["[预览] Diff 效果:\n"]

    for idx, (search_block, replace_block) in enumerate(blocks):
        result.append(f"--- 块 {idx + 1} ---")

        match_pos = _find_match_position(content, search_block)
        if match_pos:
            start_line = content[:match_pos[0]].count('\n') + 1
            result.append(f"将替换第 {start_line} 行附近的代码:")
            result.append("- " + "\n- ".join(search_block.split('\n')[:5]))
            result.append("+ " + "\n+ ".join(replace_block.split('\n')[:5]))
        else:
            result.append("  未找到匹配位置")

        result.append("")

    return '\n'.join(result)


# ============================================================================
# 模块初始化
# ============================================================================

__all__ = [
    # AST 工具
    'get_code_entity',
    'list_file_entities',
    'list_file_entities_tool',
    'get_file_entities',
    'extract_method_from_class',
    # Diff 工具
    'apply_diff_edit',
    'apply_diff_edit_tool',
    'validate_diff_format',
    'validate_diff_format_tool',
    'preview_diff',
    # 工具注册
    'get_code_analysis_tools',
    'create_ast_tools',
    'create_code_tools',
]
