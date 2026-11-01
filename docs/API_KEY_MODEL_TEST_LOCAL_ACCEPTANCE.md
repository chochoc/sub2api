# API Key 模型测试：本地部署与验收记录

> **当前部署（2026-11-01）**：已从干净的 `main` 提交 `0f2b04c2cd3b3549ed6467ff0783c736edc2a28d` 重新构建并部署 `0.2.19-custom.2-main-local`，模型测试开关开启，服务继续在本机运行。新增验收与备份记录见 §7；§1–§6 保留为 2026-10-31 的历史记录，不能作为当前产物摘要。

> 日期：2026-10-31（Asia/Shanghai）。状态：当前源码已在本机运行，功能开关已开启，本地端到端验收通过。供应商响应为本地 fixture，未进行真实供应商付费调用或生产部署。
>
> 对应方案：[API_KEY_MODEL_TEST_TECHNICAL_PLAN.md](API_KEY_MODEL_TEST_TECHNICAL_PLAN.md)。部署方法沿用 [LOCAL_SOURCE_HTTPS_DEPLOYMENT.md](LOCAL_SOURCE_HTTPS_DEPLOYMENT.md)。

## 1. 当前访问方式

| 项目 | 地址 / 位置 |
| --- | --- |
| HTTPS 密钥页 | `https://127.0.0.1:8443/keys` |
| 回环 HTTP 密钥页 | `http://127.0.0.1:18080/keys` |
| 管理员邮箱 | `admin@local.invalid` |
| 管理员密码 | `.dev/local-https/credentials.json` 的 `admin_password`，不在文档或终端输出 |
| 自定义 CA | `.dev/local-https/ca/rootCA.pem` |
| 私有验收材料 | `.dev/local-https/key-model-test/`，Git 忽略 |

服务保持运行。两个 Web 地址均仅监听本机，未开放局域网或公网。HTTPS 继续使用专用本地 CA，未修改系统信任；未信任该 CA 的浏览器会提示证书不受信任。回环 HTTP 入口可用于本机检查。

从仓库根操作：

```bash
node deploy/local-source-https.mjs status
node deploy/local-source-https.mjs start
node deploy/local-source-https.mjs stop
```

`start` 对已运行实例幂等；`stop` 保留数据。不要在运行期间原位覆盖二进制。后续重新构建须继续显式传入 `VITE_KEY_MODEL_TEST_ENABLED=true`，该变量不是运行时设置。

## 2. 部署产物与数据保护

| 项目 | 实际值 |
| --- | --- |
| 分支 | `feature/api-key-model-test` |
| 提交基线 | `7090857956d6d7ec6a97dfc19a06688f025f4caf` |
| 源码状态 | 包含本功能未提交变更；不是仅凭 HEAD 可复现的干净版本 |
| 版本 | `0.2.19-custom.1-key-model-test-local-dirty` |
| 前端开关 | `VITE_KEY_MODEL_TEST_ENABLED=true` |
| 后端构建 | Go 1.27.3、CGO_ENABLED=0、embed、trimpath；注入 Version/Commit/Date/BuildType=source |
| 前端工具链 | Node v24.19.0、pnpm 9.15.9；Node 20 CI 仍需单独执行 |
| 二进制 | `.dev/local-https/bin/sub2api` |
| 二进制 SHA-256 | `4166cf223979628d0e47da8f5e6fe002bf5a661697669ce1bae6829a9bcab8b4` |
| 升级前备份 | `.dev/local-https/backups/key-model-test-20261031T133438Z/` |
| 数据库迁移记录 | 运行后查询到 299 条；不代表生产迁移演练完成 |

开始前确认本实例已经停止，复制了 PostgreSQL、Redis、应用数据/配置、凭据和旧二进制到私有备份。重新构建使用 `.next` 文件；编译成功后停止本实例，替换二进制并启动。没有清空原数据库，没有修改已有真实上游账号或管理员声明。

当前 PostgreSQL、Redis、应用、Caddy 分别监听 `127.0.0.1:15432/16379/18080/8443`。源码差异快照、逐文件摘要、浏览器测试和报告保存在私有验收目录；不提交凭据、数据库、日志或截图中的用户数据。

## 3. 部署测试发现并修复的问题

### 3.1 正常使用被误判为配置变更

现有 `api_key_repo.go::UpdateLastUsed` 会同时更新 Key 的 `last_used_at` 与 `updated_at`，结算也可能更新该时间。此前前端把 Key 的 `updated_at` 当作配置版本，发现模型后或重测时可能中止计划并清空结果。

修复集中在 `frontend/src/features/key-model-test/useKeyModelTest.ts`：比较 Key 身份、名称、分组、状态、有效期、IP 规则、配额和速率限制配置；排除使用时间、用量及其窗口进度。分组的配置版本仍比较 `group.updated_at`。每次启动仍读取当前 Key，每个网关请求仍执行真实后端授权。

新增回归覆盖：使用时间和累计用量变化不阻止测试，IP 白名单/黑名单、配额及速率限制变化仍要求重新发现。

