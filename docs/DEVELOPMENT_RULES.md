# Sub2API 开发规范

> 本文是 Sub2API 定制开发的强制规范，适用于 `backend/`、`frontend/`、插件协议、数据库迁移、部署脚本、CI 与技术文档。
>
> 结构参考 `maas/docs/DEVELOPMENT_RULES.md`，保留效力等级、变更纪律、关键不变量、验证门禁（Gate）、文档同步与完成清单；技术要求依据本仓库实际实现重新制定。
>
> 核对基线：2026-09-29 的仓库代码、`DEV_GUIDE.md`、`docs/SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md`、各领域文档、Makefile 与 `.github/workflows/`。版本、路径和命令发生变化时，必须同步修订本文。

## 1. 规范效力与阅读入口

- **必须（MUST）**：不可省略，违反时阻断合入。
- **禁止（MUST NOT）**：不得出现在正常开发或产品路径中。
- **应该（SHOULD）**：原则上遵守，偏离时必须在评审中说明理由、风险与验证结果。
- **可以（MAY）**：在不破坏不变量的前提下允许选择。

项目约定的执行优先级为：当前任务中用户明确要求 → 本文的开发规范与 Gate → 对应领域文档 → `DEV_GUIDE.md` 的环境指导 → 相邻代码风格。用户对功能的要求不能被理解为默认允许破坏鉴权、计费或数据完整性；出现冲突时必须明确说明并解决。

本文作为定制开发的规范与阅读索引，领域文档入口如下：

| 范围 | 必读资料 |
| --- | --- |
| 架构总览、修改入口与强制变更索引 | [ARCHITECTURE_AND_MODIFICATION_GUIDE.md](ARCHITECTURE_AND_MODIFICATION_GUIDE.md)；任何代码改动必须同批更新，见 §19 |
| 项目能力与部署概览 | [README_CN.md](../README_CN.md)、[DEV_GUIDE.md](../DEV_GUIDE.md) |
| 定制开发、分支与上游同步 | [定制开发与官方代码同步操作手册](SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md) |
| 数据库迁移 | [迁移说明](../backend/migrations/README.md)、`backend/internal/repository/migrations_runner.go` |
| 组合分组与跨平台路由 | [COMPOSITE_GROUPS.md](COMPOSITE_GROUPS.md) |
| 异步图片与批量任务 | [ASYNC_IMAGE_TASKS.md](ASYNC_IMAGE_TASKS.md)、[BATCH_IMAGE_MVP.md](BATCH_IMAGE_MVP.md) |
| Seedance 原生视频任务 | [seedance-api.md](seedance-api.md) |
| 支付 | [PAYMENT_CN.md](PAYMENT_CN.md)、[PAYMENT.md](PAYMENT.md)、[管理端支付集成 API](ADMIN_PAYMENT_INTEGRATION_API.md) |
| 插件 | [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)、[pluginapi](../backend/pkg/pluginapi/README.md) 及其 `docs/` |
| 部署与边缘安全 | [deploy/README.md](../deploy/README.md)、[DOCKER.md](../deploy/DOCKER.md)、[EDGE_SECURITY.md](../deploy/EDGE_SECURITY.md) |
| 渠道监控 | [安全默认值说明](channel-monitor-v2-safe-defaults.md) |
| 管理控制台合规确认与品牌归属 | [中文承诺](legal/admin-compliance.zh.md)、[英文承诺](legal/admin-compliance.en.md) |

文档与实现冲突时，**必须**核对源码、测试、生成配置与 Git 历史，不能把旧示例当作现行能力。本文记录的流程约束必须落实；描述已有行为的内容必须有实现依据。计划中的能力必须明确标为计划。

本项目没有 maas 的 `relaykit/`、React/Bun 工程、GORM 三数据库兼容要求或 AGPL/QuantumNous 版权检查，**禁止**机械移植这些约束。[架构与修改指南](ARCHITECTURE_AND_MODIFICATION_GUIDE.md) 是本项目理解、定位、修改和验证的总览与索引；本文负责定义强制开发规范，两者必须与实际代码同步维护。

### 1.1 领域文档的适用边界

本节对照 `docs/` 中各领域文档（含 `legal/` 中英文文件）与当前实现，汇总需要特别说明的边界。操作示例、特定 PR 的范围限制、历史验证记录和未来方案不能直接提升为全项目永久规则。已核对的差异如下，开发时必须以对应实现和测试确认：

| 文档描述 | 当前适用边界 |
| --- | --- |
| `PAYMENT.md` / `PAYMENT_CN.md` 的迁移对比表称内置订阅“计划中” | 已有 `payment_fulfillment.go` 的订阅履约和 Composite 订阅套餐路径；不能据旧表禁用或重复实现订阅支付。中英文支付指南也未完全同步移动端当面付说明。 |
| `ADMIN_PAYMENT_INTEGRATION_API.md` 称缺少幂等键必定返回 400 | handler 要求键，但 `service/idempotency.go` 的 `ObserveOnly` 允许缺键执行；只有启用强制校验且接入 coordinator 时才有该拒绝行为，见 §7.1。 |
| 同一文档将创建兑换码并兑换描述为“原子完成” | `admin/redeem_handler.go` 实际先创建、再兑换，并支持创建后中断的恢复；这是单接口业务操作，不代表两步处于同一数据库事务，必须验证中间失败与重试。 |
| `PLUGIN_DEVELOPMENT.md` 的 Go 1.21、示例工具和宿主测试命令 | 宿主工具链以 `backend/go.mod` 为准；插件示例仓库尚未提供，示例 `build.sh` / `tools/keygen` 不是本仓库已有工具；宿主测试必须从 `backend/` 模块执行，见 §17。 |
| 渠道监控设计稿的历史迁移改写与分块上限 | 仅说明特定历史兼容处理，不豁免 §6 的迁移不可变规则；当前较早历史回填有按天对齐逻辑，实际查询窗口不能只按设计稿的小时上限推断，见 §10.1。 |
| `BATCH_IMAGE_MVP.md` 的“未来下载卸载”、历史云端验证和稳定化 PR 范围 | 不代表已实现对象存储直链下载、所有提供方已完成真实生图验证，或永远禁止新增能力；必须区分当前 MVP、配置默认值与后续扩展。 |

下文提炼领域开发契约，不复制提供商推广内容、真实部署参数或整套 API 示例；完整操作说明仍由 §1 的来源文档维护。

## 2. 开工与变更范围

每项开发开始前**必须**：

1. 阅读本文、[架构与修改指南](ARCHITECTURE_AND_MODIFICATION_GUIDE.md) 及 §1 中与任务有关的文档，先查找并阅读真实代码，再制定修改方案。
2. 执行 `git status --short --branch`，识别并保留用户已有修改、未跟踪文件与当前分支。
3. 查找相邻实现、接口、测试、配置入口和历史决策，明确变更所有者。
4. 确认影响是否涉及鉴权、账户调度、模型映射、计费、迁移、缓存、前端或部署。
5. 选定 §17 的验证集合；高风险变更先记录原始行为、目标行为、兼容边界和回滚方式。

变更**必须**职责集中、可评审、可回滚。**禁止**顺手重构、全目录格式化、整目录覆盖上游代码、清理用户文件或夹带无关依赖升级。品牌调整、计费规则、协议转换和数据库迁移应该拆成可独立审查的步骤。

**禁止**提交真实凭据、用户数据、请求抓包、运行日志、数据库备份、`.DS_Store`、`node_modules/`、编译二进制或 `backend/internal/web/dist/` 构建产物。Ent、Wire、protobuf 等受版本管理的生成源码按 §15 处理，不属于禁止提交的构建产物。

