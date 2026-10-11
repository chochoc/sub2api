# Sub2API Admin & Ops skill

这是一个可直接复制的 Codex skill，用 Python 标准库管理和诊断 Sub2API。重点是 502/503、请求错误、上游错误、账号归因、系统日志和安全清理；Node.js CLI 保留了账号、分组、代理、兑换码等已有管理面板操作。

## 安装与配置

本 skill 不检查或限定 Python 版本；命令中的 `python` 可直接替换为 `python3`，两种解释器调用方式都支持。

将整个目录复制到目标机器的 Codex skills 目录，或在当前仓库中直接使用：

```bash
export SUB2API_BASE_URL='https://your-sub2api-domain'
export SUB2API_ADMIN_TOKEN='<replaceable-admin-token>'
export SUB2API_SSH_SCRIPT='/Users/james/sub2api_gcp.sh'
```

`SUB2API_ADMIN_TOKEN` 支持 JWT 和 Sub2API Admin API Key。`auto` 模式会将 `admin-` 前缀的令牌作为 `x-api-key`，其它令牌作为 `Authorization: Bearer`；也可以显式设置：

```bash
export SUB2API_AUTH_MODE=api-key   # 或 bearer
```

也兼容 `SUB2API_JWT` 和 `SUB2API_ADMIN_API_KEY`。令牌不会写入文件、日志或示例。

如果管理 API 只绑定在远端回环地址，需要先建立 SSH 隧道，再把 `SUB2API_BASE_URL` 指向本地隧道端口。`SUB2API_SSH_SCRIPT` 本身用于只读健康检查，不会自动重启、升级或修改远端服务。

## 常用操作

```bash
python scripts/sub2api_admin.py health
python scripts/sub2api_admin.py ops-report --since 6h --format markdown
python scripts/sub2api_admin.py errors analyze --since 24h
python scripts/sub2api_admin.py errors list --status-codes 502,503 --since 1h
python scripts/sub2api_admin.py errors get --id 123
python scripts/sub2api_admin.py errors request-upstream --id 123
python scripts/sub2api_admin.py account-report --ids 27,32 --since 24h
python scripts/sub2api_admin.py dashboard error-trend --since 6h
python scripts/sub2api_admin.py system-logs list --level error --since 1h
```

写操作需要显式确认：

```bash
python scripts/sub2api_admin.py errors resolve --id 123 --resolved true --confirm
python scripts/sub2api_admin.py system-logs cleanup --filter-file filters.json --confirm
```

新版本接口可以用只读或已确认的原始 Admin API 调用：

```bash
python scripts/sub2api_admin.py api GET /admin/ops/system-logs/health
python scripts/sub2api_admin.py api GET /admin/groups/all
python scripts/sub2api_admin.py api POST /admin/accounts/bulk-update --json '{"account_ids":[40],"concurrency":10}' --confirm
```

账号和兑换码等已有 CRUD 命令：

```bash
node scripts/sub2api-admin.js accounts list --page-size 20
node scripts/sub2api-admin.js accounts get 40
node scripts/sub2api-admin.js redeem-codes list --page-size 20
```

## 错误判断原则

报告会合并 `/ops/errors`、`/ops/request-errors` 和 `/ops/upstream-errors`，按 ID 去重，并区分上游/代理、平台路由、账号鉴权和上下文不足。单独一个 502/503 不会被当作账号或代理故障；应结合 phase、source、upstream status、request ID、账号和代理分布继续钻取。

## 分享

目录只依赖 Python 标准库，不需要虚拟环境或第三方包。运行 `./package.sh [输出文件]` 可生成不含令牌和 Python 缓存的 tar.gz 包。复制整个目录即可作为 skill 使用。
