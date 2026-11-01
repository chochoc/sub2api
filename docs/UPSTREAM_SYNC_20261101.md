# 2026-11-01 官方 main 源码同步

> 状态：同步分支已合并源码并逐项解决冲突，验证执行中；实际结果见下方记录。源码更新与运行实例升级分开，本次不自动替换现有本地或生产服务。

## 1. 固定来源与范围

| 项目 | 来源 |
| --- | --- |
| Fork 起点及源码回滚目标 | `3763090fa908791d4f725291da742fa55942a61c` |
| 已合入官方起点 | v0.2.19，`dece26153621959ccd7635814f4b2d08304e681a` |
| 官方终点 | `d851a38477597157e78450d30af2d8504764d085`，2026-10-30 的 main；本次获取时最新正式 Release 仍是 v0.2.19 |
| 新官方提交 | 16 个（含 merge commit），不把 main 开发提交称为新的正式 Release |
| 同步分支 | `sync/upstream-20261101`，普通 merge 保留 Fork 与官方历史 |
| 定制源码版本 | `0.2.19-custom.4`；高于既有本地验证产物 custom.3，不覆盖为纯官方版本 |

先更新干净的 main，核对 origin 为 chochoc/sub2api、upstream 为 Wei-Shaw/sub2api 且 push URL 为 DISABLED，再获取官方 refs/tags 和 Release 信息。从最新 main 创建同步分支并合并完整固定终点，不通过挑选零散提交替代同步。

## 2. 变更与兼容边界

- 默认关闭的管理 MCP：无状态 Streamable HTTP、授权码/S256 PKCE、明确同意个人/管理员及只读/读写范围、短期访问凭据、刷新轮换/重放撤销和用户连接撤销。工具调用复用封闭目录中的原用户/管理路由、归属、step-up、审计及限流；不是任意 URL 代理。SDK 为 v1.4.1，包含 GO-2026-4770/4773 修复。
- MCP 仅在显式配置 `mcp.public_url` / `MCP_PUBLIC_URL` 后开放，默认空；不能仅因为升级就开启管理工具。详见 [MCP 文档](mcp.md)。本次不替操作者开启功能或授予权限。
- OAuth passthrough `/v1/responses` 保留客户端原始 stream 语义，非流式聚合上游 SSE 为 JSON；incomplete/cancelled 正确保留状态。OAuth 上游缺 Content-Type 时按 SSE framing 检查。Fork strict/legacy max、stop、cached_tokens presence 及原计费路径保留，验证不得只检查编译。
- CI/发布的 Node 20 跟随官方升为 Node 24；Go 仍 1.27.3，pnpm 9。保留 Fork 的架构索引、手动 workflow 入口和发布辅助流程。
- 既有 Key 模型测试及按需结果详情弹窗独立模块、双语注册、功能开关保持；与新增 MCP 页面/路由分别验证。

## 3. 冲突、装配与依赖

rerere 已启用，本次五个冲突均保留冲突 preimage，逐项核对后手动解决，没有未经审查套用既有结果或批量 ours/theirs。

| 冲突文件 | 决策 |
| --- | --- |
| `.gitignore` | 保留 Fork 默认追踪 docs/scripts/tests 的规则；官方新增 docs/mcp.md allowlist 在 Fork 无需另设白名单。 |
| `backend/cmd/server/VERSION` | 使用定制版本 0.2.19-custom.4，避免官方 VERSION 覆盖定制身份。 |
| `frontend/package.json` | 沿用双方已更新的 vue-i18n 11.4.16 与 decode-uri-component 0.5.1；保留 Fork 更高的 follow-redirects 1.16.2 安全下限。 |
| `frontend/pnpm-lock.yaml` | 保留与 package.json 一致的更高安全 override；通过 frozen-lockfile 验证，不降低或重新无界升级依赖。 |
| `frontend/src/components/payment/__tests__/SubscriptionPlanCard.spec.ts` | 双方断言已一致，仅注释冲突；保留 Fork 关于真实 i18n 和用户可见译文的说明，不删减断言。 |