### 3.2 Responses 转换链路附加结束标记

本地网关的 Chat → Responses SSE 转换在 `response.completed` 后附加 `data: [DONE]`。此前解析器将该标记作为 JSON 解析，导致有正常输出的请求显示失败。

修复集中在 `frontend/src/features/key-model-test/protocols/responses.ts`：允许该可选标记，但不以它替代正常终态和有效文本。新增回归覆盖 completed + DONE 成功、只有 delta + DONE 不完整、incomplete + DONE 仍不完整。没有修改后端转换或结算。

## 4. 本地端到端验收

链路为：实际 Chrome `/keys` 页面 → 已嵌入前端 → 本地 HTTPS Caddy → 真实 Sub2API Key 鉴权/调度/转换/计量 → `127.0.0.1:18181` 模拟上游。

使用专用普通用户、3 个独占测试分组、3 个合成凭据账号和 3 个业务 Key。另建零余额用户验证拒绝路径。没有把生产凭据发送给 fixture，没有使用已有真实上游账号。测试图片为固定静态 PNG，不生成真实图片。

| 测试方式 | 非流式 | 流式 | 图片预览 |
| --- | --- | --- | --- |
| Responses | 通过 | 通过，含网关转换后的 DONE | 不适用 |
| Chat Completions | 通过 | 通过 | 不适用 |
| Messages | 通过 | 通过 | 不适用 |
| Gemini 文本 | 通过 | 通过，真实 `/v1beta` 代理可达 | 不适用 |
| Images | 通过 | 首版禁用 | 浏览器解码成功 |
| Gemini 图片 | 通过 | 首版禁用 | 浏览器解码成功 |

最终一轮共 10 个协议/模式场景全部成功，浏览器 `pageerror` 为 0。

| 其他场景 | 实际结果 |
| --- | --- |
| 模型发现 | 三个 Key 各返回其分组目录，没有静态前端兜底 |
| 打开弹窗 | 没有生成请求 |
| 批量取消确认 | 没有生成请求 |
| 批量包含图片 | 确认后发出 2 个请求，浏览器观察到最大并发为 1 |
| 越权读取 Key | 404 |
| 无效 / 禁用 Key | 401 |
| IP 黑名单 | 经 HTTPS 代理访问返回 403 |
| 零余额用户 | `/v1/models` 返回 403 / INSUFFICIENT_BALANCE |
| 本地用量归属 | 共 23 条测试用量记录，均属于专用用户及其 3 个 Key |
| 本地账务 | 模拟 usage 进入现有计量/结算链路，未新建测试结算路径；不是供应商账单核对 |
| UI | 实际嵌入版明暗主题、390px 窄屏无文档横向溢出、Escape 关闭通过 |
| TLS / 登录 / 资源 | 自定义 CA 严格验证的 HTTPS smoke 通过；管理员登录、JS/SVG、无 Key 拒绝正常 |

浏览器使用仅针对本地服务器公钥的 SPKI 配置；没有启用全局忽略证书错误或安装系统 CA。首次前端 fixture 测试中的停止、迟到结果、429 停队等覆盖仍有效；本轮部署测试没有把这些全部重做成真实供应商场景。

测试结束已通过正常 API 删除专用 Key、账号、分组和用户，删除测试会话凭据，停止模拟上游。清理失败数为 0。软删除和测试用量/审计记录按现有后端策略保留；本地真实服务继续运行。

## 5. 修复后的自动化与构建检查

| 检查 | 结果 |
| --- | --- |
| `make test-frontend` | lint、typecheck、578 项 critical 测试通过 |
| 模块与 KeysView 定向测试 | 9 文件 / 113 项通过 |
| 全量前端测试 | 383 文件 / 3,098 项通过 |
| 开启功能构建 | 通过，已部署此次产物 |
| 关闭功能构建 | 首轮实现已通过；本轮未改开关逻辑，沿用该结果 |
| embed build / web tests | 通过 |
| 部署后 smoke 与进程检查 | 通过，四组件运行且只监听回环地址 |
| 架构索引与 diff | 工作区及暂存区 Gate、差异格式检查通过 |

构建保留既有大型 chunk / Browserslist 提示，未修改依赖或降低检查标准。

## 6. 限制与后续发布条件

本次完成的是本地已部署服务的验收。真实供应商可用性、真实收费、生产 IP/代理规则、Composite 真实账号及生产升级/恢复演练仍未完成；本机模拟图片成功不等于供应商生图成功。

本地验收结束时尚未提交、推送、合并同步分支或发布生产；后续 Git 提交与评审状态以仓库记录为准。原有 `docs/REF_AUTH_TECHNICAL_PLAN.md` 保持不变。后续同步分支已通过 PR #2 合入，并升级前端安全依赖；该后续源码变更未替换本文记录的本地二进制。上线仍需完成生产基线/数据库核对及真实专用 Key 验收。

## 7. 合入 main 后重新部署（2026-11-01）