## 3. 定制边界、分支与上游同步

- **必须**遵循同步手册：`main` 保持可发布；开发使用 `feature/*`、`fix/*` 或 `hotfix/*`；上游升级使用独立 `sync/upstream-*` 分支。
- **禁止**向 `upstream` 推送，或对已共享、已部署的 `main` rebase、强制推送。远端地址以 `git remote -v` 为准，不沿用旧文档中的其他 Fork 地址。
- 定制优先级**应该**为：已有配置/数据库设置 → 合适的插件扩展点 → 独立文件、服务或组件 → 稳定边界的接口扩展 → 必要的核心流程修改。
- **禁止**将尚不存在的插件能力当作通用扩展点。现有传输插件不能自动承担账户选择、鉴权或计费职责。
- 自定义域名、密钥、价格、模型清单和部署参数**禁止**硬编码在业务流程中。新增行为开关必须有默认值、关闭行为和回归测试，默认应保持已有部署的兼容性。
- 核心流程定制**必须**记录业务需求、上游原始行为、差异、兼容边界、测试与回滚方案，供后续合并冲突时判断。
- 上游同步**必须**记录起止 commit、依赖与配置变化、迁移和冲突处理原则，逐处审查 `rerere` 复用结果；**禁止**批量选择全部 `ours` 或 `theirs`。
- 生产发布**必须**可追溯到定制版本、上游基线和完整 commit；不得将持续变化的 `upstream/main` 或 `latest` 作为唯一发布标识。
- **应该**至少每周检查上游、逐次评估正式 Release，并及时评估安全修复。紧急补丁可在 `hotfix/*` 精确 cherry-pick，必须记录来源、验证并后续完成正常同步；不得以长期零散 cherry-pick 替代上游合并。定制版本推荐 `<上游版本>-custom.<修订号>`。

## 4. 架构、分层与所有权

技术栈：Go + Gin + Ent + Wire，业务持久化使用 PostgreSQL，Redis 承担缓存、限流等能力；前端使用 Vue 3 + TypeScript + Vue Router + Pinia + Vite + Tailwind CSS 3 + vue-i18n，包管理器为 pnpm。

| 目录 | 职责与修改边界 |
| --- | --- |
| `backend/cmd/server/` | 启动、生命周期、版本与 Wire 依赖装配 |
| `backend/internal/server/` | HTTP 服务、`routes/` 路由和 `middleware/` 中间件 |
| `backend/internal/handler/` | 输入校验、协议入口、调用服务与响应输出 |
| `backend/internal/service/` | 业务规则、调度、计费及供实现层满足的接口 |
| `backend/internal/repository/` | PostgreSQL/Ent/SQL、Redis 访问与迁移执行 |
| `backend/ent/schema/`、`backend/migrations/` | 数据模型源定义与持久化演进 |
| `backend/internal/pkg/`、`backend/internal/util/` | 协议工具、HTTP、日志、错误、脱敏等共享能力 |
| `backend/internal/payment/` | 支付提供方集成 |
| `backend/pkg/pluginapi/` | 公开插件协议与 SDK |
| `backend/internal/web/` | 前端嵌入、静态资源和公开设置注入 |
| `frontend/src/` | 管理端、用户端与公共页面 |

请求方向通常为 `routes → handler → service → repository 实现`，但编译期依赖**必须**通过服务层接口倒置：`service` 不直接导入 `repository`。`backend/.golangci.yml` 的 depguard 还限制 handler/service 直接依赖 Redis 与 GORM；已有明确白名单不是新增违规依赖的理由。

handler **应该**保持输入/输出与编排职责，新增数据库操作放入 repository；业务规则放在 service。已有特殊实现不能作为扩大跨层耦合的依据。新增构造器、接口或依赖时，**必须**同步 Wire provider、所有调用点和相关 stub/mock。

## 5. 网关、调度与协议兼容

网关路由入口为 `backend/internal/server/routes/gateway.go`，按平台分发到现有 Gateway、OpenAI、Gemini 等 handler/service；管理 API 使用 `/api/v1`。本项目不是 maas 的 `controller.Relay` 单入口结构。

- 新接口**必须**接入已有路由和对应服务链路，保留鉴权、请求体限制、模型准入、分组限制、调度、并发控制、计费与诊断；**禁止**新增绕开这些机制的直连上游路径。
- **必须**保持模型白名单检查在 API Key 鉴权之后、组合路由改写之前，依据客户端提交的模型名检查，不能通过映射或切换平台绕过限制。
- 账户选择、平台/分组归属、模型映射、粘性会话、并发槽位与故障切换**必须**复用相应平台的现有调度实现；批量编辑不得把一个平台的模型规则覆盖到其他平台。
- **必须**区分请求模型、映射模型、上游模型与计费模型；修改映射时同步验证列表展示、准入、调度和定价归属。
- HTTP 出站**应该**复用现有 client、连接池、代理与 URL 校验能力。**禁止**以关闭 TLS 验证、放开任意内网 URL 或无界重试解决连接问题。
- 重试**必须**考虑请求是否已发送、是否已产生客户端可见输出及操作是否可重复；不能在流式响应已输出后盲目切换账户并重放请求。
- SSE/WebSocket/协议转换改动**必须**覆盖事件顺序、结束标记、工具调用 ID/参数、usage、错误与取消；不得以聚合完整响应替代原有实时流式行为。
- 请求取消、超时和所有错误分支**必须**释放响应体、连接、并发槽位等资源。后台计费应使用明确生命周期的必要快照，禁止长期持有 Gin context 或完整请求体。

新增平台或扩展协议前**必须**核对：平台标识与凭据类型、路由分发、调度资格、模型映射、出站转换、流式/非流式结果、usage/计费、前端账户与分组表单、功能开关及回归测试。不能只增加前端选项。

### 5.1 Composite 分组与模型路由

依据 [COMPOSITE_GROUPS.md](COMPOSITE_GROUPS.md) 和 `backend/internal/service/composite_route_resolver.go`：

- **必须**保持“显式路由优先、账号模型归属解析其次、内置检测兜底”（`GatewayService` 装配归属 resolver）；归属歧义拒绝，归属查询失败时仅可识别模型允许检测兜底。显式匹配按 exact 优于 prefix、具体 endpoint 优于 `any`、更长 prefix、较小 priority、较小 route ID 顺序决胜。禁用规则不得参与运行时解析，预览与实际解析必须一致。
- 未知或有歧义的模型必须返回客户端错误，**禁止**猜测平台。JSON `model`、Gemini 路径模型、Live 的 `session.model`（含 multipart）必须在各自协议入口正确解析和改写；Alpha Search/Live 使用 `responses` 路由域。
- **必须**将解析出的具体平台贯穿账户调度、用户平台配额、结算、运维错误归属、渠道映射/定价及报表；不能以 `composite` 代替实际平台做这些归属。
- 组合分组的订阅套餐只授予分组访问权，不改变逐请求具体平台的计费/配额。渠道 `group_ids` 保持现有扁平载荷，映射和定价仍按具体平台组织。
- 路由别名本身不生成定价、模型元数据或上游能力；不能把组合分组宣传为已具备跨提供方 AUTO 智能路由，或允许 Key 直接绑定多个既有分组。

### 5.2 OpenAI/Grok 异步图片任务

依据 [ASYNC_IMAGE_TASKS.md](ASYNC_IMAGE_TASKS.md)、`image_task_handler.go` 和 `service/image_task.go`，此功能与 §5.3 的 Gemini 批量任务是不同链路：

