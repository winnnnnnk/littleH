# 小H Codex Plugin

[![Cross-platform](https://github.com/winnnnnnk/littleH/actions/workflows/cross-platform.yml/badge.svg?branch=develop)](https://github.com/winnnnnnk/littleH/actions/workflows/cross-platform.yml?query=branch%3Adevelop)

小H是Codex根对话中的研发协调者。你可以直接说目标、现象或想法，小H负责核对事实、提出推荐方案、协调专业Agent、验证结果，并把已经验收的内容写入长期知识库。

小H不会把疑问当成需求变更，也不会因为用户的一句反问就删除范围。用户说法与代码、配置、数据或运行证据不一致时，小H会说明冲突和影响，再给出推荐结论。

仓库只包含通用能力，不保存客户资料、具体项目、真实任务证据、账号或凭据。

## 先看哪份文档

- [认识小H](docs/xiaoh-guide.md)：适合第一次使用，说明怎么沟通、任务怎么推进、什么时候需要人工决定。
- [小H实现设计](docs/implementation-design.md)：面向维护者，说明组件、门禁、Agent体系和Obsidian结构。
- [小H与Playbook的关系](docs/xiaoh-playbook-relationship.md)：说明独立模式和Playbook受管模式如何分工。
- [安全与可信边界](SECURITY.md)：说明Hook、权限、凭据和治理信任边界。

## 支持环境

| 系统 | 安装入口 | 自动验证 |
| --- | --- | --- |
| macOS | `install.sh` | Python、JSON、隔离安装、Hook自检 |
| Windows | `install-windows.cmd`或`install.ps1` | Python、JSON、隔离安装、跨平台Hook自检 |

两端都需要Git、Python 3和Codex CLI。Obsidian不是初始化的硬依赖；如果要使用小H的个人研发系统，建议安装Obsidian 1.9或更高版本。

## 从GitHub安装

当前发布分支是`develop`：

```bash
codex plugin marketplace add winnnnnnk/littleH --ref develop
codex plugin add xiaoh@xiaoh
```

重新打开Codex，然后说：

```text
小H，初始化当前电脑。
```

初始化程序会部署小H的20个Skill、8个专业Agent、公共契约、Hook和空白Vault模板。默认路径是：

- Codex：`~/.codex`
- Obsidian：`~/obsidian/development-vault`
- 小H配置：`~/.xiaoh/config.json`

初始化结束后重启Codex，在`/hooks`中审核并信任Agent委派、Vault路径、`SubagentStart`和`SubagentStop`四个Hook。随后说：

```text
小H，检查当前环境、Hook和可选集成。
```

macOS可以运行`./verify.sh --runtime`，Windows可以运行`.\verify.ps1 -Runtime`。命令行不能证明某个Codex任务实际加载了哪一版Skill，因此完整版本检查仍要在重启后的新任务中调用`$xiaoh-doctor`。

## 从源码安装

macOS：

```bash
git clone -b develop https://github.com/winnnnnnk/littleH.git
cd littleH
chmod +x install.sh verify.sh
./install.sh
./verify.sh
```

Windows：

```powershell
git clone -b develop https://github.com/winnnnnnk/littleH.git
cd littleH
.\install-windows.cmd
```

也可以使用PowerShell入口：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1
.\verify.ps1
```

源码安装器会注册当前目录为本地Marketplace、安装`xiaoh`插件并部署运行时。Codex定时任务只能通过应用提供的任务工具创建，所以命令行安装可能暂时显示`degraded`。重新打开Codex并完成初始化后，小H会读取真实任务状态并完成绑定。

## 主要能力

- 主动整理用户目标，带着推荐方案提问，而不是让用户设计流程。
- 区分疑问、假设、事实纠正、业务决定和执行指令。
- 根据Workspace识别项目与系统，定向召回已验收历史。
- 维护需求与设计基线，按复杂度路由Spec+RFC、OpenSpec或专用Skill。
- 使用专业Agent完成探索、实现、测试和独立评审。
- 所有实现先经过本地多角色评审和收敛复审。
- 任务或稳定阶段完成后立即收口，并刷新业务项目进度。
- 将工作台与正式知识库分开，避免把每日流水当成长期知识。
- 使用`xiaoh:humanizer`整理写给用户阅读的文档，同时保留精确技术语义。

小H不是子Agent，插件不会创建`agents/xiaoh.toml`。

## 可选能力

依赖事实源是`plugins/xiaoh/dependencies.json`。

Ponytail用于已确认方案的代码实现阶段。浏览器、文档、PDF、表格、演示、站点和可视化插件按需安装。`codebase-memory-mcp`可以提供代码知识图谱，缺失时小H改用本地搜索。

Playbook是可选的受管研发平台。只有任务明确由Playbook管理时，小H才启用适配器。机器上存在`playbook`命令不会改变普通任务的流程。

Playbook CLI的安装、升级、降级、重装、版本切换和安装源切换由用户在Codex外部终端人工完成。小H只读检查版本、路径、包来源和兼容性，不会替用户修改Playbook。

`~/.xiaoh/config.json`中的集成模式可以设为：

```json
{
  "integrations": {
    "playbook": "auto"
  }
}
```

- `auto`是默认值。普通任务不探测缺失CLI，受管任务要求接口兼容。
- `enabled`要求Playbook可用；缺失或不兼容时受管委派失败关闭。
- `disabled`跳过探测并禁止Playbook受管委派。

## 更新

先更新插件，再新建Codex任务并说：

```text
小H，更新本地运行环境。
```

更新程序会备份现有全局配置和Vault，再同步当前插件版本。Hook内容变化后需要重新审核信任。

## 开发验证

```bash
python3 plugins/xiaoh/scripts/xiaoh.py plan --json
python3 plugins/xiaoh/scripts/xiaoh.py setup --json
python3 plugins/xiaoh/scripts/xiaoh.py doctor --json
```

任务上下文、需求门禁和本地评审清单由`validate.py`验证。完整命令与发布检查见[小H实现设计](docs/implementation-design.md#20-验证入口)和[安全与可信边界](SECURITY.md)。
