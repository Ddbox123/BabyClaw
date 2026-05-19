# Vibelution 配置面板 Schema-First 重构 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将当前配置面板从“服务端拼整页 HTML + 整页预览提交”的实现，重构为“schema 驱动 + 卡片级确认 + 全局应用 + 两层模型结构”的配置体验，同时保持 `config.toml` 仍然是唯一最终真相。

**Architecture:** 保留现有 Python 配置加载、TOML 持久化、Pydantic 校验链路，不做一次性前后端大重写。先抽出配置 schema / view-model / patch 协议，让 UI 不再直接绑死在 `scripts/config_panel.py` 的大段字符串模板上；再把 LLM 配置表意收束为“通用模型模板 + 具体配置卡片”两层，运行时内部需要的 `providers` 物化逻辑继续只存在于 `config/settings.py` 的归一化阶段，不再暴露为用户心智。

**Tech Stack:** Python `http.server`、现有 `scripts/config_panel.py`、`config/public_config.py`、`config/settings.py`、Pydantic、`pytest`、稳定 TOML 序列化器；设计上参考 OpenClaw 的 schema/render/patch/base-hash 思路，但不在本轮直接引入 React/JSON Forms。

---

## 改造目标锁定

1. 用户可见层面只保留两层：
   - 通用模型模板
   - 具体配置卡片
2. 不再向用户暴露“公共 provider / remote_main / primary provider”之类运行时概念。
3. 每个配置卡片统一为：
   - 查看态
   - 点击“编辑”后展开卡片内编辑
   - 点击“确认”仅确认到草稿，不写入配置文件
   - 顶部或页面级“应用配置”才真正写入 `config.toml`
4. 删除模板后，引用该模板的配置卡片进入“未完成占位态”，页面允许继续编辑，但禁止应用。
5. 模板中的 API Key 归属模板本身，测试连接优先使用草稿中的待写入密钥。
6. 所有局部修改只刷新当前卡片，不刷新整页。
7. 后端写入必须增加 `base_hash` 并发保护，防止旧页面覆盖新配置。

## 非目标

1. 本轮不做完整 SPA 重写。
2. 本轮不把全部配置项都迁移到第三方表单库。
3. 本轮不修改运行时核心 LLM 调用协议，只改配置表达、面板交互和保存流程。

## 关键设计决策

### 决策 1：继续保留现有 Python 服务端入口

原因：

1. 当前面板已经依赖 `scripts/config_panel.py` 的路由、预览、测试连接、环境变量写入。
2. 直接切前端框架会把“结构问题”和“技术栈迁移问题”绑在一起，风险过高。
3. 先抽 schema 和 patch 协议，后续如果要改成 Vite/Lit/React，替换成本就会低很多。

### 决策 2：公开配置改成“模板引用 + 局部覆盖”

建议公开结构：

```toml
[llm.model_library.openai_gpt_5_5]
label = "OpenAI GPT-5.5"
model = "gpt-5.5"
api_key_env = "VIBELUTION_LLM_OPENAI_GPT_5_5_API_KEY"

[llm.model_library.openai_gpt_5_5.provider]
kind = "openai"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
compat_mode = "openai"
requires_api_key = true
context_window = 1050000

[llm.profiles.primary]
model_ref = "openai_gpt_5_5"

[llm.profiles.primary.overrides]
temperature = 0.7
max_output_tokens = 128000
tool_calling_mode = "auto"
```

说明：

1. `model_library` 负责定义“可选模型模板”。
2. `profiles.<id>.model_ref` 负责选择模板。
3. `profiles.<id>.overrides` 只放该卡片相对模板的微调值。
4. 运行时仍然会在 `normalize_public_config_dict()` 中物化成内部 `provider_id + profile fields`，但那是内部实现，不再是用户编辑模型。

### 决策 3：保留草稿态与最终应用态分离

需要三个层次的状态，但用户只感知两个动作：

1. 本地编辑中
2. 已确认未应用
3. 已应用

实现上：

1. `draftPublicConfig` 保存当前草稿
2. `draftMeta` 保存待写入 API Key、清除标记、校验状态
3. `saved_hash` / `base_hash` 标识当前草稿基于哪个已保存版本

### 决策 4：模板删除后不自动“补回”

删除模板后：

1. 所有引用该模板的卡片改成占位值，例如 `model_ref = "__unconfigured__"`
2. 卡片显示红色必填标记和不可运行提示
3. 页面仍可继续编辑
4. 点击“应用配置”时统一拦截，要求补全

这能避免“UI 看起来删掉了，刷新后又回来”这种不可信行为。

---

### Task 1: 先用测试锁住当前与目标行为

