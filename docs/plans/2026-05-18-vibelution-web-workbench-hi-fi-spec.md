# Vibelution Web Workbench High-Fidelity Page Spec

**Purpose:** 在行为设计、低保真结构图、视觉 brief 已经完成后，这份文档把页面进一步压到“接近最终 UI”的说明层级。它仍然不是实现代码，但已经明确到足以指导真实前端搭建。

**Upstream references:**

- [2026-05-18-vibelution-web-workbench-design.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-design.md)
- [2026-05-18-vibelution-web-workbench-wireframes.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-wireframes.md)
- [2026-05-18-vibelution-web-workbench-visual-brief.md](/C:/Users/17533/Desktop/Vibelution/docs/plans/2026-05-18-vibelution-web-workbench-visual-brief.md)

**Design anchor:** `frontend-design`

---

## 1. Experience Summary

这一版高保真方向的目标不是“华丽”，而是让页面一打开就有明确的秩序：

1. 左边告诉你系统和 agent 当前状态
2. 中间承接你真正的工作
3. 右边安静地提供上下文切换
4. 顶部只负责切工作域，不抢视线

页面应像一个长期使用的本地工作台，而不是一个等待演示的产品壳。

---

## 2. Global Shell Spec

### 2.1 Top Bar

顶部条高度应偏低，接近工具台而不是网站导航。

#### Left cluster

1. `Vibelution` 标识
2. 简短产品副标题，可弱化显示，例如：
   - `local agent workbench`
   - 不建议放长 slogan

#### Center cluster

两个主标签：

1. `Chat / Coding`
2. `Evolution`

视觉规则：

1. 当前标签要明显，但不靠巨大颜色块。
2. 当前态建议使用暖色底线、暖色 pill 或轻压痕高亮。
3. 非当前态保持低噪声、低饱和。

#### Right cluster

1. 全局状态点
   - idle / running / failed
2. 齿轮按钮进入 `Config`

### 2.2 Global Surface Feel

页面不是“卡片堆叠网站”，而应像一整块连续工作台表面。

建议处理：

1. 顶栏与主内容之间有轻微明暗层次变化
2. 左、中、右三栏之间使用细边与浅阴影区分
3. 大区块不是浮起卡片，而是嵌入式面板

---

## 3. Chat / Coding High-Fidelity Spec

### 3.1 Overall Intent

这个页面不是聊天软件，也不是 IDE。

它是一个：

- 对话驱动
- 文件可预览
- 会话可切换
- 改动可回看

的本地 agent 工作台。

### 3.2 Layout Proportions

桌面优先建议：

1. 左栏：240px - 280px
2. 右栏：300px - 360px
3. 中间区：其余全部空间

当窗口稍窄时：

1. 左栏保持稳定
2. 右栏优先收窄
3. 中间区永远优先保住

### 3.3 Left Status Rail

左栏要看起来像“仪表 + 陪伴位”。

#### Block A: Agent Identity

内容：

1. 小型头像或抽象形象
2. Agent 名称
3. 一句短状态语

状态语示例语气：

- `steady and listening`
- `working through current task`
- `waiting for your next move`

视觉要求：

1. 头像区应精致但克制
2. 不做大面积插画
3. 不像虚拟宠物养成界面

#### Block B: Current Session Card

内容：

1. 会话标题
2. 当前任务摘要
3. 当前阶段标签
   - `reading`
   - `editing files`
   - `running tools`
   - `waiting`

视觉要求：

1. 这是左栏里最有“当前感”的一块
2. 可稍微更亮一层
3. 但不应做成巨大焦点卡

#### Block C: Runtime

内容：

1. 当前模式
2. 当前模型
3. 当前配置档
4. 当前运行状态

建议展示方式：

```text
mode        chat
model       gpt-5.5
profile     safe_local
status      running
```

不要用花哨图表；它更像精炼状态表。

#### Block D: Context and Tools

内容：

1. context usage
2. active tools
3. delegation / child task signal

表现方式：

1. 小型条状或数字
2. 当前活跃工具用轻高亮
3. 子任务状态尽量一句话说明

#### Block E: Recent Outcome

内容：

1. 最近变更文件数
2. 最近动作摘要
3. 最近成功/失败状态

这是左栏最靠近“事件回声”的一块，不宜过高。

### 3.4 Center Workspace

中间区必须看起来最“值钱”。

#### Top of center: Tab strip

标签类型：

1. `Agent Session`
2. `file.py`
3. `notes.md`

规则：

1. `Agent Session` 标签应有特殊身份，但不必过度装饰
2. 文件预览标签更像工作对象
3. 当前标签应清楚、稳定、低噪声

#### Agent Session tab

应包含：

1. 对话流
2. tool call / tool result 的结构化块
3. 结果摘要块
4. 输入区

##### Message style

用户消息和 agent 消息不应做成社交聊天泡泡。

推荐：

1. 用户输入更简洁、像指令块
2. agent 回复更像工作记录 + 结论输出
3. tool 部分作为嵌入式运行块，不喧宾夺主

##### Input area

输入区应固定在底部，像工作台命令入口。

建议包含：

1. 主输入框
2. 发送按钮
3. 少量附加动作
   - attach current file
   - maybe stop/cancel when running

不要把输入区做成大而空的聊天首页样式。

#### File Preview tab

只读预览页要更像“代码阅读面”，不是文本卡片。

建议组成：

1. 文件头
   - 文件名
   - 路径
   - changed badge if modified by agent
2. 正文预览
   - 代码或文本内容
3. 轻量辅助区
   - 最近修改来源
   - 来自哪条会话

视觉要求：

