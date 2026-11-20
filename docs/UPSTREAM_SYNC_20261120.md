# 2026-11-20 官方 main 本地源码同步

## 来源与范围

- 官方远端：`Wei-Shaw/sub2api`
- 官方当前主线：`328db26f450edbdf9f8d4344a3ea903ac6396842`
- 官方稳定标签：`v0.2.24`，标签提交为 `5c2982a81b46e2142d0143d2f83c1ce9c4da1d24`
- 本地同步前 `main`：`de7f252d56cd93911237b76e772fceccd9bc9934`
- 共同祖先：`d851a38477597157e78450d30af2d8504764d085`
- 同步分支：`sync/upstream-20261120`
- 本地合并提交：`9d1e2f524f5297bfa3aa30dd26e2494621d3e52d`
- 合并方式：`git merge --no-ff upstream/main`
- 本次只更新本地源码，不推送 Fork、不创建 PR、不创建发布 tag、不部署、不重启服务、不连接业务数据库执行 migration。

## 官方变更范围

本次从 2026-10-31 后的官方主线引入到 `v0.2.24` 及其后续版本标识提交，涉及网关安全、请求体重复字段拒绝、协议转换、OpenAI/Claude/Gemini/Grok 兼容、账号调度、计费、缓存、管理 API、模型广场、注册邮箱黑名单、前端管理界面和依赖更新。

主要数据库变更包括：

- `249_add_usage_logs_api_key_cost_index_notx.sql`
- `250_openai_cache_write_ttl.sql`
- `251_group_force_openai_ultrafast.sql`
- `251_group_usage_rollup_nonblocking_build.sql`
- `252_channel_pricing_ultrafast_multiplier.sql`

新增 migration 只随源码合入并完成静态审查，本次没有对任何业务数据库执行迁移。

## 冲突与解决

| 文件 | 解决原则 |
| --- | --- |
| `.gitignore` | 保留本地工具、测试工作区、插件目录和同步文档规则，同时接入官方构建产物、配置、运行数据和文档 allowlist。 |
| `DEV_GUIDE.md`、`backend/Dockerfile`、`deploy/Dockerfile` | 按官方 Go 1.27.4 对齐文档和构建镜像。 |
| `backend/cmd/server/VERSION` | 以官方 0.2.24 为基线，保留定制版本后缀，设置为 `0.2.24-custom.1`。 |
| `backend/internal/pkg/apicompat/chatcompletions_to_responses.go` | 保留本地 token floor、max 参数原值和 function choice 归一化选项，同时采用官方完整 GPT-6.1 reasoning 校验。 |
| `backend/internal/pkg/apicompat/types.go` | 同时保留显式 `cached_tokens: 0` 的 presence 语义和官方 `cache_write_tokens` presence/缓存输入 token 计算逻辑。 |
| `backend/internal/service/gateway_forward_as_chat_completions.go` | 保留自定义 Anthropic contract 校验，并将校验放在官方令牌轮换和实际发送循环中、每次发送前执行。 |
| `backend/internal/service/openai_gateway_chat_completions_anthropic_native.go` | 保留自定义 contract 转换和校验，同时接入官方实际上游 endpoint 记录。 |

合并后工作区没有未解决冲突，合并提交通过 `git diff --cached --check` 和提交前格式检查。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| `git diff --check` | 工作区和本地冲突解决改动通过。将合并提交与两个父提交逐项比较时，官方新增测试文档保留了 Markdown 尾随空格及 EOF 空行提示；未改写这些上游文档格式。 |
| 冲突标记检查 | 通过；仓库中仅剩一处文档代码示例里的等号分隔文本，不是 Git 冲突标记。 |
| `make -C backend test-unit` | 未完成。本机 Go 为 `1.26.6`，项目要求 `1.27.4`；Go 自动下载 `1.27.4` 时因网络长时间无响应而中止。 |
| `pnpm --dir frontend install --frozen-lockfile` | 未完成。本机 pnpm 11.5.0 不再读取 `package.json` 的 `pnpm.overrides`，先报告 lockfile 配置不匹配；使用 npm registry 重试时多个包请求出现 `ECONNRESET` 和超时。未修改 lockfile，未生成 `frontend/node_modules`。应按仓库既有流程使用 pnpm 9.15.9 后重试。 |
| `make -C backend test` | 尚未执行，等待 Go 1.27.4 工具链可用。 |
| `make test-frontend`、`make build-frontend`、`make build` | 尚未执行，等待后端工具链和前端依赖环境确认。 |
| 数据库迁移/恢复演练 | 未执行。 |
| 生产部署和真实供应商验收 | 未执行。 |

## 发布与回滚

本次结果是本地同步分支源码，不代表可以直接生产发布。后续发布前仍需完成 Go 1.27.4 环境下的后端测试、前端检查和构建、migration 脱敏副本演练、MaaS 核心流程验收、生产备份和评审。

本次本地回滚目标为合并前的 Fork commit：

```text
de7f252d56cd93911237b76e772fceccd9bc9934
```

如果后续执行数据库 migration，回滚时必须同时评估应用版本和数据库兼容性，不能只替换应用二进制。