- **必须**保持默认关闭、对象存储配置完整才允许提交；关闭或配置不全时返回 404，不创建任务、不写 Redis。只支持当前实现的 OpenAI/Grok 分组和媒体权限，拒绝流式提交，不能因 Composite 支持其他图片接口就推定此接口也支持。
- 提交仍复用同步图片路径的审计、调度、并发和计费。成功结果必须先将图片上传对象存储，再以 URL 替换 `b64_json`，Redis 仅保存紧凑结果；上传失败必须标记失败，不能回退存储完整 base64。
- 关闭开关只停止新提交，已接受任务仍可轮询。归属同时绑定用户与提交 Key；同用户的其他 Key 也不得读取，未知/越权任务统一返回 404。
- 提交返回 202、`Location` 和 `Retry-After`；提交/轮询保持 `Cache-Control: no-store`。默认任务状态 TTL 为最近更新后 24 小时、执行超时 30 分钟；更改时必须同时检查资源回收与客户端轮询契约。不能因生成耗尽余额阻断已有结果读取，但禁用 Key、用户、IP 和分组检查仍有效。
- 管理端存储设置优先于配置文件，只有从未保存管理设置时才回退 `image_storage`；保存须使缓存失效并在后续请求重建客户端。复用备份存储时应隔离 bucket/prefix，存储目标变更须保留已启用的 step-up 2FA。

### 5.3 Gemini 批量图片任务

依据 [BATCH_IMAGE_MVP.md](BATCH_IMAGE_MVP.md)：

- **必须**分别检查全局开关、Gemini 分组媒体权限、`allow_batch_image_generation` 与提供方凭据；`batch_image.enabled` 和 `queue_enabled` 默认关闭。`gemini_api` 使用对应 API Key 流程，`vertex` 使用对应 service-account 流程，不能把其他登录类型自动视为可用。
- PostgreSQL 是任务状态事实来源，Redis 用于唤醒、重试、领取、锁及下载限流；worker 必须先从 Redis 领取具体任务，不得改成无界数据库扫描轮询。状态转换、重复投递和 stale active 恢复须可重入。
- `output_count` 表示展开成独立上游 JSONL 请求，附件数量和解码字节预算必须按展开后计算。当前默认单项最多 4 张、单任务最多 200 张、参考附件共 1000 个、内联参考图共 128 MiB；Flash/Pro 的单项参考图能力分别为 3/14。调整配置、模型能力或校验上限时必须同步展开逻辑、估价、冻结款和 ZIP 下载限制，不能把参考图数量当作输出张数上限。
- 结果索引完成后只结算成功图片，复用 `batch_image_settlement:{batch_id}` 幂等请求 ID；失败项不收费，参考图不额外增加独立附加费。结算重试必须有界，耗尽后走幂等释放剩余冻结款路径。
- 公共接口只暴露安全的任务/条目状态，下载通过 Sub2API 代理；**禁止**返回提供方文件名、job 名、GCS 路径、签名 URL、账户秘密或把图片字节/base64 存入 PostgreSQL。此约束不适用于 §5.2 已明确支持的对象存储结果 URL。
- 读取、取消、下载、删除必须检查所有权；清理只使用服务端生成且校验前缀的存储引用。输出删除后下载返回 410 与 `BATCH_IMAGE_OUTPUT_DELETED`，不得删除其他任务/用户的对象。
- 当前默认终态后输入保留 24 小时、输出保留 72 小时、输出保留最大 7 天；保留期调整必须考虑下载、清理、计费与云存储生命周期。Vertex MVP 只承诺 `1K`/默认输出，不得未经实现与验证承诺 `2K`/`4K`。

### 5.4 Seedance 原生视频任务

依据 [seedance-api.md](seedance-api.md)、`handler/seedance.go` 和 `service/seedance.go`：

- **必须**保留 Ark 原生 `content[]`、角色及扩展参数，只按既有映射改写模型，响应维持原生格式；不能转换成 OpenAI `messages` 或 Grok `prompt`。
- 只允许具备显式 Seedance 端点能力的 OpenAI API Key 账号和正确 Base URL，并检查 OpenAI/Composite 分组及媒体权限；端点能力默认关闭，创建/编辑/批量编辑必须一致。
- 查询与删除绑定同一用户、Key、分组和原提交账号，保留 `seedance:` 任务命名空间隔离；禁止换账号查询、暴露上游任务列表或盲目重试异步创建。
- 创建时不扣 token；查询到 `succeeded` 后按实际 `usage.completion_tokens` 和创建时的模型快照结算，使用共享缓存领取与持久化请求去重防止重复扣费。不得套用 Grok 按秒费率；失败/排队/运行中不计费，删除不自动退款。
- 当前任务绑定默认保存 24 小时，且无后台轮询结算；必须准确说明需要在有效期内查询完成结果，不能把“只接回调、不查询”描述为已能自动入账。

## 6. 数据库与迁移

主业务数据库是 PostgreSQL；`go.mod` 中存在 SQLite 依赖和局部测试不意味着产品支持 SQLite/MySQL 部署。**禁止**照搬三库兼容或 GORM `AutoMigrate` 流程。

- 模型修改**必须**同时检查 `backend/ent/schema/`、Ent 生成源码、repository、DTO 和 SQL migration，不能只修改 schema 而遗漏现有数据库升级。
- 迁移由 `backend/internal/repository/migrations_runner.go` 执行，文件格式为 `NNN_description.sql`，启动时自动应用并校验 SHA256。
- 已在任何环境应用的迁移**禁止**修改、删除、重命名或重新编号。修复必须新增前向迁移；合并上游时必须检查编号/文件名冲突和实际执行顺序，不能忽略校验和错误。
- 普通 `.sql` 由 runner 包在事务中执行；`*_notx.sql` 仅用于并发索引语句，创建/删除必须使用 `IF NOT EXISTS` / `IF EXISTS`，不得混入其他 DDL/DML 或事务控制语句。
- **禁止**在同一迁移文件中追加可执行的 Down SQL；runner 不解析 goose Up/Down 分区。回退使用经过演练的新修复迁移或备份恢复。
- 当前 Makefile **没有** `migrate-up` / `migrate-down` 目标，迁移 README 中相关示例不得直接作为验证命令；应使用现有迁移测试和隔离数据库上的服务启动演练。
- SQL **必须**参数化；动态排序/列名必须白名单化。事务内操作必须复用同一事务，避免锁失效、部分写入和跨请求数据竞争。
- 新字段必须说明默认值、空值、旧数据回填与旧版本兼容性；大表索引或回填必须评估锁表、耗时与分批方案。
- 数据库变更**必须**验证新库初始化、旧库升级、重复启动及失败恢复；不能用 SQLite 或纯 mock 通过替代 PostgreSQL 特有 SQL 的集成验证。

## 7. 计费、配额与支付不变量

同步网关按对应服务的 `RecordUsage` 与统一结算链路记录用量；不要假定所有请求都有预扣费。批量图片等冻结余额路径有独立生命周期。

