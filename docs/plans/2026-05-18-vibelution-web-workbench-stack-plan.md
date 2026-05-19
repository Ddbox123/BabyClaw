# Vibelution Web Workbench Stack And Structure Plan

**Purpose:** 在页面设计已经收敛之后，为真正开始 Web 工作台实现提供技术选型、目录骨架、前后端边界与分阶段落地方案。

**Upstream references:**

- [2026-05-18-vibelution-web-workbench-design.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-design.md)
- [2026-05-18-vibelution-web-workbench-wireframes.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-wireframes.md)
- [2026-05-18-vibelution-web-workbench-visual-brief.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md)
- [2026-05-18-vibelution-web-workbench-hi-fi-spec.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-hi-fi-spec.md)

---

## 1. Recommendation Summary

我对这一版 Web 工作台的明确推荐是：

### Frontend

1. `Vite`
2. `React`
3. `TypeScript`
4. `React Router`
5. `TanStack Query`
6. `Zustand`
7. `CodeMirror 6` 只读预览
8. `Lucide React`
9. `CSS variables + CSS modules`
10. 需要时少量 `Radix UI` primitives

### Backend adapter

1. `FastAPI`
2. `Uvicorn`
3. 保留现有 Python 业务逻辑
4. 新增本地 Web adapter 层，不直接把业务塞进前端
5. 使用 `JSON API + SSE`，而不是一开始就上 WebSocket

### Launch mode

1. CLI 仍然保留
2. 新增 Web workbench 启动入口
3. 本地开发时前后端分开跑
4. 生产/本地长期使用时由 Python 服务层托管前端构建产物

---

## 2. Why This Stack

### 2.1 Why React + TypeScript + Vite

原因：

1. 当前仓库没有现成前端，Vite 起步最快。
2. 这套工作台需要：
   - 三栏壳
   - 多页面域切换
   - 会话流
   - 文件预览标签
   - 进化总览
3. 这已经超过“服务端拼 HTML”适用区间。
4. TypeScript 能给会话、运行状态、进化记录这些对象增加明显可控性。

### 2.2 Why Not Keep Building on `http.server`

当前 [scripts/config_panel.py](/C:/Users/17533/Desktop/Vibelution/scripts/config_panel.py:1) 适合配置页，但不适合作为统一 workbench 基座。

主要原因：

1. `Chat / Coding` 需要更强的增量状态更新
2. 会话、文件树、运行状态、Evolution 记录都更适合走 JSON API
3. 后续要接事件流时，`http.server` 的维护成本会迅速升高

### 2.3 Why FastAPI

FastAPI 在这里的定位不是“重写后端”，而是：

**给现有 Python 业务逻辑加一个干净的 Web adapter 层。**

它适合：

1. 本地服务
2. typed schema
3. 分路由组织
4. SSE / streaming adapter

### 2.4 Why TanStack Query + Zustand

这套界面天然存在两类状态：

1. `server state`
   - 会话列表
   - 会话内容
   - 文件树
   - 文件预览内容
   - Evolution overview / runs / library
   - config snapshot
2. `UI state`
   - 当前页面
   - 当前右栏面板
   - 当前会话
   - 当前预览标签集合
   - 左栏局部展示状态

推荐分工：

1. `TanStack Query` 管 server state
2. `Zustand` 管 UI state

这样比把所有状态都塞进 React context 更干净。

### 2.5 Why CodeMirror 6 for Read-Only Preview

因为你已经明确说了第一版文件区只要预览，不做人类编辑。

所以：

1. 不需要 Monaco 这种更重的编辑器栈
2. CodeMirror 6 足够承担读代码、路径、只读语法高亮
3. 后续若要升级到编辑器，也比纯自制预览更容易过渡

### 2.6 Why CSS Modules Instead of Tailwind-As-Default

不是因为 Tailwind 不能用，而是因为这套界面已经有明确的气质要求：

- 温暖
- 克制
- 有层次
- 避免通用 AI 壳感

推荐：

1. 用 `CSS variables` 统一 token
2. 用 `CSS modules` 写组件样式
3. 保留少量全局基础层

这样更容易让页面有自己的长相，而不是快速滑向模板味。

---

## 3. Backend Architecture Recommendation

### 3.1 New Web Adapter Layer

