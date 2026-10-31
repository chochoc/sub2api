# 2026-10-31 官方 v0.2.19 本地源码同步

## 来源与范围

- 官方发布：[v0.2.19](https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.19)，发布于 2026-10-28。
- 官方起点：v0.2.15，`3a6fd1c9db07203ca308aaba69e502bc1f35b307`。
- 官方终点：v0.2.19，`dece26153621959ccd7635814f4b2d08304e681a`；annotated tag 对象为 `e60cefeaf78f2fbfa95aa076029e28b40d0a5527`。
- Fork main：`a077b1d70989a9f5b07de52cd9c6cc6436c5b209`。保留当前功能分支 `feature/admin-skill-management` 的 `c92175f2b`，从更新后的 main 建立同步分支后先快进到该提交。
- 同步分支：`sync/upstream-20261031-v0.2.19`。使用普通 merge 保留双方历史，不引入发布标签之后的 upstream/main 开发提交。
- 源码版本标识：`0.2.19-custom.1`。官方 tag 内 VERSION 仍为 `0.2.18`，本 Fork 显式更新，避免合并提交构建成错误的旧版本号；没有创建发布 tag。
- 本次仅更新本地源码，不部署、不重启服务、不连接业务数据库执行迁移。

## 主要更新与兼容边界

引入 v0.2.16–v0.2.19 的完整变更，包括受限管理员 API Key、分组多语言、Gemini 显式上下文缓存、OpenAI/Composite 图片按张计费、GPT-6.1 Terra、Grok 模型目录诊断、缓存/计费/退款/协议与安全修复。

受限管理员密钥以 `adm_sc_` 开头，按动作和资源授权；未在官方权限目录登记的本地扩展路由默认拒绝。现有管理员 JWT、旧管理密钥与显式目标用户 API Key CRUD 保留。管理工具若使用新密钥，可显式指定 `--auth-mode api-key`；不得把新密钥当作 JWT。

自定义 Chat strict/text stop、max 参数、真实 usage 与有限收尾逻辑继续保留。strict 模式不对客户端的正数 max 应用官方最小 token floor；legacy 模式应用新的 `gateway.min_output_tokens`。`cached_tokens` 的显式零与字段缺失继续分别处理。

## 冲突与装配处理

| 文件 | 解决原则 |
| --- | --- |
| `.gitignore` | 保留 Fork 的文档/脚本/测试追踪规则。官方只新增 docs allowlist，Fork 已默认追踪 docs，无须引入整份官方忽略规则。 |
| `Dockerfile`、`backend/go.mod` | 接入官方 Go 1.27.3，并将 `backend/Dockerfile`、`deploy/Dockerfile` 对齐；不延续与官方依赖/CI 不一致的旧 1.26 镜像。 |
| `backend/internal/config/config.go`、`deploy/config.example.yaml` | 同时保留自定义 Chat contract 和官方 token floor/缓存/重试配置。 |
| `backend/internal/pkg/apicompat/chatcompletions_to_responses.go` | 统一 options 转换入口，保留官方 WithMinOutputTokens API 与自定义参数原值/工具选择处理。 |
| `backend/internal/service/gateway_forward_as_chat_completions.go`、`backend/internal/service/openai_gateway_chat_completions_anthropic_native.go` | 两条 Anthropic 桥保留 contract 校验，legacy 转换读取运行配置。 |
| `backend/internal/service/openai_gateway_chat_completions.go`、`backend/internal/service/openai_gateway_messages.go` | 合并官方账号/模型审计状态与自定义文本 observer；错误返回同时保留真实 usage 和 prior audit。 |
| `backend/internal/service/openai_gateway_chat_completions_raw.go` | 保留官方携带起始时间的 fallback 入口，在共用实现中执行自定义 contract 校验。 |
| `backend/internal/web/embed_test.go` | 保留 SVG 内容断言，未删减 Fork 的别名/缓存回归。 |

Wire 按 `backend/internal/handler/wire.go` 重新生成，修复已有管理 API Key handler 未注入 APIKeyService 的生成代码；保留新 Gemini 缓存服务接线。生成命令：`cd backend && GOPROXY=https://goproxy.cn,direct go run -mod=mod github.com/google/wire/cmd/wire ./cmd/server`，Wire v0.7.0；补齐生成器所需的 subcommands 校验和。Ent 文件来自官方合并，没有手工修改生成源码。

## 数据库、配置与依赖

新增七个 SQL 文件，保留已有历史迁移内容：

- `backend/migrations/242_group_i18n.sql`：分组 i18n JSONB。
- `backend/migrations/243_gemini_cached_contents.sql`：显式缓存归属/上游资源绑定与索引。
- `backend/migrations/244_gemini_cached_contents_channel_usage.sql`：缓存渠道计费快照。
- `backend/migrations/245_gemini_cached_contents_mutation_lease.sql`：缓存变更租约与待恢复索引。
- `backend/migrations/246_enable_gemini_image_generation_groups.sql`：将现有 Gemini/Antigravity 分组生图开关置为开启；部署前需评估这一数据更新。
- `backend/migrations/247_scoped_admin_api_keys.sql`：受限管理员密钥，仅存摘要、保留撤销记录。
- `backend/migrations/248_group_image_count_billing.sql`：图片按张计费开关，默认关闭。

迁移 runner 按完整文件名执行；已有 `242_remove_platform_enum_constraints.sql` 继续保留，与新 242 文件名称不同。源码合并没有执行这些迁移。

