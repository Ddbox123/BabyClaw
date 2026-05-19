# Vibelution Web Workbench Visual Brief

**Purpose:** 在信息架构与低保真结构图已经锁定之后，为后续 Web 前端实现提供一份明确的视觉 brief。此文档不讨论数据结构和实现细节，只负责回答：这套工作台看起来应该像什么，为什么应该长这样。

**Upstream references:**

- [2026-05-18-vibelution-web-workbench-design.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-design.md)
- [2026-05-18-vibelution-web-workbench-wireframes.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-wireframes.md)

**Design skill anchor:** `frontend-design`

---

## 1. Visual Thesis

这套前端不应长成“默认 AI 控制台”，也不应长成“宠物面板”。

它的视觉命题是：

**Lamplight Workshop**

含义：

1. `Workshop`：这是干活的地方，不是展示页。
2. `Lamplight`：它要有一点温度，有陪伴感，但不是娱乐化和玩具化。
3. `Night Desk`：适合长时间使用，安静、稳定、可专注。

一句话总结：

**像深夜书桌前的一盏工作灯，而不是一艘赛博飞船的驾驶舱。**

---

## 2. User Feel Target

用户打开这套界面时，理想感受应该是：

1. 我可以在这里一直工作，不会被吵到。
2. Agent 是在旁边协作，不是在前面表演。
3. 系统状态是清楚的，但不是冷硬的。
4. 文件、会话、进化记录都能看懂，不像被塞进同一种面板。

避免出现的感受：

1. “又是一个紫蓝发光的 AI 产品壳”
2. “太像 SaaS 仪表盘”
3. “太像玩具”
4. “信息都在，但没有主次”

---

## 3. Aesthetic Direction

### 3.1 Tone Pair

结构气质：

- industrial
- editorial
- utilitarian

情绪气质：

- warm
- companion-like
- calm

组合结果：

- 专业但不僵
- 温暖但不软塌
- 密度高但不压人

### 3.2 What Makes It Memorable

这套界面最该被记住的，不是 logo，也不是大动画，而是：

1. 左侧状态栏像一个安静的陪伴位
2. 中间工作区始终稳稳地承担主焦点
3. 深色底上的暖色状态反馈有“灯下工作”的感觉

---

## 4. Color System

### 4.1 Primary Palette Direction

禁止走常见 AI 路线：

- 紫色主导
- 蓝紫渐变
- 纯黑 + 霓虹青

建议色彩方向：

1. `Base background`
   - 偏煤灰、墨绿黑、炭蓝黑
   - 不是纯黑
2. `Surface`
   - 比背景略亮一层
   - 用层级而不是强对比切割区域
3. `Warm accent`
   - 琥珀、蜂蜜金、烛光橙
   - 用于当前态、活跃态、轻强调
4. `Cool support accent`
   - 灰青、鼠尾草绿、柔和蓝灰
   - 用于信息性辅助，不抢主色
5. `Status colors`
   - success: muted green
   - warning: amber
   - error: clay red
   - running: warm gold

### 4.2 Suggested Token Direction

以下不是最终实现值，而是视觉区间：

```text
bg.canvas       = #15171a
bg.panel        = #1b1f23
bg.panel-soft   = #22272c
bg.active       = #292f35

fg.primary      = #ece6dc
fg.secondary    = #b7b0a4
fg.tertiary     = #8c877d

accent.warm     = #d8a75b
accent.warm-2   = #e7bf7a
accent.cool     = #7c9b96

state.success   = #7ea37c
state.warning   = #d7a054
state.error     = #bb6c5d
```

### 4.3 Color Rules

1. 暖色只打在关键焦点上，不要铺满页面。
2. 大面积颜色靠深浅层次，不靠大渐变。
3. 左栏和顶部可以略有暖度，中间工作区要更中性，保证内容可读。

---

## 5. Typography Direction

### 5.1 Principles

前端实现时应避免：

- Inter
- Arial
- Roboto
- Space Grotesk

推荐采用三类文字角色：

1. `Display / section accent`
2. `Body UI text`
3. `Code / data mono`

### 5.2 Candidate Pairing

建议候选：

1. 标题/强调：`Newsreader`
2. 正文/UI：`IBM Plex Sans`
3. 代码：`JetBrains Mono`

为什么这样配：

1. `Newsreader` 有一点编辑感和人味，不会像品牌海报。
2. `IBM Plex Sans` 稳、清晰、技术气质适中，适合高密度工作区。
3. `JetBrains Mono` 对代码和路径展示足够清楚。

### 5.3 Typographic Rules

1. 大标题不用太大，工作台不是海报。
2. 左栏和右栏文字要紧凑，但不能挤。
3. 中间对话内容允许更舒展的行距。
4. 代码预览区必须使用独立等宽体系。

