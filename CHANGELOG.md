# 变更记录

## 2.17.3 - 2026-07-29

- Playbook受管任务只有一个member且由根线程直接实现时，本地专业评审改用独立的`local_review`绑定，不再复用root-owned worker凭证。
- `code_quality_reviewer`和`test_integration_verifier`分别绑定`code_review`与`verification`，并校验当前任务状态、member worktree、授权范围和唯一评审对象摘要。
- 专业Agent继续拒绝`recommended_executor=main_agent`的worker凭证；实现权限与只读评审权限保持分离。
- 新增单member、root-owned worker与双专业评审组合回归，防止相同版本源码与部署运行时再次产生能力误判。
- 本次发布只调整小H，不修改Playbook CLI版本。

## 2.17.1 - 2026-07-28

- `status_review`改为只接受schema 1.6稳定任务上下文，不再依赖schema 1.5中的运行时绑定字段。
- 稳定上下文只保存Playbook任务身份和授权范围；`binding_kind`、`stage`、worker source、凭证路径和评审工件字段只要出现就拒绝，包括`null`和空列表。
- `capture-review`从命令参数生成完整评审工件清单，并在短时凭证中绑定工件内容、任务状态语义和授权范围。
- 一次性执行绑定的`subject_digest`必须等于凭证中的`artifact_manifest_sha256`，防止凭证与实际评审对象不一致。
- 四个只读动作和两类Playbook状态契约完成schema 1.6正反回归；legacy状态继续仅供worker绑定兼容。

## 2.17.0 - 2026-07-28

- 新增面向使用者的[小H说明](docs/xiaoh-guide.md)，直接说明怎么沟通、任务怎么推进、什么时候需要人工决定，以及独立模式、Playbook和Obsidian各自承担什么。
- 插件内置`xiaoh:humanizer`，写给用户阅读的README、说明、方案、总结和交接材料在交付前执行初稿、AI写作痕迹审查和最终修订。
- 用户显式点名独立`humanizer`时优先使用指定Skill；换机或独立安装时由插件内置版本提供相同的基础写作门禁。
- 文风编辑仅处理自然语言表达，不改写代码、命令、机器可读工件、证据和需要精确措辞的契约条款。
- 重新整理README、实现设计入口和Playbook关系说明，减少重复介绍，并保留维护和发布所需的技术细节。

## 2.16.1 - 2026-07-28

- 将Playbook CLI安装、升级、降级、重装、版本切换和安装源切换固定为用户人工维护边界；小H及专业Agent只做版本、命令路径、包来源和兼容性的只读核对。
- 明确业务任务中的“继续”或自动推进授权不包含Playbook版本变更；Playbook输出的升级命令只作为人工建议报告。
- 规则进入可跨电脑部署的公共契约，Doctor同时检查捆绑源码与当前生效`AGENTS.md`是否完整承接。
- 保持治理约束而不安装命令级机械门禁，用户在Codex外部终端维护Playbook不受影响。

## 2.16.0 - 2026-07-27

- 任务上下文升级到schema 1.6：稳定目标、范围、角色、动作和受管任务身份产生确定性`authority_hash`，具体Agent实例与短时凭证不再污染长期授权。
- 新增`xiaoh-delegation-binding/v1`一次性执行绑定，按角色命名空间生成跨轮唯一`task_name`，绑定动作、评审轮次、对象摘要、根会话和可选Playbook收据。
- `PreToolUse → SubagentStart → SubagentStop`生成schema 1.3认证证明，阻断错误角色、动作、命名空间、上下文替换、重放、跨会话消费和Hook漂移。
- 本地多轮评审改为绑定稳定`authority_hash`；各轮独立保存执行绑定、Agent会话、证明、运行记录和Playbook收据，收据刷新不再使既有历史证据失效。
- 新增schema 1.5到1.6的不可覆盖迁移命令；旧上下文继续用于只读历史审计，不伪造为新证据。
- Windows PowerShell入口收敛为同一Python Hook的薄启动器，macOS、Linux和Windows共享一套门禁实现。
- 新增独立模式多轮唯一名称、受管模式收据刷新、错误命名空间、迁移和schema 1.3证明正反回归。

## 2.15.0 - 2026-07-27