- 计费变更**必须**核对 `billing_service.go`、`gateway_usage_billing.go`、`openai_gateway_usage.go`、`usage_billing.go` 与 `repository/usage_billing_repo.go` 中受影响的调用链。
- 正常扣费**必须**复用 `UsageBillingCommand` 和 `UsageBillingRepository.Apply` 的幂等结算，保持 `(request_id, api_key_id)` 去重、请求指纹冲突检测及归档去重语义；**禁止**在 handler 中直接改余额或重复累计配额。
- 余额、订阅、Key 与账户的计费效果必须保持既有事务一致性；缓存只用于加速，不能替代持久化幂等凭据。结算成功/失败后的缓存更新和失效不得遗漏。
- 金额**必须**复用 `QuantizeUsageBillingAmount` 与 `UsageBillingMonetaryScale = 8`，对齐 `NUMERIC(20,8)`。**必须**保持 `Normalize()` 先按原始金额生成指纹、再量化金额的顺序，避免升级后重试出现指纹冲突。
- token 数、张数、分辨率、时长和倍率必须有合理边界；新增收费输入必须拒绝非法负数、NaN、Infinity 与溢出。量化函数不是输入校验器，不得把余额不足、缺失定价等错误静默解释为免费成功。
- 流式断开或部分上游执行的计费必须依据实际 usage 和既有业务契约，不能一律按 HTTP 失败免单。既有透支记录与控制语义不得被简单的“余额永不为负”规则替代。
- 冻结/预留余额的任务**必须**验证预留、实际结算、余款释放、取消、失败与重启恢复，确保不重复扣款、不永久冻结；修改时另读 `BATCH_IMAGE_MVP.md`。
- 支付回调**必须**验证签名、订单归属、提供方、金额与币种，经现有支付状态机和履约逻辑处理；重复或乱序通知不得重复充值/发放订阅。前端支付成功页不能作为入账依据。
- `simple` 模式与标准模式**必须**分别验证；不能给仅记录 Key 限流窗口用量的路径引入余额、订阅或其他配额扣减。

### 7.1 支付方式、履约与外部充值集成

依据 [PAYMENT_CN.md](PAYMENT_CN.md)、[PAYMENT.md](PAYMENT.md) 和 [ADMIN_PAYMENT_INTEGRATION_API.md](ADMIN_PAYMENT_INTEGRATION_API.md)：

- 用户可见的支付宝/微信按钮各自只能选择一个支付来源，未选来源时不应暴露该方式；后端可存在多个实例。实例选择必须保留金额范围、每日限额、启停和支付方式限制，超限实例不得参与分流。
- **必须**区分 `PAID`（上游已支付）与 `COMPLETED`（充值/订阅已履约）。支付成功而履约失败必须可恢复，不能要求用户重新付款；超时处理要查询上游状态，覆盖回调延迟、补单和取消/过期后到达的有效支付。
- 移动端/桌面端、微信内/外的支付结果类型必须正确处理；支付宝当面付唤起需有动态二维码回退，改变优先级时要验证其与强制二维码开关的组合。支付页面 URL、商户凭据与回调实例必须保持匹配。
- 服务间外部充值应该使用受控 Admin API Key，经 `/api/v1/admin/redeem-codes/create-and-redeem` 一步创建并兑换；必须保留“创建成功、兑换前中断”的恢复路径，不能误认为两步天然处于同一数据库事务。同订单复用稳定兑换码，同码同用户不得重复到账，同码不同用户必须冲突。人工余额修正使用既有 `set/add/subtract` 接口并记录原因，不能以直改数据库替代。
- 外部写入调用方**必须**发送 `Idempotency-Key`，测试必须区分强制校验与 `ObserveOnly`：观察模式允许缺键，不能据指南宣称所有部署缺键必返 400。普通网络重试保持相同键及载荷；确认一次执行失败后需按集成协议重新执行时，可用新键但必须保留同一业务兑换码，禁止通过换键/换码造成重复入账。
- 外部支付成功与内部充值成功要分别持久化。迁移到内置支付时必须验证新回调和新订单履约，并保留历史订单查询安排，不得宣称历史数据会自动迁移。

## 8. 鉴权、授权与响应契约

- 路由**必须**使用现有 `backend/internal/server/middleware/` 的 JWT、管理员、API Key、审计和必要的二次认证机制；不得用前端隐藏按钮代替后端授权。
- 用户资源读取、修改、导出、任务轮询和批量操作**必须**检查所有权与授权范围，不能仅凭可猜测 ID 访问。管理 UI 标识头不能充当管理员身份凭据。
- 会话、刷新令牌、OAuth、API Key 各有用途，**禁止**跨路径混用。修改登录/刷新时必须覆盖过期、撤销、并发刷新、失败清理与重定向校验。
- 管理/用户 API **必须**使用 `backend/internal/pkg/response/`：成功 `code: 0`，响应为 `{code, message, data}`，可带 `reason`、`metadata`；保留正确 HTTP 状态码，不能统一改为 HTTP 200。
- 网关**必须**使用当前端点所属协议的成功与错误格式，不能套管理端 envelope；Google、Anthropic、OpenAI 路径的错误结构和流式写出方式须分别验证。
- 业务错误**应该**经 `internal/pkg/errors/` 和既有错误映射传递。对外错误不得暴露 SQL、内部堆栈、凭据或完整上游响应。

### 8.1 管理控制台合规确认契约

依据 `docs/legal/admin-compliance.zh.md` / `.en.md` 和 `backend/internal/service/admin_compliance.go`，这是现有产品确认流程的开发约束：

- 法律文档被 `LegalDocumentView.vue`、`AdminComplianceDialog.vue` 以 `?raw` 导入，**属于前端运行内容**；修改它们不能仅按“纯文档免构建”处理。
- 修改承诺内容或确认语义时**必须**同步中英文文本、版本、文档链接、确认短语、前端 fallback 和测试；已有确认按管理员身份与版本区分，版本变更要验证重新确认，不能伪造或自动代替用户接受。
- **必须**保留管理路由的 `AdminComplianceGuard` 与确认端点的必要豁免，防止既绕过确认又使用户无法确认。HTTP 423 和 `ADMIN_COMPLIANCE_ACK_REQUIRED` 是专门契约，前端有对应事件处理；不得强行改成通用数值 `code` 或普通 401 刷新流程。
- 确认记录保留版本、时间、管理员标识及必要 IP/User-Agent，沿用权限和留存边界。品牌定制不得暗示第三方实例得到上游项目参与、授权或背书，也不能把此确认当作许可证、商业授权或运营资质的替代。

## 9. Go、JSON、并发与资源管理

- Go 代码**必须**经过 `gofmt`，遵守 `backend/.golangci.yml`，检查错误并使用 `errors.Is/As` 处理包装错误；禁止为通过检查随意新增全局忽略或 depguard 白名单。
- JSON **应该**沿用相邻实现的 `encoding/json`、gjson/sjson 等现有工具；本项目没有 maas `common.Marshal/Unmarshal` 的强制包装要求。
- 请求 DTO **必须**保留缺省、显式零值、空数组和 `null` 的协议语义；需要区分缺省与零值时使用指针或显式 presence 表示，不可仅靠 `omitempty` 丢弃有效输入。
- 跨协议转换前必须判断对象所有权，**禁止**原地修改被重试、其他 goroutine 或缓存共享的请求对象。
- 长耗时操作**必须**传播 context、设置合理超时；后台任务须有关闭、重试上限和错误可观测性。**禁止**无界 goroutine、无界队列、无界响应读取。
- 共享状态必须使用锁、原子或现有并发组件；修改限流、并发槽位、缓存或 worker 时应该增加针对性的竞态测试。

## 10. 配置、设置与缓存