`wire_gen.go` 自动合并后按 source provider 重新执行 Wire v0.7.0，确认 MCP repo/service/handler 装配并保留定制 APIKeyService 注入；不手改生成代码。Ent schema 没有新增，不需要重新生成 Ent。

Go 新增 MCP SDK、jsonschema、segmentio、URI template 和 oauth2 依赖，校验和随官方引入；保留原 Wire 校验和。前端 package/lock 实际保持 Fork 安全修复后的内容，不产生新的安全降级或例外。

## 4. 迁移、配置、升级及回滚

唯一新增 migration 为 `backend/migrations/249_mcp_oauth.sql`：创建 grants/codes/credentials 三表与普通索引，外键指向 users、授权关系级联；授权/码/凭证只保存摘要，scope/kind 受约束。未修改已应用历史 SQL；新建表默认无数据，不改已有余额、Key、账号或计费记录。动态客户端注册不写表，其签名密钥首次使用存入既有 security_secrets。

需要配置 MCP 时应使用可信 HTTPS、精确 `/api/v1/mcp` 路径；仅回环开发允许 HTTP，不支持站点子路径、userinfo、query 或 fragment。反向代理额外转发 MCP/OAuth 与 well-known 端点；分域部署还需正确前端地址及 Origin。默认空保持 503/入口隐藏。Compose 与示例新增相应空变量，不影响已有网关开关。

迁移验证使用隔离测试库/本地数据库副本，不在现有业务库上运行新程序。验证完整迁移 runner、重复启动、历史数据及旧版本兼容；实际执行结果与生产演练区分。生产部署前仍须核对线上基线、备份 PostgreSQL/Redis/配置/必要秘密/旧程序或镜像并验证可读，在脱敏生产副本演练迁移锁与恢复。没有生产数据或环境时不得宣称已完成生产演练。

源码回滚使用新增 revert 提交撤回同步，不能 reset/强推已共享 main。应用回滚到 Fork 起点的固定已验证程序；数据库若经兼容验证可保留新增表，MCP 保持关闭；若无法证明兼容或存在后续写入差异，应执行经演练的数据恢复。不能在已有业务写入后盲目覆盖旧备份。

本次不创建会自动发布镜像/二进制的 v* tag：仓库 release workflow 的 tag push 会发布产物，源码同步不等于生产发布。源码通过完整 commit/PR 追溯，正式发布需在已验证 main 上按手册单独创建发布版本并核对产物。

## 5. 验证记录

命令从仓库根执行；Go 测试/生成/构建串行，避免 Ent 动态加载的临时文件干扰。前端 Node v24.19.0、pnpm 9.15.9 使用既有隔离工具，单次 COREPACK_ENABLE_STRICT=0 仅避开父目录 yarn 声明，不修改全局配置、锁文件校验或 TLS。

| 验证 | 当前证据 |
| --- | --- |
| 冲突与差异复核 | 五项逐项解决，自动合并的 i18n/装配/配置与定制逻辑已核对 |
| Wire 生成 | 成功；结果与自动合并的装配一致 |
| frozen-lockfile 安装 | 离线成功，package/lock 保留既有安全下限 |
| 后端 unit / 普通测试与 lint / build | 执行中，结果后续按真实日志更新 |
| 前端 critical / 全量 / 构建 / 定制模块 | 执行中，结果后续按真实日志更新 |
| PostgreSQL/Redis 集成 | 本机无 Docker；由 GitHub Docker runner 执行，不以本机 skip 视为通过 |
| 迁移、副本与旧版本兼容 | 待执行隔离验证；生产未验证 |
| 架构与格式 | 提交前执行工作区/暂存区/完整范围 Gate 与 diff |
| GitHub PR、CI、安全扫描 | 推送后以实际运行记录为准，不绕过门禁 |

私有构建/测试材料位于 `.dev/upstream-sync-20261101/`，不提交数据库、凭据、日志或程序。原有本地部署仍为 `0.2.19-custom.3-result-dialog-local`（构建源码 3800e8c07），本次不将旧运行状态误报为新源码部署。