- 新增`xiaoh-local-review` Skill：所有实现任务在交付前执行至少两个独立判断角色的一轮多角色评审、问题修复和收敛复审。
- 新增`xiaoh-local-review/v1`确定性清单校验：绑定当前任务上下文、交付模式、干净单仓Git HEAD或真实工件清单摘要、连续评审轮次、角色证据和最终结论；代码或工件变化使旧清单失效。
- 每轮证据使用`xiaoh-local-review-evidence/v1`反向绑定评审角色、轮次、对象、结论和唯一schema 1.2认证运行记录；跨轮复用、失败gate、未认证报告和多仓漏绑均失败关闭。
- Validator要求所有`implementation`任务至少配置两个独立评审角色，并在实现任务收口时要求证据目录中存在且仅存在一份当前有效的最终清单。
- 明确双模式交付：未受管项目由小H本地评审闭环独立完成，Playbook受管项目在本地通过后才进入handoff、MR Ready和远程AI评审。
- Playbook CLI存在不再影响模式判断；受管任务不可用时失败关闭，未受管任务不因安装CLI而切换。
- Playbook远程`disabled`、`skipped`和`accepted_without_verdict`固定为例外处置，不等价于质量通过或人工Approval。
- Playbook 0.0.40-snapshot适配器兼容当前Task Truth状态契约，包括多member的`mixed`聚合事实和`code_view.cleaned`未清理证明，并保留旧`current_state`契约的向后兼容与状态来源重验。
- 捆绑Skill数量增加到19个，并更新README、实现设计、Playbook关系和治理文档。

## 2.14.0 - 2026-07-26

- 新增`xiaoh-project-recall` Skill：Workspace识别后按主题定向读取项目进度、已验收任务、规范需求基线和正式知识，并与当前代码、配置和任务状态对账。
- 任务上下文升级到schema 1.5，业务任务绑定`xiaoh-project-recall/v1`清单的绝对路径、SHA-256、任务ID、Workspace、任务关系和完成时间。
- Validator新增项目历史召回硬门禁：召回未完成、跨任务复用、过期、哈希不符、当前平台未绑定、越出配置Vault、空历史缺少索引证据、重复文件身份、需求基线缺少稳定确认点、仅有每日摘要或缺少当前事实来源时，拒绝需求工件路由、正式委派和后续业务生命周期动作。
- 旧schema仅允许根线程只读审计；任何意图域的正式专业Agent委派都要求schema 1.5。
- `SubagentStart`在消费一次性委派意图时重新运行完整任务上下文校验，阻断prepare之后发生的召回清单或来源内容漂移；校验进程超时或异常时强制降级为未授权只读。
- 历史来源、索引和当前事实的SHA-256改为流式计算，降低大文件校验的内存放大风险。
- macOS与Windows均通过当前Python Hook的真实`prepare → SubagentStart → SubagentStop` CLI链路自检，并覆盖带空格和非ASCII字符的配置、运行时与转录路径。
- 明确Playbook只补充当前受管任务事实，不替代小H的项目历史召回；没有Playbook时召回门禁仍独立生效。
- 捆绑Skill数量增加到18个，并更新README、实现设计、Playbook关系和治理文档。

## 2.13.0 - 2026-07-26

- 小H核心与Playbook适配解耦：没有Playbook的用户仍获得完整核心能力，普通任务不会因本机存在Playbook命令而进入受管流程。
- 本地配置新增`integrations.playbook`三态：`auto`仅在任务明确受管时激活，`enabled`要求兼容，`disabled`跳过探测并禁止受管委派。
- Doctor分开报告核心健康和可选集成状态；`auto`模式缺少Playbook显示`not_enabled`且不再造成核心降级，显式`enabled`缺失或不兼容仍显示`degraded`。
- 安装时把实际本地配置绝对路径绑定到四个Hook命令；使用非默认`--config`时，委派门禁和Vault门禁不再回退读取另一份默认配置。
- 可选插件和外部增强能力只有在`required`或`recommended`级别时影响总状态，纯`optional`缺失只记录能力状态。
- Playbook的具体捕获、时效和重验流程收敛到`xiaoh-playbook-adapter` Skill；公共契约只保留按任务激活与失败关闭边界。

## 2.12.0 - 2026-07-25

- 新增`xiaoh-playbook-adapter`，只读取Playbook现有worker JSON和完整task status JSON，不修改Playbook源码、配置、任务或Git状态。
- 区分小H长期`xiaoh_workspace_id`与Playbook当前`task_workspace_id`，并将member、worktree、allowed scope和delegated action绑定到默认15分钟有效的可验证凭证。
- 正式委派Hook和schema 1.4校验器验证凭证文件、来源哈希、身份、范围、动作和时效；旧受管上下文只能继续只读，不能绕过新门禁。
- 捕获拒绝超过两分钟、顺序错误、终态或worktree不一致的原始快照；委派准备和SubagentStart均重新读取当前只读task status，所有delegated scope逐项收紧到任务授权范围。
- 凭证15分钟时效仅用于授权和启动；历史收口按当时Agent启动事实审计，不因正常任务耗时而失效。
- Doctor探测Playbook CLI版本及只读接口兼容性；不兼容时小H全局能力保持可用，但Playbook受管业务委派失败关闭。
- macOS与Windows统一使用同一Python委派Hook，减少双实现语义漂移。

