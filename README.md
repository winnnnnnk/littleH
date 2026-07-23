# 小H Codex Plugin

[![Cross-platform](https://github.com/winnnnnnk/littleH/actions/workflows/cross-platform.yml/badge.svg?branch=develop)](https://github.com/winnnnnnk/littleH/actions/workflows/cross-platform.yml?query=branch%3Adevelop)

小H是Codex根对话中的协调者：用户只需描述目标、想法、现象或背景；小H负责形成推荐方案、询问真正影响结果的决策、协调专业Agent、验收结果并沉淀稳定知识。

小H采用“证据优先的建设性异议”：提问、质疑和假设不会被自动当成需求变更；当用户表述与代码、数据模型、配置、文档或运行证据冲突时，小H会说明冲突、影响和推荐结论，再把真正改变业务结果的选择交给用户。缩减范围或写入兼容默认值必须有可定位证据，或有用户在知悉影响后的明确决策；高风险缩减还必须经过独立评审。

本仓库是可直接安装的Codex Marketplace源码，只包含通用能力，不包含客户、项目、仓库、真实任务证据、账号或凭据。

## 支持环境

| 系统 | 安装入口 | 自动验证 |
| --- | --- | --- |
| macOS | `install.sh` | Python、JSON、隔离安装、Hook自检 |
| Windows | `install-windows.cmd`或`install.ps1` | Python、JSON、隔离安装、PowerShell Hook自检 |

两端都需要Git、Python 3和Codex CLI。Obsidian只在需要查看开发知识库时安装，不是小H初始化的硬依赖；使用原生Bases工作台建议Obsidian 1.9或更高版本。小H自己的13个Skill随插件发布；配套Codex插件由初始化程序根据机器可读清单自动安装。

## 从GitHub安装

当前发布分支为`develop`：

```bash
codex plugin marketplace add winnnnnnk/littleH --ref develop
codex plugin add xiaoh@xiaoh
```

重新打开Codex后说：

```text
小H，初始化当前电脑
```

`xiaoh-setup`会自动安装可用的配套Codex插件，并使用默认目录或根据你的选择配置：

- Codex：`~/.codex`
- Obsidian：`~/obsidian/development-vault`
- 本地配置：`~/.xiaoh/config.json`

初始化完成后重启Codex，在`/hooks`中审核并信任Agent委派、Vault路径、`SubagentStart`、`SubagentStop`四个Hook，然后说：

```text
小H，检查当前环境和Hook是否生效
```

命令行也可以执行包和运行时文件诊断：macOS使用`./verify.sh --runtime`，Windows使用`.\verify.ps1 -Runtime`。命令行无法证明某个Codex任务实际加载了哪一版Skill，因此会保留`loaded Skill version unverified`降级项；完整版本证明必须在重启后的新Codex任务中调用`$xiaoh-doctor`。

## macOS源码安装

```bash
git clone -b develop https://github.com/winnnnnnk/littleH.git
cd littleH
chmod +x install.sh verify.sh
./install.sh
./verify.sh
```

## Windows源码安装

```powershell
git clone -b develop https://github.com/winnnnnnk/littleH.git
cd littleH
.\install-windows.cmd
```

也可以直接使用PowerShell：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1
.\verify.ps1
```

源码安装器会注册当前目录为本地Marketplace、安装`xiaoh`插件并部署核心运行时。由于定时任务只能通过Codex支持的任务工具创建，命令行安装结束时会如实显示`degraded`；重新打开Codex并说“小H，初始化当前电脑”后，小H会创建或校准任务、读取真实状态并完成绑定。

## 能力依赖

依赖事实源是`plugins/xiaoh/dependencies.json`，不是README中的人工步骤：

- 13个小H Skill随插件安装；任务即时收口和项目进度维护在工作完成时调用，每日成果推送和每周知识候选评审作为托管定时任务模板发布。
- Ponytail以及Codex提供的浏览器、文档、PDF、表格、演示、站点和可视化插件由初始化程序自动检测并安装。
- `codebase-memory-mcp`是可选的本机增强能力。小H只检测其是否存在，不会下载或执行第三方远程安装脚本；缺失时自动使用本地代码搜索，不影响核心运行。
- `$xiaoh-doctor`会把当前机器报告为`complete`或`degraded`，并列出实际缺失能力。

## 插件结构

- `xiaoh-core`：根线程沟通、分析、路由、验收与知识沉淀。
- 公共交互门禁：所有专业Agent都必须区分提问、假设、事实纠正、业务决策和执行指令，并在输出中给出证据依据、重大冲突、不确定项和推荐结论。
- `xiaoh-requirement-routing`：在业务任务进入成员确认、任务创建、OpenSpec或实现前，选择`openspec_only`、`spec_rfc_then_openspec`或`class_skill`，并执行需求工件门禁。
- Spec+RFC路线固定执行两道评审：先用`xiaoh:spec-rfc-reviewer`审核源工件准入质量；生成OpenSpec后再用`xiaoh:spec-rfc-openspec-consistency-review`审核完整承接与语义一致性。`xiaoh:`只表示插件来源，不表示子Agent；校验器兼容已有的无前缀全局副本。
- `xiaoh-setup`：显式安装Agent、公共契约、Hook、治理校验器和空白Vault。
- `xiaoh-doctor`：静态及运行时诊断。
- Vault写入门禁：只接受`~/.xiaoh/config.json`中配置的唯一Obsidian Vault；显式指向其他Vault、包含`..`或通过符号链接逃逸的文件/命令调用会在执行前被拒绝。
- `xiaoh-update`：备份后同步当前插件版本，保留本地路径和知识。
- `xiaoh-task-closeout`：任务或稳定阶段完成后立即按意图域写入当日记录；业务项目刷新项目进度，全局能力和Playbook平台使用各自记录，不等待定时任务。
- `xiaoh-project-progress`：根据已收口结果刷新项目当前阶段、工作线、阻塞、风险和下一里程碑。
- Obsidian个人工作台：使用原生Bases从统一属性生成今日重点、待确认、当前项目、进行中任务、最近成果和知识候选；个人偏好与项目总览只初始化一次，不在插件更新时覆盖。
- `xiaoh-daily-progress`：定时推送已经即时收口的每日成果，并报告缺少收口键的已完成任务，不补写项目总结。
- `xiaoh-knowledge-review`：每周只评审每日记录中的知识候选，不自动覆盖正式知识。
- 托管任务只通过Codex支持的定时任务能力创建或更新；小H不直接修改内部automation TOML。每日任务由小H管理为启用，每周任务管理为暂停；绑定和Doctor都会读取实际任务文件核对名称、提示词和状态，能力不可用或运行态漂移时报告`degraded`，不影响小H核心能力。
- 8个通用专业角色：Java探索、Java架构、Java实现、前端实现、PKI领域、PKI安全、测试验证、代码质量评审。
- 5个通用方案Skill：需求工件路由、Spec/RFC、方案评审、OpenSpec一致性评审、适用性工程。

小H不是子Agent，插件不会创建`agents/xiaoh.toml`。

## 更新

先更新插件，再新建任务说：

```text
小H，更新本地运行环境
```

更新会备份现有全局配置和Vault，然后执行完整静态校验。Hook内容变化后必须重新审核信任。

## 开发验证

```bash
python3 plugins/xiaoh/scripts/xiaoh.py plan --json
python3 plugins/xiaoh/scripts/xiaoh.py setup --json
python3 plugins/xiaoh/scripts/xiaoh.py doctor --json
```

业务任务的结构化上下文还可按动作验证需求门禁：

```bash
python3 ~/.codex/agent-system/validate.py \
  --requirement-gate /absolute/path/to/task-context.json \
  --action task_create
```

插件发布前还需运行Plugin与Skill校验器。详见[SECURITY.md](SECURITY.md)。