**Files:**
- Modify: `tests/test_config_panel.py`
- Modify: `tests/test_config_sync.py`
- Modify: `tests/test_config_redaction.py`
- Create: `tests/test_public_config_model_refs.py`

**Step 1: Write the failing tests**

增加以下测试骨架：

```python
def test_profile_uses_model_ref_and_overrides():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.3},
    }
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")
    assert profile.model == "gpt-5.5"
    assert profile.temperature == 0.3


def test_delete_model_marks_referencing_profiles_unconfigured():
    public_config = load_public_config()
    updated = delete_llm_model(public_config, "openai_gpt_5_5")
    assert updated["llm"]["profiles"]["primary"]["model_ref"] == "__unconfigured__"


def test_confirm_does_not_persist_config_file(tmp_path):
    ...


def test_apply_rejects_stale_base_hash():
    ...
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_public_config_model_refs.py tests/test_config_panel.py -q`

Expected: FAIL，提示 `model_ref`、`overrides`、`base_hash` 等行为尚未实现。

**Step 3: Add minimal test helpers**

在测试中增加以下帮助函数：

```python
def make_profile_ref(model_ref: str, **overrides):
    return {"model_ref": model_ref, "overrides": overrides}
```

**Step 4: Re-run focused tests**

Run: `python -m pytest tests/test_public_config_model_refs.py -q`

Expected: 仍 FAIL，但失败点更聚焦到新结构。

**Step 5: Commit**

```bash
git add tests/test_config_panel.py tests/test_config_sync.py tests/test_config_redaction.py tests/test_public_config_model_refs.py
git commit -m "test: lock config-panel schema-first target behaviors"
```

---

### Task 2: 抽出配置面板 schema / view-model 层

**Files:**
- Create: `config/panel_schema.py`
- Create: `config/panel_view_model.py`
- Modify: `scripts/config_panel.py`
- Test: `tests/test_config_panel.py`

**Step 1: Write the failing test**

```python
def test_panel_schema_lookup_returns_child_summaries():
    node = lookup_panel_schema("llm.profiles")
    assert node["path"] == "llm.profiles"
    assert any(child["path"] == "llm.profiles.primary" for child in node["children"])
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_panel.py -q -k "schema_lookup"`

Expected: FAIL with `lookup_panel_schema` not found.

**Step 3: Write minimal implementation**

新增两个模块：

1. `config/panel_schema.py`
   - `build_panel_schema(public_config: dict, lang: str) -> dict`
   - `lookup_panel_schema(public_config: dict, path: str, lang: str) -> dict`
2. `config/panel_view_model.py`
   - `build_model_library_page_vm(...)`
   - `build_llm_profiles_page_vm(...)`
   - `build_card_vm(...)`

建议的最小结构：

```python
def lookup_panel_schema(public_config: dict, path: str, lang: str) -> dict:
    tree = build_panel_schema(public_config, lang)
    ...
    return {
        "path": path,
        "title": "...",
        "description": "...",
        "children": [...],
        "fields": [...],
    }
```

**Step 4: Refactor `scripts/config_panel.py` to read from schema/view-model**

不要一次全改 HTML，先把以下内容迁出：

1. section/card 标题
2. field label/hint
3. group 分组
4. 右侧卡片数据来源

`scripts/config_panel.py` 应只保留：

1. HTTP 路由
2. HTML 拼装
3. 事件入口
4. 调用 schema/view-model

**Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_config_panel.py -q -k "schema_lookup or stable_card_id"`

Expected: PASS

**Step 6: Commit**

```bash
git add config/panel_schema.py config/panel_view_model.py scripts/config_panel.py tests/test_config_panel.py
git commit -m "refactor: extract config panel schema and view-model layer"
```

---

### Task 3: 引入 `model_ref + overrides` 的公开配置结构

**Files:**
- Modify: `config/public_config.py`
- Modify: `config/settings.py`
- Modify: `config/models.py`
- Modify: `config/toml_writer.py`
- Modify: `config.example.toml`
- Modify: `config.toml`
- Test: `tests/test_public_config_model_refs.py`
- Test: `tests/test_config_sync.py`

**Step 1: Write the failing tests**

```python
def test_build_effective_config_resolves_model_ref():
    public_config = {
        "llm": {
            "model_library": {...},
            "profiles": {
                "primary": {"model_ref": "openai_gpt_5_5", "overrides": {"temperature": 0.2}}
            },
        }
    }
    effective = build_effective_config(public_config)
    assert effective.llm.get_profile("primary").temperature == 0.2