- 启动配置经 `backend/internal/config/` 的 Viper 配置结构、默认值和校验管理；运行时设置经现有 `SettingService` 等业务入口维护。业务代码应该消费注入配置，避免散落读取环境变量。
- 新配置**必须**定义类型、默认值、有效范围、是否敏感、是否需要重启及失败行为；同步 `deploy/config.example.yaml`、`deploy/.env.example` 和实际使用的 Compose 映射。
- 密钥只允许进入既有秘密管理边界，不得进入公开设置、`window.__APP_CONFIG__`、Vite `VITE_*` 变量、前端源码或静态产物。
- 修改设置必须检查数据库持久化、缓存失效、多实例传播和公开字段过滤。品牌/公开配置变更还须检查开发态 Vite 注入与生产态 HTML 缓存刷新一致性。
- Redis key 必须隔离用途和业务身份，定义 TTL、失效策略与故障行为；不得把连接失败统一降级为允许请求，尤其是鉴权、限流、并发和支付幂等路径。

### 10.1 渠道监控默认值与渐进回填

依据 [channel-monitor-v2-safe-defaults.md](channel-monitor-v2-safe-defaults.md) 及当前 setting、runner、aggregator/repository 实现：

- 缺失或非法模式**必须**回退 `v1`，V2 为显式开启；升级不得强制把已有 V2 设置改回 V1。前端表单、公开设置与后端默认值必须一致。
- V1 定时探测与手工 `RunCheck` 都必须检查 `ActiveProbesAllowed()`，切到 V2 后停止主动探测；nil settings 的测试/异常路径保持不探测，不能与产品默认 V1 混淆。
- V2 **必须**保留单 leader、约 55 秒单轮预算和配置的刷新间隔，禁止恢复 5 秒 bootstrap 加速循环。首次种子覆盖约 2 小时，后续先刷新最近约 10 分钟，再每轮至多一个历史块；失败必须缩块并退避，进度需持久化以支持重启恢复。
- 自适应块初始 1 小时、最小 15 分钟，基础上限随深度为 2/4/6 小时；当前超过 7 天的历史会按天边界对齐，实际窗口可能超过基础上限。调整时必须同时验证日聚合与细粒度数据裁剪正确性、真实扫描范围及数据库负载，不能仅引用旧设计稿宣称所有查询均不超过 6 小时。
- 错误去重的 `request_id` 候选分支必须保留 `created_at >= $1 - INTERVAL '90 minutes' AND created_at < $2` 等时间边界，防止全历史扫描；UI 按已覆盖范围渐进展示，不把 30 天产品窗口尚未回填完误当成无数据。
- 历史 migration 195 的特定 checksum 兼容处理不是改写已应用迁移的通用先例；新调整继续遵守 §6，且不得强制重置已有设置。

## 11. 日志、审计与敏感信息

- 新增系统日志**应该**复用 `backend/internal/pkg/logger/` 及既有结构化日志接口，脱敏复用 `backend/internal/util/logredact/`；禁止用临时 `fmt.Println` 代替正式诊断。
- 普通日志、错误响应、测试快照与 PR **禁止**包含密码、API Key、OAuth/refresh token、Cookie、Authorization、支付秘密、完整 prompt/回复或 SSE payload。
- 请求正文审计若属于已配置的产品功能，**必须**走其独立权限、开关、存储和留存机制；不得复制到普通运维日志或绕过审计访问控制。
- 关键操作**应该**记录请求关联 ID、资源 ID、类型、状态、计数和耗时；不得为了排错直接转储完整请求、响应、环境变量或配置对象。
- 诊断与回归样例**必须**使用构造数据或脱敏数据，文档使用占位符，不复制现有指南中的本机密码和绝对路径作为通用部署默认值。

## 12. 插件、许可与品牌定制

- 插件协议以 `backend/pkg/pluginapi/` 为准；宿主继续拥有鉴权、凭据管理、账户调度、并发和计费。插件能力、握手和版本变化必须与宿主实现及文档同步。
- 插件转发**必须**遵守帧顺序、取消和资源回收契约，准确返回 `request_sent`；不能把已可能执行的请求标为未发送以触发重放。
- **禁止**为方便部署关闭默认签名/哈希校验或扩大插件 UI Bridge 权限；未签名包仅用于明确的本地开发配置。UI 消息必须校验来源、窗口和 Bridge Token。
- protobuf 及 SDK 生成源码不得手改，协议兼容变更必须同时验证旧插件协商与新能力行为。
- 当前根 `LICENSE` 为 **GNU LGPL v3**；**必须**保留许可证、已有版权与第三方归属声明，并核对 README 的相关声明。不得替换为参考项目的 AGPL/QuantumNous 声明。
- 产品名称、Logo 等定制**应该**优先使用现有公开设置和独立资源；不得借品牌调整抹去源码归属、冒充上游官方版本，或无必要地重命名 Go module 和整个源码树。

### 12.1 插件配置、打包与灰度契约

依据 [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)：

- `GetInfo` 必须与清单中的身份、版本和能力一致，`Health` 不做长网络探测。配置使用 `snake_case`，`ValidateConfig` 严格拒绝未知字段和非法值并返回规范化结果，`ApplyConfig` 成功才原子切换，失败保留旧配置/连接，宿主持久化失败要能恢复。
- UI Bridge 的配置测试针对已保存配置，每条消息必须有 `request_id`；页面卸载清理监听。插件 UI 不依赖 CDN/远程脚本，不读取、刷新或持久化宿主 OAuth token，不使用 Cookie/本地存储保管宿主会话。
- 维护 `manifest.source.json`，由打包器生成最终清单、目标运行时与文件哈希；`requires.sub2api` 是硬兼容范围，`tested_sub2api_versions` 只能填写实测版本。声明新 capability 不等于宿主已支持它，须同时完成公开协议与能力匹配。
- Ed25519 签名覆盖最终 `manifest.json` 精确字节，签名后不得重新格式化。私钥不得进入源码、插件包或部署服务器，`key_id` 必须匹配受信任公钥；追加的发布者不能覆盖内置公钥，轮换按先分发新公钥、再发新包、最后停用旧密钥执行。
- 安装后默认停用，诊断通过后按账号灰度启用；未命中灰度的 OAuth 账号与 API Key 账号继续原路径。发布必须覆盖实际目标平台运行时、路径安全、签名、取消、进程退出及升级/停用/回滚。

## 13. 前端架构与功能开发

- 页面沿用 `frontend/src/views/`，组件放 `components/`，复用逻辑放 `composables/`，状态放 `stores/`，接口放 `api/`，类型放 `types/`；已有 `features/` 模块继续按其边界维护，**禁止**照搬 maas 的 React 功能切片布局强制迁移全项目。
- Vue 组件**应该**采用项目现有 Composition API 与 `<script setup lang="ts">` 风格，复用公共表单、弹窗、表格和布局组件。
- 状态管理使用 Pinia；组件私有状态保持局部，派生值使用 computed，异步和响应式订阅应在卸载时清理，避免陈旧响应覆盖新状态。
- 面板 API **必须**通过 `frontend/src/api/client.ts` 的共享 `apiClient`，复用 URL、认证、语言、时区、错误解包与 `tokenRefresh.ts` 的刷新机制；不得在页面另建通用 axios 客户端或复制刷新逻辑。
- 流式请求、第三方 SDK 等确需独立传输时，必须明确其边界并复用适用的 URL/鉴权能力，不能向第三方发送面板凭据。
- 新页面**必须**同步 Vue Router、访问控制、导航和相关类型；API 字段变更必须同步后端 DTO 与前端调用方，不能靠 `any` 或类型断言掩盖不一致。
- 新功能必须覆盖适用的加载、成功、空、失败、无权限、不可用与提交中状态，错误后应能重试且不得重复提交支付等不可重复操作。
- 外部购买页/自定义页面的 iframe 与新窗口**必须**复用 `frontend/src/utils/embedded-url.ts`，同步用户、token、主题、语言及 `ui_mode` 参数；当前实现还传递 `src_host` / `src_url`。这是明确配置的嵌入集成边界，不得扩展为向任意外链传凭据；含 token 的完整 URL 不得进入日志、埋点或诊断，调整时须检查来源参数与重定向是否泄露会话信息。