推荐新增：

```text
core/web/
```

职责：

1. 定义 Web app
2. 定义 API routes
3. 连接现有 core/config/evolution/session 逻辑
4. 提供前端所需的 typed payload

不要让前端直接读仓库文件或直接碰内部 Python 模块。

### 3.2 Recommended Backend Skeleton

```text
core/web/
├── __init__.py
├── app.py
├── settings.py
├── routes/
│   ├── shell.py
│   ├── sessions.py
│   ├── files.py
│   ├── runtime.py
│   ├── evolution.py
│   └── config.py
├── services/
│   ├── session_service.py
│   ├── file_service.py
│   ├── runtime_service.py
│   ├── evolution_service.py
│   └── config_service.py
├── schemas/
│   ├── sessions.py
│   ├── files.py
│   ├── runtime.py
│   ├── evolution.py
│   └── config.py
└── streams/
    └── sse.py
```

### 3.3 Launch Entrypoint

推荐新增一个启动脚本，例如：

```text
scripts/web_workbench.py
```

职责：

1. 启动 FastAPI / Uvicorn
2. 在开发模式下指向 Vite dev server
3. 在本地使用模式下托管前端构建产物
4. 可选自动打开浏览器

---

## 4. Frontend Architecture Recommendation

### 4.1 Frontend Root

推荐新增：

```text
web/
```

### 4.2 Recommended Frontend Skeleton

```text
web/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
└── src/
    ├── main.tsx
    ├── app/
    │   ├── App.tsx
    │   ├── router.tsx
    │   ├── providers.tsx
    │   └── boot.ts
    ├── design/
    │   ├── tokens.css
    │   ├── themes.css
    │   ├── typography.css
    │   └── motion.css
    ├── api/
    │   ├── client.ts
    │   ├── events.ts
    │   ├── queryKeys.ts
    │   └── types/
    ├── store/
    │   ├── shellStore.ts
    │   ├── chatWorkbenchStore.ts
    │   └── evolutionStore.ts
    ├── routes/
    │   ├── ChatCodingRoute.tsx
    │   ├── EvolutionRoute.tsx
    │   └── ConfigRoute.tsx
    ├── components/
    │   ├── shell/
    │   ├── status/
    │   ├── sessions/
    │   ├── files/
    │   ├── conversation/
    │   ├── preview/
    │   ├── evolution/
    │   └── config/
    ├── features/
    │   ├── chat-coding/
    │   ├── evolution/
    │   └── config/
    └── utils/
```

### 4.3 Why Feature + Shared Component Split

原因：

1. `Chat / Coding` 和 `Evolution` 是两个清晰域
2. 壳层、状态栏、通用标签、tooltips 这类组件是跨域共享的
3. 会话、文件树、Evolution 详情面等则更适合作为 feature 下的局部实现

---

## 5. Route Plan

第一版推荐保持简单：

```text
/              -> redirect to /chat
/chat
/evolution
/config
```

不建议第一版就把：

- active session id
- active file tab
- right panel state

全部编码到 URL 里。

更推荐：

1. 路由只表示当前工作域
2. 当前会话与当前工作区状态走 store + server restore

---

## 6. API Surface Recommendation

第一版后端接口建议围绕“页面真正需要什么”来设计，不直接裸露内部对象。

### 6.1 Runtime and shell

```text
GET  /api/runtime/summary
GET  /api/runtime/events   (SSE)
```

### 6.2 Sessions

```text
GET  /api/sessions
GET  /api/sessions/:id
POST /api/sessions/:id/messages
GET  /api/sessions/:id/events   (SSE or merged stream)
```

返回内容应覆盖：

1. 会话摘要
2. 任务状态
3. 对话内容
4. 该会话关联的预览标签集合
5. 最近变更文件集合

### 6.3 Files

```text
GET /api/files/tree
GET /api/files/content?path=...
```

第一版只做只读，所以不需要写接口。

### 6.4 Evolution

```text
GET /api/evolution/overview
GET /api/evolution/runs
GET /api/evolution/runs/:id
GET /api/evolution/library
GET /api/evolution/library/pending
POST /api/evolution/intake-mode
```

### 6.5 Config

```text
GET  /api/config/public
POST /api/config/public
POST /api/config/test-connection
```