def test_legacy_inline_profile_is_migrated_to_generated_template():
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_public_config_model_refs.py -q`

Expected: FAIL

**Step 3: Write minimal implementation**

在 `config/public_config.py` 中新增：

```python
PROFILE_OVERRIDE_FIELDS = (
    "transport",
    "contract",
    "reasoning_state_field",
    "strict_compatibility",
    "temperature",
    "max_output_tokens",
    "timeout",
    "connect_timeout",
    "streaming",
    "tool_calling_mode",
    "discovery_enabled",
)
```

实现：

1. `resolve_profile_model_ref(public_config, profile_id)`
2. `materialize_profile_from_model_ref(public_config, profile_id)`
3. `migrate_legacy_inline_profile_to_model_ref(public_config)`

在 `config/settings.py` 中让归一化流程支持：

1. `profiles.<id>.model_ref`
2. `profiles.<id>.overrides`
3. 旧结构兼容迁移

在 `config/models.py` 中为 `LLMProfile` 保持运行时结构不变，不直接引入 `model_ref` 字段；`model_ref` 只存在于公开配置层。

**Step 4: Update persistence**

保证 `dumps_public_config()` 可以稳定写出：

```toml
[llm.profiles.primary]
model_ref = "openai_gpt_5_5"

[llm.profiles.primary.overrides]
temperature = 0.2
```

**Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_public_config_model_refs.py tests/test_config_sync.py -q`

Expected: PASS

**Step 6: Commit**

```bash
git add config/public_config.py config/settings.py config/models.py config/toml_writer.py config.example.toml config.toml tests/test_public_config_model_refs.py tests/test_config_sync.py
git commit -m "feat: express llm profiles as model refs with overrides"
```

---

### Task 4: 删除模板后进入“未完成占位态”，而不是补回旧值

**Files:**
- Modify: `config/public_config.py`
- Modify: `scripts/config_panel.py`
- Test: `tests/test_public_config_model_refs.py`
- Test: `tests/test_config_panel.py`

**Step 1: Write the failing test**

```python
def test_missing_template_blocks_apply_but_not_preview():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"]["model_ref"] = "__unconfigured__"
    html = render_panel_html(public_config, lang="zh")
    assert "必填" in html
    with pytest.raises(ValueError):
        validate_applyable_public_config(public_config, "zh")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_public_config_model_refs.py tests/test_config_panel.py -q -k "unconfigured or missing_template"`

Expected: FAIL

**Step 3: Write minimal implementation**

新增常量：

```python
UNCONFIGURED_MODEL_REF = "__unconfigured__"
```

实现：

1. `delete_llm_model()` 删除模板时，把引用它的 profile 统一改成 `model_ref = "__unconfigured__"`
2. `validate_applyable_public_config()` 负责拦截未完成 profile
3. `render_panel_html()` / card vm 给未完成卡片打红色必填标记
4. 诊断信息明确提示“当前配置未完成，不能运行”

**Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_public_config_model_refs.py tests/test_config_panel.py -q -k "unconfigured or missing_template or required"`

Expected: PASS

**Step 5: Commit**

```bash
git add config/public_config.py scripts/config_panel.py tests/test_public_config_model_refs.py tests/test_config_panel.py
git commit -m "fix: keep deleted model references as explicit unconfigured placeholders"
```

---

### Task 5: 重做“确认 / 应用”协议，加入 `base_hash`

**Files:**
- Create: `config/panel_patch.py`
- Modify: `scripts/config_panel.py`
- Modify: `config/public_config.py`
- Test: `tests/test_config_panel.py`

**Step 1: Write the failing tests**

```python
def test_confirm_profile_patch_returns_card_preview_without_writing_file(tmp_path):
    ...


def test_apply_requires_matching_base_hash():
    ...


def test_apply_persists_confirmed_draft():
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_panel.py -q -k "base_hash or confirm_profile_patch or apply_persists"`

Expected: FAIL

**Step 3: Write minimal implementation**

新增 `config/panel_patch.py`：

```python
def compute_public_config_hash(public_config: dict) -> str:
    payload = dumps_public_config(public_config, HEADER_LINES)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_public_config_patch(public_config: dict, patch: dict) -> dict:
    ...
```

在 `scripts/config_panel.py` 中新增或替换路由：

1. `GET /panel-bootstrap`
2. `POST /draft-confirm-card`
3. `POST /draft-preview-card`
4. `POST /apply`

协议要求：

1. 卡片“确认”：
   - 只更新草稿
   - 返回当前卡片 HTML 或 card vm
   - 不写 `config.toml`
2. 全局“应用”：
   - 提交完整草稿 + `base_hash`
   - hash 一致才允许写入
   - 写入成功后返回新的 `saved_hash`

**Step 4: Update frontend state machine**

前端状态最小结构：

```javascript
let draftPublicConfig = ...
let draftMeta = ...
let savedHash = INITIAL_HASH
let confirmedCards = new Set()
```

卡片确认后：

1. 只刷新当前卡片
2. 页面其他未应用编辑不丢
3. 顶部“应用配置”按钮变为高亮

**Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_config_panel.py -q -k "base_hash or confirm_profile_patch or apply_persists"`