## 14. 前端文案、样式与可访问性

- 用户可见文案**必须**通过 vue-i18n；新增/修改键同步 `frontend/src/i18n/locales/zh/` 与 `en/` 对应模块，运行 `pnpm --dir frontend run check:i18n`。本项目不是英文原文即键的 i18next JSON 结构。
- **必须**保持语言键、插值参数及复数表达一致，动态键须有明确候选范围与测试，不能在缺翻译时静默显示内部键名。
- 样式使用现有 Tailwind CSS 3 配置、`src/style.css`、`src/styles/` 与公共组件约定，保持明暗主题和移动端可用；不得移植参考项目的两套固定主题名称或 Tailwind v4 配置规则。
- 交互**必须**支持键盘操作、表单 label、可见焦点和弹窗焦点管理；错误和状态不能只依靠颜色。普通小字号文本对比度应达到 4.5:1，移动端主要点击区域应达到 44px。
- 外部 HTML/Markdown 展示必须复用净化逻辑，不能未经处理直接 `v-html`；外链、Logo URL、iframe 与 CSP 修改必须检查注入和来源限制。
- UI 变更**必须**进行实际页面检查，覆盖受影响主题、视口与关键状态；测试使用 Vue Test Utils + Vitest/jsdom，按行为风险补充，避免仅复刻实现的断言。

## 15. 格式、依赖与生成源码

- 前端统一 pnpm，提交 `frontend/pnpm-lock.yaml`；安装使用 `pnpm install --frozen-lockfile`，有意变更依赖时再更新锁文件。禁止混入 npm/yarn/Bun 锁文件。
- 前端 lint 为 ESLint：`lint:check` 只检查，`lint` 带 `--fix`；类型检查为 vue-tsc。当前没有 maas 的 oxlint/oxfmt、`copyright:check` 或 `i18n:sync` 命令，不得将其列为本项目 Gate。
- 格式沿用相邻文件，限制在改动范围内；不能为文档或小改动运行全仓自动修复。
- Ent 源定义位于 `backend/ent/schema/`，生成命令为 `cd backend && go generate ./ent`；Wire 使用 `cd backend && go generate ./cmd/server`。两者均需更新时可运行 `make -C backend generate`。
- 生成源码**必须**与源定义一起提交并复核 diff；禁止直接修改带 `Code generated … DO NOT EDIT` 的文件。`ent/schema/` 等手写源文件不属于禁改范围。
- protobuf 修改必须从 `.proto` 按项目协议工具链再生成，并记录生成命令和工具版本；不能用手工补丁伪装为生成结果。
- Go 依赖调整同步 `backend/go.mod` / `go.sum`；所有依赖升级必须说明用途、许可证、构建影响和相关验证，不能用关闭安全扫描解决告警。

## 16. 构建与本地运行

以下命令默认在 **sub2api 仓库根目录**执行，括号内命令只在子 shell 切换目录。

工具链以仓库配置为准：当前 Go 为 `backend/go.mod` 声明的 **1.27.0**，CI 同时硬校验该版本；前端 CI 使用 **Node.js 20、pnpm 9**，golangci-lint 为 **v2.13**。升级 Go 必须同步 CI 断言、Docker 构建镜像和发布配置；不得通过随意降低 `go.mod` 版本规避环境问题。

```bash
# 安装前端锁定依赖
pnpm --dir frontend install --frozen-lockfile

# 开发模式：分别在两个终端运行，预先配置隔离的 PostgreSQL/Redis
(cd backend && go run ./cmd/server)
pnpm --dir frontend dev

# 普通后端构建与前端构建
make -C backend build
make build-frontend

# 发布形态检查：先生成前端，再编译带嵌入资源的后端
make build-frontend
(cd backend && go build -tags embed -o bin/server ./cmd/server)
(cd backend && go test -tags embed ./internal/web)
```

前端 Vite 默认端口为 3000，开发代理默认指向 `http://localhost:8080`，可通过 `VITE_DEV_PORT`、`VITE_DEV_PROXY_TARGET` 调整。开发服务默认监听 `0.0.0.0`，需要仅本机访问时必须显式限制监听地址。

**构建语义必须区分**：`make build` 调用普通后端构建与前端构建，但后端 Makefile 默认不含 `-tags embed`；Vite 输出到 `backend/internal/web/dist/`。因此 `make build` 成功不能证明二进制已包含 UI。完整发布应使用带 embed 的既有 Docker/GoReleaser 流程和真实版本注入；上面的手工 embed 命令仅用于本地验证。

`go.mod` 位于 `backend/`，Go 命令必须在该模块执行。本项目没有 `relaykit` 独立模块，也没有由该模块导出的全局 `GOWORK=off` 要求；若本机存在外部 workspace，必须确认不会改变依赖解析。

## 17. 测试与 Gate

Gate 按变更范围选择，未受影响部分无需机械重跑。**禁止**把未运行、跳过或受环境阻塞的检查写成通过；失败必须说明原因、影响和后续验证，必需检查未完成前不能宣称可发布。

| 变更范围 | 必须完成的验证 |
| --- | --- |
| 任意代码/配置/脚本/资源/测试/生成文件改动 | **无条件执行架构索引 Gate**：`make check-architecture-index`（工作区）及提交前 `python3 tools/check_architecture_index.py --staged`；CI 对提交范围执行，不能代替下列业务 Gate |
| 仅文档（不进入运行产物） | 路径/链接/命令与实现核对，Markdown 结构检查，`git diff --check`；无需运行业务测试 |
| Go 业务代码 | 改动文件 gofmt、`make -C backend test-unit`、`make -C backend test`、`make -C backend build` |
| repository、迁移、Redis、事务/幂等 | Go Gate + `make -C backend test-integration`，真实 PostgreSQL/Redis 行为及迁移演练 |
| 网关、鉴权、计费、支付 | Go Gate + 受影响集成测试及下方业务矩阵；涉及 UI 时同时执行前端 Gate |
| 前端行为/类型/样式 | `make test-frontend`、受影响模块的 Vitest 测试、`make build-frontend`，UI 变化补实际页面验收 |
| 前端公共 API 客户端、路由、store、跨模块依赖 | 前端 Gate + `pnpm --dir frontend run test:run` 全套回归 |
| 嵌入资源/公开设置注入/静态路由 | 前后端相关 Gate + §16 的 embed 构建与 `internal/web` 测试 |
| 插件协议/生命周期 | 宿主相关测试、协议兼容、签名/哈希、取消与资源回收、实际进程及目标平台验证 |
| `docs/legal/` 或控制台确认流程 | 前端 Gate + 受影响的后端确认测试，双语展示、旧版本重新确认、按管理员隔离、423 事件及确认端点可达性 |
| 渠道监控模式、聚合与回填 | 默认 V1/保留既有 V2、主动探测停用、单 leader、分块/退避/重启进度与 PostgreSQL 去重时间边界；UI 变化加前端 Gate |
| 部署、CI、发布脚本 | 受影响脚本语法/现有脚本测试、对应构建或容器启动验证；不可仅检查 YAML 文本 |
| 上游同步 | 后端 unit/integration/lint/build、前端 Gate 与定制功能回归，涉及发布形态时补 embed/镜像验证 |

命令的真实覆盖范围：