这里应尽量复用现有：

- [config/public_config.py](/C:/Users/17533/Desktop/Vibelution/config/public_config.py:1)

而不是在 Web 层重新发明配置业务。

---

## 7. State Model Split

### 7.1 Frontend UI State

用 `Zustand` 管：

1. 当前主域
2. 当前右栏面板
3. 当前活跃会话 id
4. 当前活跃中心标签 id
5. 当前会话下的只读预览标签顺序
6. 局部 UI 偏好

### 7.2 Server State

用 `TanStack Query` 管：

1. runtime summary
2. session list
3. session detail
4. file tree
5. file contents
6. evolution overview
7. runs and run detail
8. library and pending queue
9. config snapshot

### 7.3 Event Flow

推荐：

1. 初始化靠普通 REST 拉取
2. 运行中状态、会话追加消息、进度更新靠 `SSE`

为什么先用 SSE：

1. 单向流足够覆盖第一版状态刷新
2. 比 WebSocket 更简单
3. 更贴合“本地 agent 持续输出、前端持续观察”的模型

---

## 8. Config Integration Strategy

这里要非常明确：

### 8.1 Do Not Duplicate Config Logic Again

不要再让 Web workbench 把配置逻辑复制一份。

单一业务源必须继续是：

- [config/public_config.py](/C:/Users/17533/Desktop/Vibelution/config/public_config.py:1)

### 8.2 Transitional Strategy

第一阶段：

1. 先让 `Config` 页通过新 API 消费已有配置业务
2. `scripts/config_panel.py` 仍可存在

第二阶段：

1. 把 `scripts/config_panel.py` 的页面职责逐步迁移到新前端
2. 让它退化成旧入口或调试入口

---

## 9. Suggested Dependency Additions

### 9.1 Python

建议新增：

```text
fastapi
uvicorn
orjson        (optional)
```

可选：

```text
sse-starlette (if you want a helper layer, otherwise native streaming is fine)
```

### 9.2 Frontend

建议新增：

```text
react
react-dom
typescript
vite
react-router-dom
@tanstack/react-query
zustand
lucide-react
@codemirror/state
@codemirror/view
@codemirror/lang-python
@codemirror/language
```

按需新增：

```text
@radix-ui/react-tabs
@radix-ui/react-tooltip
@radix-ui/react-scroll-area
clsx
```

---

## 10. Build Phases

### Phase 1: Shell and Mocked Layout

目标：

1. 跑起 React 壳
2. 做出三栏 `Chat / Coding`
3. 做出 `Evolution` 与 `Config` 空壳
4. 先接静态假数据

### Phase 2: Live Chat/Coding Integration

目标：

1. 接会话列表
2. 接会话流
3. 接文件树
4. 接只读文件预览
5. 接左栏 runtime 状态

### Phase 3: Evolution Domain Integration

目标：

1. 接 `Overview`
2. 接 `Runs`
3. 接 `Library`
4. 接 intake mode 切换

### Phase 4: Config Unification

目标：

1. 新 `Config` 页接入现有配置逻辑
2. 与 `Evolution Overview` 同步 intake mode
3. 开始淘汰独立 `config_panel` 页面角色

---

## 11. Rejected Alternatives

### 11.1 Electron / Tauri First

不推荐现在就做。

原因：

1. 当前矛盾是工作台统一与业务边界，不是桌面宿主能力
2. 太早会把打包、窗口、权限问题提前引进来

### 11.2 Keep Everything Server-Rendered in Python

不推荐。

原因：

1. 统一工作台需要更细颗粒度的状态刷新
2. 会话、文件、Evolution 交互会把模板字符串拖得很重

### 11.3 Tailwind + Shadcn as the Whole Identity

不推荐把它当默认外观方案。

原因：

1. 容易快速滑向通用 AI 后台长相
2. 与已经锁定的视觉气质相冲突

---

## 12. Implementation Readiness

当你决定让我真正开工时，推荐顺序就是：

1. 建 `web/` 前端骨架
2. 建 `core/web/` 后端 adapter
3. 先做静态 shell
4. 再逐块接 live data

到这个节点，关于“用什么栈”“怎么分目录”“后端如何接前端”的问题，已经足够收口，可以开始实现。