1. 等宽字体
2. 清楚的行间距
3. changed 区域可以有轻微暖色提示
4. 不做人类可编辑光标态

### 3.5 Right Panel

右栏像“安静工具抽屉”。

#### Toggle header

顶部只有两个切换：

1. `Sessions`
2. `Files`

切换应该像 segment control，不像二级导航栏。

#### Sessions panel detail

每个会话项建议包含：

1. 会话标题
2. 一句任务摘要
3. 状态 pill
4. 最后活动时间

如果会话正在运行：

1. 用暖色 running 指示
2. 不要整块闪烁

当前会话项：

1. 使用更明确的底色层级
2. 左边可有细暖色标记线

#### Files panel detail

项目树建议：

1. 目录缩进清晰
2. 当前打开文件可见
3. agent 改过的文件有低调 changed 标记

文件树是辅助工具，不应视觉上过于强势。

### 3.6 Chat / Coding State Examples

#### Idle

感觉：

1. 安静
2. 内容稳定
3. 左栏状态略低亮

#### Running

感觉：

1. 左栏与顶部状态点有温暖活跃感
2. 中间 agent 会话显示当前进度
3. 右栏当前会话项同步为 running

#### After file changes

感觉：

1. 会话流给出清晰文字说明
2. 文件树出现 changed 标记
3. 若预览已开，内容静默刷新
4. 用户不会被强行拉去看新标签

---

## 4. Evolution High-Fidelity Spec

### 4.1 Overall Intent

`Evolution` 要看起来像“实验与沉淀工作域”，不是单一日志面。

页面核心问题：

1. 现在进化状态如何
2. 最近结果有没有变好
3. 有哪些内容值得沉淀或已经沉淀

### 4.2 Evolution Header

进入 `Evolution` 后，顶部下方出现域内标签：

1. `Overview`
2. `Runs`
3. `Library`

当前标签可用比主导航稍弱一点的视觉强调。

右侧可以放：

1. intake mode 快捷切换
2. recent run state indicator

### 4.3 Overview

#### First row

两个主要区块：

1. `Current evolution status`
2. `Recent library additions`

#### Second row

1. `Recent run performance`
2. `Quick actions`

##### Current evolution status

应显示：

1. 当前是否运行
2. 当前阶段
3. 最近一次结果
4. 最近一次异常或回退提示

##### Recent run performance

应显示：

1. 最近数次 run 的分数走势
2. 近期成功/失败比
3. 最近显著波动

图表应克制，不做仪表盘风暴。

##### Recent library additions

应显示：

1. 最近入库内容
2. 最近候选数量
3. 自动/人工来源标记

##### Quick actions

建议：

1. open latest run
2. open pending candidates
3. switch intake mode

### 4.4 Runs

`Runs` 页面更像 master-detail 工作面。

#### Left side

run 列表项包含：

1. run id
2. score
3. result status
4. short summary

#### Right side

run detail 包含：

1. overall summary
2. evidence / diagnosis
3. outputs worth promoting
4. candidate items for library

要点：

1. 让用户能快速判断“这次 run 值不值得看”
2. 而不是把所有技术细节无差别摊开

### 4.5 Library

`Library` 页面要让“资产”和“候选”分层非常清楚。

建议顶部分段：

1. `Library Items`
2. `Pending Review`

#### Library item row

每项至少可见：

1. 名称
2. 类型
3. 来源 run
4. 入库方式
   - auto-ingested
   - manual-approved

#### Pending review row

每项至少可见：

1. 候选名称
2. 来源 run
3. 为什么被视为候选
4. approve / reject 动作位

视觉要求：

1. 正式条目更稳定
2. 待确认条目要有一点提醒感，但不该像报错

---

## 5. Config High-Fidelity Spec

### 5.1 Intent

`Config` 页是系统设置页，不是工作流页。

它应更平静、更规则、更克制。

### 5.2 Layout

左侧为 section navigation，右侧为主内容。

建议 section：

1. Runtime
2. Models
3. Evolution
4. Appearance
5. Diagnostics

### 5.3 Evolution settings inside Config

这一段需要与 `Evolution Overview` 的快捷开关形成闭环。

至少应包含：

1. intake mode
2. 相关说明
3. 是否影响历史项的说明

文案应清楚说明：

- only affects future items

---

## 6. Icon and Control Language

后续实现时应偏向熟悉的工具感控件。

建议：

1. 顶部齿轮用 icon-only button
2. 右栏 `Sessions / Files` 用 segmented control
3. 状态使用小 pill
4. 输入区动作用 icon + tooltip

避免：

1. 页面上到处都是大文本按钮
2. 把二级信息做成大彩块

---

## 7. Example Copy Tone

文本语气应保持：

1. 简短
2. 专业
3. 不端着
4. 有一点陪伴感，但不卖萌

示例：

- `running a file update`
- `reviewing latest changes`
- `waiting on your next instruction`
- `3 files changed in this session`

避免：

- 过度产品化口号
- 夸张拟人化台词
- 社交媒体式语气

---

## 8. Build Guardrails

后续前端实现时，如果页面出现以下特征，就说明偏航了：

1. 看起来像常见紫蓝 AI SaaS
2. 左栏变成导航树
3. 中间工作区被做成聊天首页
4. 右栏比中间还抢眼
5. Evolution 像日志垃圾场
6. Config 像另一套产品

---

## 9. Ready State

到这一步，设计层已经形成四层闭环：

1. 行为锁定
2. 信息架构
3. 低保真结构
4. 高保真页面说明

下一步就可以进入真正的页面实现准备：

1. 前端技术栈确认
2. 页面骨架创建
3. 视觉 token 落地
4. 组件实现