```bash
make -C backend test-unit        # go test -tags=unit ./...
make -C backend test-integration # go test -tags=integration ./...
make -C backend test             # go test ./... + golangci-lint run ./...
make test-frontend              # lint:check + typecheck + 根 Makefile 指定的 critical Vitest
pnpm --dir frontend run test:run # 全套 Vitest，一次性运行
```

普通 `go test ./...` **不会**覆盖所有带 `unit` / `integration` 标签的测试；`make test-frontend` **不是**全套前端测试；`pnpm test` 为 Vitest 交互模式，不作为一次性验证命令。集成测试使用 testcontainers 等基础设施，必须准备可用的容器运行环境，不能通过跳过来伪造成功。

领域文档中的命令还须遵守以下边界：`BATCH_IMAGE_MVP.md` 的 Go 命令应在 `backend/` 执行，`go test … -run '^$'` 只是测试包编译检查，不代表运行测试或云端生图成功。插件进程测试可按以下方式调用（替换占位路径）：

```bash
(cd backend && SUB2API_TEST_PLUGIN_PACKAGE=/path/to/validated-plugin.s2plugin \
  go test ./internal/service -run '^TestPluginRuntimeIntegration$' -count=1)
```

`TestPluginRuntimeIntegration` 对签名、宿主版本、UI 文件和配置字段有固定 fixture 假设，必须提供与这些假设相符的实际包，不能把任意插件包视为通用测试输入；没有该环境变量时测试会跳过。示例脚本不存在、提供方余额不足或外部环境不可用时，只能报告实际完成的编译/单元/可调用验证，不能报告端到端成功。

按影响选择的业务验证矩阵：

- **鉴权**：无凭据、过期/撤销、禁用 Key、越权、跨用户资源、管理员权限、并发刷新。
- **调度**：分组/平台限制、原始模型白名单、映射、粘性会话、并发满载、限流、无可用账户、重试资源释放。
- **协议**：流式/非流式、工具调用、usage、异常终止、客户端取消、上游已执行后的重试边界。
- **计费**：重复请求、指纹冲突、并发扣费、8 位金额边界、订阅/余额/Key 配额一致性、缓存失效、simple 模式差异。
- **异步任务**：所有权、重复投递、领取与终态、超时/取消、重启恢复、冻结款释放和回收。
- **支付**：验签失败、金额/币种不符、重复/乱序通知、履约中断恢复、不重复入账。
- **迁移**：空库、旧数据、重复启动、事务失败、并发索引及旧版本兼容性。
- **Composite**：显式/内置决胜顺序、禁用与未知模型、预览一致性、具体平台配额/定价/报表，以及原始模型白名单不可绕过。
- **异步图片**：对象存储缺失时无任务写入、上传失败不存 base64、关闭后仍可轮询、同用户不同 Key 的 404、余额耗尽后的合法读取与 no-store。
- **Gemini 批量图片**：展开后输出/参考图/字节预算、队列重复领取与恢复、部分成功计费、重试耗尽释放、所有权、删除后 410 和存储引用不外泄。
- **Seedance**：能力默认关闭、原生字段透传、原账号和归属绑定、创建不重试、成功轮询按 token 只结算一次、删除不退款。
- **外部支付集成**：稳定兑换码重试、跨用户冲突、观察/强制幂等模式、支付与履约状态分离、内置订阅履约和嵌入 URL 参数。

测试**应该**靠近行为所有者，优先表驱动和可观察结果。新增高风险业务和修复缺陷必须有能证明契约的回归测试；低风险文案或纯样式调整无需机械添加实现镜像测试。**禁止**降低断言、删除失败用例或扩大跳过范围以取得绿色结果。

## 18. CI、PR 与发布

当前自动化能力以 `.github/workflows/` 为准：

- `backend-ci.yml`：`architecture-index` 文件级变更索引检查与门禁自身回归、部署脚本检查、后端 unit/integration、golangci-lint、`make test-frontend` 与发布辅助脚本测试。
- `security-scan.yml`：后端 govulncheck、前端 pnpm audit 及审计例外校验；gosec 已由后端 lint 配置启用，不应误写成独立扫描 job。
- `release.yml`：发布构建；具体触发条件、平台、镜像和版本注入须在发布前核对。
- `cla.yml` 与 `CLA.md`：向适用仓库贡献时按其实际要求执行。

本文 §17 的合入要求可能多于现有 CI；**禁止**把本文要求描述成已配置的自动化门禁，也不能因为 CI 未覆盖就省略本次变更必需的验证。本仓库没有参考项目的 anti-slop PR 自动关闭规则，不得宣称存在该检查。

PR **必须**说明问题与最终行为、影响模块、数据库/配置变化、兼容性、实际验证命令及结果、发布与回滚要点。提交应该使用 `feat:`、`fix:`、`refactor:`、`test:`、`docs:`、`build:`、`chore:` 等清晰类型。

PR **必须**给出架构指南 §11 的本次变更条目及受影响正文章节。维护者**必须**在托管平台将 `architecture-index` 配置为必需状态检查；仓库 workflow 不能自行开启远端分支保护，不能把已新增 CI job 误报为已配置远端保护。**禁止**用跳过 CI、机器人身份、直接推送或改检查脚本规避索引要求；自动版本同步也必须在同一提交更新指南并通过本地检查。

生产升级必须使用验证过的不可变版本，记录源码 SHA、上游基线、镜像 digest、迁移和配置状态。涉及迁移时必须先用脱敏数据库副本演练、备份并确认恢复方案；应用回滚不能替代数据库兼容性判断。

升级备份还必须覆盖实际配置、JWT/加密/支付秘密的安全副本、自定义资源、当前二进制或镜像与迁移状态，并验证备份可读。部署后验收健康、关键业务和全部定制功能，观察错误率、延迟、结算及渠道状态稳定后再清理旧版本；禁止直接在生产服务器修改源码作为发布流程。

## 19. 文档同步

### 19.1 架构总览与代码索引：无条件强制要求

**任何对本项目代码的新增、修改、删除、重命名，必须在同一提交/同一可评审变更中更新 `docs/ARCHITECTURE_AND_MODIFICATION_GUIDE.md`。未同步索引的代码变更不得标记完成、提交评审、合入或发布。此项是合入阻断规则，不是建议。**

1. **适用范围无规模豁免**：包括后端、前端、SQL 迁移、配置/默认值、部署/CI/工具脚本、依赖与锁文件、测试/fixture、插件协议、生成源码、运行资源、版本文件；bug fix、格式化、重构、删除、回滚、hotfix、上游合并、机器人更新也适用。“没有架构变化”不构成免更新理由。
2. **现行正文与历史索引分别维护**：行为、接口、依赖、数据流、目录、构建/测试命令或文档入口变化时，必须修订指南对应正文。即使架构不变，仍必须在 §11 新增记录，说明改动原因、最终行为及不改变哪些相关契约的依据。
3. **索引必须可定位**：每条记录包含日期/标识、原因与行为、完整仓库相对代码路径、关联章节/领域文档、实际验证与限制。路径写在反引号内，逐文件列出；重命名列旧/新路径，删除列旧路径并说明替代或移除。生成文件也不可只写目录或通配符。
4. **必须保持真实**：禁止仅改日期、空白、复制旧条目或补一句“已同步”敷衍；禁止把计划能力写为已实现、把未运行测试写成通过。历史索引不删除追溯关系，但不能让它替代失效正文的修正。
5. **强制执行流程**：开工读取指南并定位代码 → 实施 → 修订正文与新增索引 → 运行 `make check-architecture-index` → 暂存后运行 `python3 tools/check_architecture_index.py --staged` → CI `architecture-index` 检查 → 评审人工核对内容。检查失败必须补齐真实文档，不得缩减检查范围绕过。
6. **自动检查边界**：`tools/check_architecture_index.py` 对指定基线与目标快照的变更取文件级集合，只接受指南索引区的本次新增行；已有目录地图/历史记录不能满足新改动。工作区模式包含未跟踪且未忽略的文件，暂存模式只认可暂存指南，CI 检查提交快照。纯说明 Markdown 不触发代码门禁，但实际进入产品的 `docs/legal/` Markdown 不豁免；其他运行型 Markdown 若新增，必须同步扩展检查分类。
7. **评审责任**：机器通过不等于架构描述正确，评审必须逐项核对路径、实际调用关系、兼容性与验证证据。批量上游同步可以用一个条目组织多文件索引，但不能只写“同步上游”。