---

## 6. Layout and Spatial Behavior

### 6.1 Overall Composition

页面整体是稳定的三栏工作台，不追求“打破栅格”的炫技。

因为本项目的记忆点不是奇观，而是长期工作舒适度。

建议空间角色：

1. `Top bar`
   - 低高度
   - 清晰切域
2. `Left rail`
   - 稳定窄栏
   - 更像仪表/陪伴栏
3. `Center`
   - 最大权重
   - 真正承接阅读和工作
4. `Right panel`
   - 次级工具面
   - 像抽屉，不像主舞台

### 6.2 Spacing Character

1. 小组件内部：紧凑
2. 栏与栏之间：留清晰缝隙
3. 大区块之间：通过层次变化分割，不通过大卡片套大卡片

---

## 7. Component Language

### 7.1 General Rules

1. 不把整个页面做成一堆浮卡。
2. 页面区域应更像连续的工作台表面。
3. 卡片只给真正的局部对象：
   - 当前会话摘要
   - Evolution overview 小块
   - Library item detail

### 7.2 Borders and Surfaces

建议：

1. 细边框
2. 柔和内阴影或浅层次压痕
3. 少量半透明叠层

避免：

1. 粗重玻璃拟态
2. 高饱和光边
3. 巨大的发光外阴影

### 7.3 Tabs

中间标签区要有“工作对象”的感觉，不要像浏览器娱乐标签。

建议：

1. 当前标签有温暖高亮
2. 文件预览标签与 Agent 会话标签能被轻微区分
3. 未关闭标签保持稳，不做跳动动效

### 7.4 Session Items

右栏会话列表项应重点显示：

1. 标题
2. 状态
3. 最近活动
4. 简短任务摘要

视觉上要像工作单元，而不是聊天气泡列表。

### 7.5 File Tree

文件树应克制：

1. 变更标记可见但不刺眼
2. 目录层级清楚
3. 当前打开文件有明确选中态

---

## 8. Motion and Interaction Feel

### 8.1 Motion Principle

动效用途只有三个：

1. 帮助理解状态变化
2. 帮助理解区域切换
3. 帮助降低硬切带来的突兀感

### 8.2 Recommended Motion Moments

1. 顶部工作域切换
2. 右栏 `Sessions / Files` 面板切换
3. 中间文件预览标签切换
4. 左栏状态更新时的轻反馈

### 8.3 Motion Character

建议：

1. 120ms - 220ms 的短过渡
2. 以淡入、位移、层次提升为主
3. 运行状态更新用轻脉冲或柔和高亮

避免：

1. 弹跳
2. 大面积飞入
3. 花哨 loading scene

---

## 9. Domain-Specific Visual Guidance

### 9.1 Chat / Coding

应该像：

1. 一个稳重的工作台
2. 一个能容纳对话、工具结果、文件预览的中心区
3. 一个低噪声但高可读的上下文管理界面

不应该像：

1. 聊天软件
2. 论坛
3. SaaS 销售后台

### 9.2 Evolution

应该像：

1. 一个实验与沉淀工作域
2. 一个能看状态、趋势、候选内容的分析面

不应该像：

1. 普通日志页
2. 空洞图表页
3. 完整 PM 看板

### 9.3 Config

应该像：

1. 稳定的系统设置页
2. 与主工作台同一世界观，但更克制

不应该像：

1. 另一个独立产品
2. 默认浏览器表单堆叠

---

## 10. State Feedback Language

### 10.1 Running States

不同状态的反馈应清楚但克制：

1. `idle`
   - 安静、低亮度
2. `running`
   - 暖色活跃提示
3. `waiting`
   - 中性提示
4. `done`
   - 短暂成功反馈后回归稳定
5. `failed`
   - 明确但不刺眼的错误色

### 10.2 Change Visibility

AI 修改文件后的反馈优先级：

1. 会话内说明
2. 文件树变更标记
3. 预览标签刷新
4. 左栏最近结果摘要

不要把“改了文件”做成抢焦点警报。

---

## 11. Responsive Strategy

第一版按桌面优先理解。

桌面策略：

1. 保持三栏
2. 中间区优先级最高
3. 右栏在较窄宽度下可收缩为更窄的工具栏态

移动端不是当前重点，不作为第一版视觉决策约束。

---

## 12. What To Build Next

这份 brief 之后，后续前端设计与实现应依次进入：

1. 设计 token 草案
2. 页面级高保真静态稿
3. 前端壳实现
4. 状态接线

如果后续实现出来的页面看起来像常见 AI 产品模板，就说明偏离了这份 brief。