## 2.11.0 - 2026-07-24

- 新增`xiaoh-requirement-baseline`，在业务规则或结果性设计逻辑确认、纠正、拒绝或取代后立即维护主题基线。
- 每个业务主题持续维护一份规范页面；确认点使用稳定ID和四态模型，疑问、假设、推荐及无来源固定值不得冒充已确认需求。
- 新增受管业务逻辑基线模板，记录业务规则、设计原因、证据来源、适用边界、验收条件及Spec+RFC/OpenSpec/任务追溯。
- 新增确定性基线校验器，检查稳定ID、合法状态、确认来源、取代关系和不可逆状态转换。
- Workspace配置异常时安装、更新和注册均失败关闭，不再静默清空或扩大冲突；路径绑定按平台保存，支持Windows与macOS迁移后安全重绑定。
- 知识晋升只引用业务基线及稳定确认点ID，不再复制业务规则形成竞争事实源。
- 任务收口、项目进度、每日推送和知识晋升只引用业务基线，不再各自事后重建竞争版本。

## 2.10.0 - 2026-07-24

- 新增`xiaoh-workspace-routing`，以Workspace作为业务项目和系统的自动识别入口。
- 未登记Workspace由小H先只读调查、带推荐归属询问一次；确认后持久化，后续不重复询问。
- 本地配置新增稳定`workspace_id`、项目、系统和本机绝对路径映射；冲突映射禁止静默覆盖。
- Setup和Update保留既有Workspace注册，Doctor验证重复归属、无效配置和跨电脑失效路径。
- 任务收口和项目进度在业务写回前统一复用Workspace归属，避免成果落入错误项目。

## 2.9.0 - 2026-07-23

- 将Obsidian从单一工作驾驶舱升级为“工作台 + 知识库”双入口：工作台回答当前进度，知识库保存可长期解释和复用的结论。
- 正式知识分为项目知识、领域知识、可复用方法和个人系统四类；每日记录、项目进度与知识候选继续作为证据和中间状态，不冒充正式知识。
- 新增`xiaoh-knowledge-promotion`，按证据、适用边界和来源把候选晋升到唯一知识层，并回写来源关系。
- 新增知识库Bases、项目知识模板、领域知识模板、复用卡模板、个人系统说明和知识评审模板。
- Agent协作目录与进化台账归入个人系统；更新器安全迁移既有位置并保留个人台账内容。
- 修正仓库根`VERSION`与插件清单版本不一致的问题。

## 2.8.0 - 2026-07-23

- 新增Obsidian原生Bases个人开发工作台，统一展示今日重点、待确认、当前项目、进行中任务、最近成果和知识候选。
- 项目、进度、方案、知识、验证、运行手册和工作记录模板统一采用`type/status/health/owner/next_action`属性模型。
- 更新器通过既有受管模板哈希安全升级旧模板，继续保留无法确认来源的个人修改；个人工作偏好和项目总览只在缺失时初始化。
- `xiaoh-task-closeout`新增知识候选工作台投影，`xiaoh-project-progress`负责维护项目首页和进度页属性，周评审只更新候选评审状态，不自动提升知识。
- 既有项目知识页不会由安装器批量改写，需由交互式小H基于真实证据逐页归一化。

## 2.7.0 - 2026-07-23

- 新增`xiaoh-task-closeout`和`xiaoh-project-progress`：任务或阶段验收后立即写入当天成果，并同步刷新项目进度。
- `xiaoh-daily-progress`调整为每日成果推送，只读取已收口结果并报告遗漏，不再承担延迟总结或知识补写。
- `xiaoh-knowledge-review`继续每周评审已收口记录中的知识候选。
- 工作记录改为按`closeout_key`即时追加或更新任务成果，并新增项目进度模板。
- Doctor新增已启用插件、当前线程Skill、托管任务实际状态和Vault受管模板版本核对，避免配置声明与真实运行状态不一致。
- 更新器对已知旧模板做安全迁移，保留无法确认来源的用户修改并报告冲突；本地配置改为原子替换和备份。
- 收口键改由稳定任务ID、阶段ID和已验收修订确定性生成，并补齐全局Agent能力与Playbook平台的非项目归档路径。
- 源码安装明确区分核心部署与交互式托管任务初始化，未完成绑定时只报告`degraded`。
- 普通Codex任务的收口键从运行时`CODEX_THREAD_ID`与验收证据内容生成，拒绝人工替代线程ID或自由填写修订。
- 本地配置读改写增加跨平台进程锁；Doctor新增重复托管任务检测。
- macOS与Windows验证入口纳入CI smoke test，并明确命令行不冒充当前Codex任务的实际Skill加载证明。

## 2.6.0 - 2026-07-23