Expected: PASS

**Step 6: Commit**

```bash
git add config/panel_patch.py scripts/config_panel.py config/public_config.py tests/test_config_panel.py
git commit -m "feat: add card-confirm and base-hash guarded apply flow"
```

---

### Task 6: 重组 UI，只保留“通用模型模板 + 具体配置卡片”两层心智

**Files:**
- Modify: `scripts/config_panel.py`
- Modify: `config/panel_schema.py`
- Modify: `config/panel_view_model.py`
- Test: `tests/test_config_panel.py`

**Step 1: Write the failing test**

```python
def test_llm_pages_only_show_model_library_and_profile_cards():
    html = render_panel_html(load_public_config(), lang="zh")
    assert "通用模型模板" in html
    assert "模型配置" in html
    assert "公共 Provider" not in html
    assert "remote_main" not in html
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_panel.py -q -k "only_show_model_library_and_profile_cards"`

Expected: FAIL

**Step 3: Write minimal implementation**

页面结构建议：

1. 左侧导航
   - 通用模型模板
   - 模型配置
   - 其他配置
2. 模型配置页内部按组展示
   - 无监督进化
   - 监督进化
3. 每个卡片 header 只保留
   - 标题
   - 当前模板名
   - 必填/未应用/已应用状态
   - 编辑按钮

模板卡片编辑态字段：

1. 模板名称
2. 模型 ID
3. provider 类型
4. base URL
5. API Key 环境变量名
6. transport / contract / timeout / token / streaming
7. 测试连接

配置卡片编辑态字段：

1. 模板下拉选择
2. 高级设置开关
3. overrides 字段
4. 确认按钮

**Step 4: Keep inline-card editing only**

禁止再出现弹窗式编辑；所有编辑都发生在当前卡片展开区。

**Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_config_panel.py -q -k "model_library and profile_cards"`

Expected: PASS

**Step 6: Commit**

```bash
git add scripts/config_panel.py config/panel_schema.py config/panel_view_model.py tests/test_config_panel.py
git commit -m "refactor: simplify llm panel into templates and profile cards"
```

---

### Task 7: 把 API Key 体验收束到模板，并支持草稿测试连接

**Files:**
- Modify: `config/public_config.py`
- Modify: `scripts/config_panel.py`
- Test: `tests/test_config_panel.py`
- Test: `tests/test_config_redaction.py`

**Step 1: Write the failing tests**

```python
def test_test_connection_uses_pending_model_api_key():
    ...


def test_apply_writes_pending_api_key_to_user_env():
    ...


def test_panel_never_echoes_real_api_key_value():
    html = render_panel_html(load_public_config(), lang="zh")
    assert "sk-" not in html
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_panel.py tests/test_config_redaction.py -q -k "pending_model_api_key or never_echoes"`

Expected: FAIL

**Step 3: Write minimal implementation**

要求：

1. 模板卡片拥有自己的 `api_key_env`
2. 配置卡片默认继承模板的 key，不单独要求重复配置
3. 草稿里的新 key 保存在 `draftMeta.pending_api_keys`
4. 测试连接优先读取：
   - profile override key
   - 模板 pending key
   - 已保存环境变量
5. UI 只显示：
   - 已配置
   - 待写入
   - 已标记清除
   - 未配置

**Step 4: Run tests to verify it passes**

Run: `python -m pytest tests/test_config_panel.py tests/test_config_redaction.py -q -k "pending_model_api_key or never_echoes"`

Expected: PASS

**Step 5: Commit**

```bash
git add config/public_config.py scripts/config_panel.py tests/test_config_panel.py tests/test_config_redaction.py
git commit -m "feat: bind api key workflow to model templates and draft-aware connection tests"
```

---

### Task 8: 做迁移、文档、回归验证，确保旧配置可恢复

**Files:**
- Modify: `config/public_config.py`
- Modify: `README.md`
- Modify: `config.example.toml`
- Modify: `tests/test_config_sync.py`
- Modify: `tests/test_workbench.py`

**Step 1: Write the failing tests**

```python
def test_load_public_config_migrates_legacy_inline_profiles():
    ...