### 19.2 领域文档同步

以下变更在满足 §19.1 的总览索引要求之外，**还必须**在同一变更中同步相关文档：

| 变更 | 对应文档 |
| --- | --- |
| 任意代码改动 | `docs/ARCHITECTURE_AND_MODIFICATION_GUIDE.md` 的 §11；涉及架构/行为时同时修订相关正文，不能用领域文档替代 |
| 规范、Gate、生成或构建命令 | 本文、`DEV_GUIDE.md` 中受影响部分 |
| 分支、定制边界、上游合并和发布流程 | `docs/SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md` |
| 迁移机制与持久化约定 | `backend/migrations/README.md`、本文 §6 |
| 分组、路由与协议 | `docs/COMPOSITE_GROUPS.md` 或对应协议文档 |
| Seedance 原生字段、账号能力、任务归属与计费 | `docs/seedance-api.md`、本文 §5.4 |
| 图片任务、计费生命周期 | `docs/ASYNC_IMAGE_TASKS.md`、`docs/BATCH_IMAGE_MVP.md` 中受影响部分 |
| 支付、订单或管理 API | `docs/PAYMENT*.md`、`docs/ADMIN_PAYMENT_INTEGRATION_API.md` 中受影响部分 |
| 插件契约、包格式与 UI Bridge | `docs/PLUGIN_DEVELOPMENT.md`、`backend/pkg/pluginapi/` 对应说明 |
| 渠道监控默认值、探测、回填或错误去重 | `docs/channel-monitor-v2-safe-defaults.md`、本文 §10.1；同步说明历史设计与现行差异 |
| 合规正文、确认版本/短语/记录、品牌归属 | `docs/legal/admin-compliance.zh.md` / `.en.md`、相关前后端实现及本文 §8.1 |
| 外部充值幂等与嵌入页面参数 | `docs/ADMIN_PAYMENT_INTEGRATION_API.md`、共享 URL helper 与对应测试 |
| 环境变量、默认值、部署/安全行为 | `deploy/config.example.yaml`、`deploy/.env.example`、相关部署文档 |
| 新增用户能力、操作入口或兼容性 | 相关 README、功能文档与必要的人工验收步骤 |

新增、重命名或删除专门文档**必须**同步架构指南 §1 或对应领域章节的入口；涉及规范时同步本文 §1。本仓库 `.gitignore` 默认允许提交 `docs/`、脚本、测试与开发规范，仅忽略构建产物、缓存、本地配置和明确的本地工作目录；本地专用文档放入 `docs-local/`。需要随代码维护的新文档**必须**确认 Git 可见，不能误以为文件落盘就已纳入版本管理。可以说明无需更新其他领域文档，但**不得**据此免除任何代码改动的架构指南索引。

文档必须区分已实现、计划、测试通过、未验证和已知限制；不得包含真实秘密、本机专属路径作为通用前提、已失效命令或无实现依据的能力承诺。发现历史文档矛盾时，至少在当前规范中指出实际边界，涉及该流程的后续变更必须同步纠正源文档。

## 20. 评审阻断项

评审先检查正确性、兼容性与数据安全，再检查风格。以下问题**一律阻断合入**：

- 任意代码变更遗漏架构指南 §11 的文件级索引、未修正失真的架构正文、仅改日期/空白敷衍，或绕过 `architecture-index` 检查。
- 绕过 API Key/JWT/管理员授权、资源归属、模型白名单或分组准入。
- 重复扣费/充值、绕过幂等结算、金额量化不一致、冻结款无法释放或事务部分成功。
- 流式输出后盲目重放、账户串用、并发槽位/响应体泄漏或无界后台工作。
- 修改已应用迁移、手改生成源码、Ent/schema/SQL 不一致。
- 破坏分层并以新增 lint 忽略或白名单掩盖。
- 将管理 API envelope 与网关协议混用，破坏已有客户端字段或零值语义。
- 密钥、用户正文、支付秘密进入日志、前端产物或提交。
- 跳过测试、伪造验证结果、降低安全校验或忽略锁文件不同步。
- 在共享主分支改写历史、整目录覆盖定制代码、无迁移恢复方案直接发布。
- 混用三类媒体任务的存储/归属/计费契约，批量任务泄露提供方引用，或 Seedance 创建重放、轮询重复收费。
- 渠道监控升级擅自切换既有模式、恢复高频无界回填，或去掉错误去重的时间边界。
- 更改运行时法律文档却遗漏版本/双语/确认处理，或伪造用户确认记录。

## 21. 变更完成检查清单

- [ ] 已先阅读真实代码、本文、架构指南及相关领域文档，明确所有者、定制边界与兼容影响。
- [ ] 已保留用户已有改动，使用合适分支，变更不含无关重构、秘密或构建产物。
- [ ] 分层、Wire 装配、接口实现与 stub/mock 一致；生成源码来自源定义。
- [ ] 网关改动保留鉴权、模型准入、平台/分组、调度、流式、取消和计费契约（如涉及）。
- [ ] 计费/支付幂等、8 位量化、事务、缓存失效与冻结款生命周期已验证（如涉及）。
- [ ] Composite 的具体平台归属，以及异步图片、Gemini 批量图片、Seedance 各自的能力、存储、归属与结算规则已分别验证（如涉及）。
- [ ] 外部充值区分业务兑换码与请求幂等键，支付与履约状态分离，嵌入 URL 无诊断泄密（如涉及）。
- [ ] 渠道监控的模式、探测停用、回填负载与恢复，以及插件配置/签名/灰度契约未被破坏（如涉及）。
- [ ] 法律文档若改变，双语、版本与确认流程同步，已按运行内容完成验证（如涉及）。
- [ ] 数据库迁移为新增前向文件，完成升级/恢复验证，未改写历史迁移（如涉及）。
- [ ] 前后端 DTO、API 响应、错误和权限一致；文案中英文齐全（如涉及）。
- [ ] UI 关键状态、明暗主题、移动端与键盘操作已检查（如涉及）。
- [ ] §17 所需测试、lint 与构建通过；未执行或环境阻塞项已如实记录，未宣称完成发布验证。
- [ ] 完整发布形态已验证前端嵌入与版本来源，未把普通 `make build` 当成 embed 构建（如涉及）。
- [ ] **所有代码变更均已在架构指南 §11 留下本次文件级索引**，影响架构/行为的正文已修正；没有以“架构未变”豁免。
- [ ] 工作区/暂存区及 CI 的架构索引 Gate 已按阶段执行，评审已核对说明与实际代码；领域文档同步或无需修改的理由已记录。
- [ ] `git diff --check` 通过，`git status --short`、diff 和暂存区只含预期变更。

完成说明必须简要列出改动、原因、验证结果以及仍存在的限制；不能只给出“已完成”而遗漏关键验证状态。