### 7.1 实际产物与访问

| 项目 | 本次实际值 |
| --- | --- |
| 源码 | 干净的 `main`，`0f2b04c2cd3b3549ed6467ff0783c736edc2a28d`；包含 PR #2、#3、#4 |
| 版本 | `0.2.19-custom.2-main-local` |
| 构建时间（UTC） | `2026-11-01T00:43:06Z` |
| 二进制 SHA-256 | `ddb93507fbcff24a3eb17c6a432e1b75ebed79b4eb3b2c336ceeeea70c2871b1` |
| 构建 | Go 1.27.3、CGO_ENABLED=0、embed、trimpath；注入版本、完整提交、时间及 BuildType=source |
| 前端 | Node v24.19.0、pnpm 9.15.9，锁定安装；`VITE_KEY_MODEL_TEST_ENABLED=true` |
| 入口 | `http://127.0.0.1:18080/keys`、`https://127.0.0.1:8443/keys` |
| 凭据 | 邮箱 `admin@local.invalid`；密码仍在 `.dev/local-https/credentials.json` 的 `admin_password`，未输出或提交 |
| 私有证据 | `.dev/local-https/main-deploy-20261101/`，含部署清单、构建/测试日志和浏览器结果 |

本机父目录声明其他包管理器，且系统 Corepack 存在签名缓存问题；本次直接使用既有 pnpm 9.15.9，仅对子命令设置 `COREPACK_ENABLE_STRICT=0` 避开父目录的包管理器声明，仍使用 `--frozen-lockfile`，未更改全局配置或关闭下载校验。没有把 Node 24 的本地验证写成 Node 20 验证。

### 7.2 备份与替换

升级前生成 `pg_dump -Fc` 并通过 `pg_restore --list` 核对可读取。停止本实例后，备份完整 PostgreSQL、Redis 持久化目录、应用数据、配置、凭据、证书及旧程序至 `.dev/local-https/backups/main-20261101T004321Z/`；未修改系统 CA 信任，未清空数据库或接管其他实例。

新程序先构建为 `.dev/local-https/bin/sub2api.next`。首次替换因构建清单覆盖备份路径字段而中止，旧实例恢复运行；修正私有记录后再次停止、完成冷备份并替换。最终通过程序版本输出及 `/api/v1/settings/public` 确认为新版本，没有将旧程序的健康检查算作新版本验证。备份目录权限 700、秘密文件 600，备份可读取不代表已完成隔离恢复演练。

当前源码相对旧部署基线没有新增数据库 migration；运行后仍为 299 条迁移记录。源码中的后续文档记录不改变本节已构建程序的提交来源。四组件继续仅监听回环地址，停止/启动仍使用 §1 的管理脚本。

### 7.3 本次真实验证

| 检查 | 结果 |
| --- | --- |
| 锁定安装、lint、类型、critical Vitest | 通过，30 文件 / 578 项测试 |
| 模型测试模块与 KeysView 定向 Vitest | 通过，9 文件 / 113 项测试 |
| 开启功能的前端构建 | 通过；保留既有大 chunk 提示 |
| embed 构建与 `go test -tags embed ./internal/web` | 通过 |
| HTTPS smoke、资源、管理员登录、无 Key 401 | 替换后及清理后均通过；使用专用 CA 严格校验证书 |
| 本地管理 API 诊断 | 替换前后通过；通过 `sub2api-admin` 的只读 API 命令获取本地 dashboard snapshot，未访问生产实例 |
| 浏览器普通用户实际登录及 `/keys` | 通过；3 个专用 Key 的测试入口可见 |
| 六种协议 / 模式 | 10 项全部成功：Responses、Chat、Messages、Gemini 文本各含流式与非流式，Images、Gemini 图片各一次；两种图片预览均可解码 |
| 串行批量 | 开窗与取消确认均不发生成请求；确认后 2 次生成，最大活动请求数为 1 |
| 权限和限制 | 跨用户读取 404；无效/禁用 Key 401；HTTPS 代理下 IP 黑名单 403；零余额模型发现 403 / INSUFFICIENT_BALANCE |
| 界面 | 明暗主题、390px 窄屏无文档横向溢出、Escape 关闭通过；浏览器 pageerror 为 0 |
| 用量归属 | 12 条测试用量均归属本次临时用户及 3 个 Key；模拟 usage 进入真实本地结算链路 |
| 清理与保留 | 临时 Key、账号、分组、用户均删除，清理失败 0；活动资源数量恢复到测试前，临时会话文件删除，模拟上游停止；原有本地数据和真实服务保留 |

本轮通过真实嵌入 UI、本地 HTTPS、Sub2API 网关与本地模拟上游验证。未进行真实供应商付费调用、生产部署、生产迁移或备份恢复演练；模拟图片和本地账务记录不能证明真实供应商生图或账单一致性。本次没有业务源码变更，未机械重跑全套 Go 业务测试或全量 Vitest，不能将此前其他提交的检查当作本轮执行结果。