def test_save_public_config_writes_backup_before_schema_first_layout():
    ...
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_sync.py tests/test_workbench.py -q -k "migrates_legacy or writes_backup"`

Expected: FAIL

**Step 3: Write minimal implementation**

迁移要求：

1. 旧 `provider + model` 结构首次加载时可自动迁移到：
   - 同名模板，或
   - 生成的 custom 模板
2. 保存前继续自动备份：
   - `config.toml.bak`
3. README 增加一节：
   - 两层模型结构
   - 确认 vs 应用
   - 模板删除后的占位提示
   - API Key 如何写入用户环境变量

**Step 4: Run full targeted regression**

Run:

```bash
python -m pytest tests/test_public_config_model_refs.py -q
python -m pytest tests/test_config_panel.py -q
python -m pytest tests/test_config_sync.py tests/test_config_redaction.py tests/test_workbench.py -q
python -m py_compile scripts/config_panel.py config/public_config.py config/settings.py config/panel_schema.py config/panel_view_model.py config/panel_patch.py
```

Expected: PASS

**Step 5: Manual browser smoke check**

检查以下路径：

1. 打开 `http://127.0.0.1:8765/?lang=zh#section-llm-model-library`
2. 新增模板
3. 编辑模板
4. 删除模板
5. 观察引用卡片变成未完成占位态
6. 仅确认一张卡
7. 应用配置
8. 页面停留当前页并刷新状态，不跳回首页

**Step 6: Commit**

```bash
git add config/public_config.py README.md config.example.toml tests/test_config_sync.py tests/test_workbench.py
git commit -m "docs: complete schema-first config panel migration and regression coverage"
```

---

## 实施顺序建议

按这个顺序做，不要跳步：

1. Task 1 锁测试
2. Task 2 抽 schema / view-model
3. Task 3 落两层数据结构
4. Task 4 落未完成占位态
5. Task 5 落确认 / 应用 / base-hash
6. Task 6 重组 UI
7. Task 7 收口 API Key
8. Task 8 做迁移与回归

## 风险与回避

1. **风险：** 直接把整个 `scripts/config_panel.py` 推倒重来，容易把已有连接测试、环境变量写入、语言切换一起打碎。  
   **回避：** 先抽 schema 和 patch 层，再逐步收瘦 HTML。

2. **风险：** 新公开结构和运行时内部结构脱节。  
   **回避：** 所有运行时入口都仍通过 `build_effective_config()`，只允许一处归一化。

3. **风险：** 删除模板后页面无法保存、无法恢复。  
   **回避：** 明确区分“允许草稿存在”与“禁止应用”。

4. **风险：** API Key 在编辑流程中泄露回显。  
   **回避：** 真实值只存在环境变量或 `draftMeta`，HTML 仅显示状态。

5. **风险：** 多页面同时打开时旧页面覆盖新配置。  
   **回避：** `base_hash` 必做，冲突时提示刷新并保留本地草稿。

## 验收标准

1. 中文模式下，LLM 配置只看到“通用模型模板”和“模型配置”两个层级。
2. 不再出现 `remote_main`、公共 provider、primary provider 之类误导用户的词。
3. 每张卡片只有一个编辑入口，编辑发生在卡片内展开区。
4. “确认”不会写文件；“应用配置”才会写文件。
5. 删除模板后，引用它的卡片会变成占位态，而不是假删除或自动补回。
6. 页面局部修改只刷新当前卡片，不会清掉其他未应用修改。
7. API Key 只需要在模板层配置一次；测试连接可使用草稿密钥。
8. 旧 `config.toml` 能自动迁移，且始终保留备份。

## 参考依据

1. OpenClaw Configuration：schema 驱动配置、`config.schema.lookup`、严格校验  
   https://docs.openclaw.ai/gateway/configuration
2. OpenClaw Control UI：base-hash guard、config patch/apply、safe raw round-trip  
   https://docs.openclaw.ai/web/control-ui
3. JSON Forms React Integration：schema + ui schema + renderer 分层  
   https://jsonforms.io/docs/integrations/react/
4. react-jsonschema-form Dynamic uiSchema：动态 UI 与性能注意点  
   https://rjsf-team.github.io/react-jsonschema-form/docs/api-reference/dynamic-ui-schema-examples/

## 结论

推荐执行的是“中等重构，不做全栈重写”的路线：

1. 先把配置面板从字符串模板代码里解耦出 schema、view-model、patch 协议。
2. 再把 LLM 配置收束成“模板引用 + overrides”的两层结构。
3. 最后再把确认 / 应用 / API Key / 占位态这些用户感知最强的行为统一起来。

这样能最快把“结构清晰、逻辑统一、交互可信”这三件事同时做出来。