- 新增`xiaoh-daily-progress`和`xiaoh-knowledge-review`，分离每日事实归档与每周知识候选评审。
- 增加版本化托管任务模板、本机逻辑ID到实际任务ID绑定，以及静态漂移诊断。
- Setup、Update和Doctor改为通过Codex受支持的定时任务能力协调生命周期，禁止直接修改内部automation TOML。
- 更新时保留既有托管任务绑定和其他本地配置；自动化不可用或未绑定时降级，不影响小H核心能力。
- 工作记录增加来源、归档键、实际变更和知识候选字段，并新增知识候选评审模板。

## 2.5.1 - 2026-07-22

- 修复更新流程覆盖既有Obsidian知识文件的问题；已有知识与模板只保留，缺失文件才初始化。
- Vault中的公共规则和Agent角色目录仍作为受管文件同步，其他页面不再参与占位符替换。
- 增加重复更新保留Agent进化台账内容的回归测试。

## 2.5.0 - 2026-07-22

- 新增“证据优先的建设性异议”公共契约，禁止把提问、质疑或假设直接当成已确认需求变更。
- 任务上下文升级到schema 1.4，记录用户行为分类、证据状态、重大冲突、影响说明和范围缩减依据。
- 范围缩减或兼容默认值必须由可定位证据或知悉影响后的明确业务决策支撑；高风险缩减要求独立评审通过。
- 专业Agent输出统一增加证据依据、重大冲突、不确定项和推荐结论，避免无证据迎合或表演式反对。
- 新增六类交互回归基线及问题误判、缺证据缩减、无来源默认值、高风险未评审缩减的校验器自检。

## 2.4.0 - 2026-07-22

- 新增唯一Obsidian Vault写入门禁，拒绝其他Vault、`..`路径和符号链接逃逸。
- Doctor增加插件/运行时版本漂移、唯一Vault配置、`.obsidian`标记和第四个Hook检查。
- 增加诱饵Vault、配置缺失和跨平台Hook自检；知识写回必须报告配置根路径和实际文件路径。
- 纠正既有误写不再自动删除、移动或覆盖，必须单独取得授权。

## 2.3.0 - 2026-07-21

- 固定Spec+RFC准入评审与OpenSpec一致性评审两道生命周期门禁。
- 将评审Skill、证据路径和Spec+RFC修订号写入可验证状态，旧版报告不能通过新修订门禁。
- 增加`spec_rfc_confirmation`校验动作，评审未通过时不得提交用户确认。
- 明确插件命名空间只表示Skill来源，不代表同名子Agent。
- 两道评审默认使用小H插件内置的命名空间Skill，同时兼容已有全局副本。

## 2.2.0 - 2026-07-21

- 增加机器可读的Skill、配套插件和外部能力清单。
- 初始化和更新时自动安装可用的Codex配套插件，不再依赖人工逐项执行README。
- Doctor增加完整、降级和缺失能力诊断。
- 将代码知识图谱调整为可选增强；未安装时自动回退到本地代码搜索。

## 2.1.1 - 2026-07-21

- 增加macOS与Windows GitHub Actions验证矩阵。
- 增加双系统安装、诊断和`develop`分支使用说明。
- 修正Windows下Hook路径分隔符造成的配置漂移误判。
- 固定命令行输出为UTF-8，避免Windows默认代码页无法输出中文诊断。
- 为PowerShell入口保留UTF-8 BOM，兼容Windows PowerShell 5.1读取中文脚本。

## 2.1.0 - 2026-07-21

- 增加业务需求工件路由和总体需求基线门禁。
- 新增`xiaoh-requirement-routing` Skill。
- 增加显式Skill执行状态、Spec+RFC、OpenSpec追溯与遗漏补救状态。
- 增加member确认、task create、OpenSpec确认、task start和实现前的确定性校验入口。
- 补充需求工件路由回归案例。

## 2.0.0 - 2026-07-21

- 改造成Codex原生Marketplace Plugin。
- 新增`xiaoh-core`、`xiaoh-setup`、`xiaoh-doctor`、`xiaoh-update`。
- 使用单一跨平台Python运行器完成备份、安装、更新和诊断。
- 保留显式Hook信任门禁，不在插件安装阶段隐式修改全局配置。
- npm发布继续延后。

## 1.4.0 - 2026-07-21

- 将小H完整拆分为可移植的通用协调能力。
- 移除客户、项目、仓库、真实证据和本机路径。
- 增加 macOS/Linux、Windows 安装与隔离验证能力。
- 支持通过 `CODEX_HOME` 和 `XIAOH_VAULT` 配置目标目录。
- 保留根线程身份门禁、专业角色、任务证据协议和空白 Obsidian 模板。
- 仓库仅保留可安装源码；发行压缩包和校验产物不纳入版本控制。
- 增加不受 Git 跟踪的 `config.local.json` 本地路径配置。