新增配置：`gateway.min_output_tokens` 默认 128、配置下限 16；`gateway.gemini_cached_content_max_ttl_seconds` 默认 86400；`gateway.max_same_account_retries_gemini` 默认 4、范围 0–10。Gemini 默认模型列表移除停用的 2.x；如仍使用，需自行声明映射/白名单。配置默认值和样例以代码为准。

依赖沿用官方锁文件：Go 1.27.3、golangci-lint v2.14.0、更新的 golang.org/x 安全补丁，以及 DOMPurify 3.4.17 / follow-redirects 修复。pnpm 使用隔离安装的 9.15.9，未关闭 Corepack 签名校验或修改全局包管理器。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| `make -C backend test-unit` | 通过，包含自定义 Chat strict/legacy floor、stop/usage 和官方新增回归。 |
| `make test-frontend` | lint、类型检查、critical Vitest 30 文件 / 576 测试通过。 |
| `pnpm --dir frontend run test:run` | 375 文件 / 3011 测试全部通过。 |
| `make build-frontend` | 通过；Vite 提示部分 chunk 超过 500 kB。 |
| 两份管理 skill 的 Python 测试 | 13 + 14 测试通过；Node CLI 语法检查通过。 |
| 架构索引门禁自身测试 | 11 测试通过；本次索引覆盖 590 个代码/配置/资源路径。 |
| `make -C backend test` | 普通测试通过；golangci-lint v2.14.0 为 0 issues。 |
| `make -C backend test-integration` | 命令退出 0；repository harness 因缺 Docker 跳过整个包，不计数据库/Redis 集成验收通过。用 `go test -tags integration -v ./internal/repository -run '^$'` 额外确认了明确的 skipping 日志。 |
| `make -C backend build` | 通过，普通二进制 `--version` 为 `0.2.19-custom.1`。 |
| embed 构建与 `go test -tags embed ./internal/web` | 均通过；嵌入二进制 `--version` 为 `0.2.19-custom.1`。本地验证产物不冒用旧 commit，commit/date 未注入。 |
| 文档与格式 | 本次 106 个本地链接、围栏、工作区/暂存区架构索引及 `git diff --check` 通过。 |

没有执行真实数据库迁移/恢复演练、容器启动、实际 UI 页面或真实上游业务验收，也没有推送分支或创建发布；不据上述本地结果宣称可生产发布。

锁定依赖安装已成功；网络超时通过单次 GOPROXY/registry 镜像参数重试，未修改锁文件、禁用 TLS 或关闭校验。架构索引的工作区/暂存区检查和 diff 格式检查均已执行；新增文档及当前构建说明已同步架构指南。

## 发布与回滚

本分支是本地源码合并结果。发布前仍须满足开发规范中的 CI、评审、真实数据库迁移演练和关键业务验收，并在 Fork 创建 PR 后合入 main。

生产部署前应备份 PostgreSQL、Redis、配置/密钥、旧产物，并用脱敏副本验证新迁移和旧应用兼容。回滚目标是升级前完整 Fork commit `c92175f2b`；仅撤回源码合并不等于撤回数据库变更。若旧应用无法读取迁移后的库，必须使用经过演练的数据恢复方案，不能盲目替换二进制或覆盖升级后的业务写入。

## 合入前安全门禁修复（2026-10-31）

GitHub 上同步基线和 API Key 模型测试分支的常规 CI 已通过，但 Security Scan 的 frontend-security 失败。使用与 CI 相同的 `pnpm audit --prod --audit-level=high --json` 及例外检查在本地复现，新增未豁免高危项为：

- Vue I18n / @intlify/core-base / @intlify/shared 9.14.5：GHSA-83rm-6c8r-g728，escapeParameter 对 srcdoc 的 XSS 防护不完整。
- decode-uri-component：GHSA-qr28-fpjm-wq7f，百分号编码输入触发二次复杂度拒绝服务。
- follow-redirects：GHSA-mrwp-f3q8-3g9p，跨 realm 的敏感头列表被忽略。

本次在同步分支追加修复提交，不重写原同步 merge，不跳过 CI：

- 将 Vue I18n 与测试使用的 @intlify/message-compiler 对齐为 11.4.16。9.x 没有更新的修复发行版；项目使用 `legacy:false` 的 Composition API，需通过类型、全量前端和文案编译检查验证升级。
- 将 follow-redirects override 的最低版本提高到 1.16.2，新增 decode-uri-component 最低版本 0.5.1。
- 重新生成 pnpm lockfile，没有新增漏洞豁免或延长过期日期。
- 更新 SubscriptionPlanCard 测试：旧断言依赖 9.x runtime-only 环境未翻译时的 key 回退；11.x 正常翻译后改为验证用户可见的 month/weeks/days 和购买按钮文案，保留原期限分支和布局检查。

审计例外检查已通过；余下 xlsx 两项高危使用仓库现有、截至 2027-01-06 的仅导出场景例外。此结果不是“依赖无漏洞”的承诺，低/中危及已有例外仍按原维护策略跟踪。

修复后 frozen-lockfile 离线安装、lint/typecheck、576 项 critical、3,011 项全量前端测试及构建通过；套餐卡片定向 9 项通过。追加修复将推送原同步分支，由 GitHub 重新执行完整 CI 和 Security Scan，远端结果以对应提交检查为准。同步 PR 仍须先合入 main，再由功能分支普通 merge 吸收更新后的 main，禁止 rebase 已推送且本地部署过的功能分支。生产迁移/恢复和真实供应商验收仍不因 CI 通过而自动视为完成。
