# 本机源码编译与 IP HTTPS 部署

> **当前更新（2026-11-01）**：已从干净代码提交 `3800e8c079a83f6f5737ac35ea132e960a105919` 构建部署 `0.2.19-custom.3-result-dialog-local`，开启 API Key 模型测试及独立结果详情弹窗。入口仍为 `https://127.0.0.1:8443/keys`（回环 HTTP：`http://127.0.0.1:18080/keys`）。本地浏览器＋真实网关＋模拟上游验收通过，服务保持运行；当前产物、备份和限制见 [API Key 模型测试本地验收 §8](API_KEY_MODEL_TEST_LOCAL_ACCEPTANCE.md#8-结果详情弹窗部署与验收2026-11-01)。Actions 已恢复且功能源码 CI、安全扫描通过，合入状态见 [PR #6](https://github.com/chochoc/sub2api/pull/6)。下文保留早期部署过程，旧版本和旧测试数字不代表当前产物。

> 2026-10-02：当前工作区源码已构建并启动，入口为 **https://127.0.0.1:8443**，无域名。健康检查、前端资源、管理员登录、无 Key 拒绝及停止/重启已验证。仅供本机隔离验证，不宣称生产发布或真实上游验收通过。

遵守 [开发规范](DEVELOPMENT_RULES.md)、[架构指南](ARCHITECTURE_AND_MODIFICATION_GUIDE.md) 与 [入口安全说明](../deploy/EDGE_SECURITY.md)。基线 HEAD 为 `b735bd4b47bff5a9f2382e672632f8bc7dd70795`，构建包含未提交修改，版本标记 `0.2.12-local-dirty`；没有切换旧提交或下载 Sub2API 发布二进制/镜像替代源码。

## 1. 当前实例与快速操作

命令均从 `sub2api` 仓库根目录执行。[管理脚本](../deploy/local-source-https.mjs) 不安装系统服务、不修改 CA 信任、不接管已有数据库。

```bash
node deploy/local-source-https.mjs status
node deploy/local-source-https.mjs --check
node deploy/local-source-https.mjs start
# 需要停止时执行；保留所有数据
node deploy/local-source-https.mjs stop
```

`start` 对已有进程幂等；初始化只针对新的空 PostgreSQL 目录。端口冲突时报错，不结束无关进程。脚本记录 PID 及启动时间，停止前核对身份；关闭顺序为代理、应用、Redis、PostgreSQL，不强制 kill。未配置开机自启，机器重启后手动运行 `start`。

| 组件 | 地址 | 边界 |
| --- | --- | --- |
| Caddy IP HTTPS | `https://127.0.0.1:8443` | 显式 IP SAN 证书，管理 API 关闭，不监听公网或 HTTP 80 |
| 源码构建的 Sub2API | `http://127.0.0.1:18080` | 仅内部回环 HTTP；前端已 embed 嵌入 |
| PostgreSQL 18.6 | `127.0.0.1:15432` | SCRAM 认证，独立库，Unix socket 关闭 |
| Redis 7.4.6 | `127.0.0.1:16379` | 独立密码、protected mode、AOF/everysec 及快照 |
| 私有运行目录 | `.dev/local-https/` | Git 忽略；目录 700、秘密文件 600，不放入公开静态目录 |

管理员邮箱为 `admin@local.invalid`。密码只保存在 `.dev/local-https/credentials.json` 的 `admin_password` 字段，请用本机私有编辑器查看，勿粘贴到聊天、提交或日志。该文件还含数据库、Redis、JWT、TOTP 秘密，不能分享整个文件。自动安装显式提供密码，未使用应用“随机生成密码并打印日志”的流程。

首次登录的管理端合规确认必须由操作者阅读并确认；本次只读取状态，没有代替用户接受声明。实例未导入真实上游账号，也未创建业务 API Key。

## 2. 构建失败原因与修复

| 问题 | 实际处理 |
| --- | --- |
| `chatTextContract` / `newChatTextContract` 未定义，函数参数不匹配 | 前序契约接线未完成；实现真实请求级控制器，接入 JSON/SSE、usage、错误及有限收尾，不以空桩绕过编译 |
| 下载缓慢或重置 | 单次命令使用可达的 Go/npm 镜像；未改全局配置，未关闭 TLS、校验和或锁文件检查 |
| Node 20 无法启动 | 本机继承的 `NODE_OPTIONS=--use-system-ca` 不被该版本接受；仅对子命令 `env -u NODE_OPTIONS` |
| lint 工具链不匹配 | 用 Go 1.27.0 重编译 golangci-lint 2.13.0，未降低 `go.mod` |
| 全量测试首次 Ent 临时文件缺失 | 多个全包 Gate 同时使用 schema loader 临时目录；串行复跑通过，未降低断言 |
| embed 静态资源测试失败 | 旧测试请求已退役 `logo.png`；改用当前 `logo.svg`，保留类型、内容和缓存断言 |
| Redis 启动退出 | 宿主 `C.UTF-8` locale 不存在；对子进程设置 `LC_ALL=C`，不改全局 locale |

实际工具链为 Intel macOS 12 / Darwin 21.6、Go 1.27.0、Node 20.20.2、pnpm 9.15.9、golangci-lint 2.13.0。Caddy 来自 Go module `github.com/caddyserver/caddy/v2@v2.11.6`；普通 `go install` 的 `caddy version` 显示 `unknown`，精确来源以 `go version -m` 核对。链接器有面向更新 macOS 的提示，但本机已实际运行及验证 TLS；不据此承诺其他旧系统兼容。

## 3. 从当前源码重新构建

先检查工作区，保留已有修改。Go 全包 Gate **串行**执行，以下命令不自动启用 strict。

```bash
git status --short --branch
git rev-parse HEAD
export SUB2API_LOCAL_RUN="$PWD/.dev/local-https"
umask 077
mkdir -p "$SUB2API_LOCAL_RUN"/{bin,tools,downloads,ca,certs,logs}
# 本次已准备这些私有工具；新机器先安装对应版本
export PATH="$SUB2API_LOCAL_RUN/tools/pnpm/node_modules/.bin:$SUB2API_LOCAL_RUN/tools/node-v20.20.2-darwin-x64/bin:$SUB2API_LOCAL_RUN/bin:$PATH"
env -u NODE_OPTIONS node --version
env -u NODE_OPTIONS pnpm --version
(cd backend && go version)
env -u NODE_OPTIONS pnpm --dir frontend install --frozen-lockfile
env -u NODE_OPTIONS make test-frontend
env -u NODE_OPTIONS make build-frontend
make -C backend test-unit
make -C backend test
make -C backend test-integration
make -C backend build
```

本次前端下载用 `--registry=https://registry.npmmirror.com`，Go 下载用单次 `GOPROXY=https://goproxy.cn`；不将镜像写进锁文件。Node 20.20.2 Darwin x64 包已对照官方 SHASUMS 验证：`8be6f5e4bb128c82774f8a0b8d7a1cc1365a7977d9657cece0ca647b3fe04e61`。

普通后端 build 不嵌入 UI，必须在前端构建后生成 embed 产物。替换运行二进制前先停止本实例并保留旧产物备份，不边运行边原位重写程序。

```bash
node deploy/local-source-https.mjs stop
export SUB2API_LOCAL_COMMIT="$(git rev-parse HEAD)"
export SUB2API_LOCAL_VERSION="$(backend/scripts/resolve-version.sh)-local-dirty"
export SUB2API_LOCAL_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
(cd backend && CGO_ENABLED=0 go build -tags embed -trimpath \
  -ldflags="-s -w -X main.Version=$SUB2API_LOCAL_VERSION -X main.Commit=$SUB2API_LOCAL_COMMIT -X main.Date=$SUB2API_LOCAL_DATE -X main.BuildType=source" \
  -o "$SUB2API_LOCAL_RUN/bin/sub2api" ./cmd/server)
(cd backend && go test -tags embed ./internal/web)
"$SUB2API_LOCAL_RUN/bin/sub2api" --version
LC_ALL=C shasum -a 256 "$SUB2API_LOCAL_RUN/bin/sub2api"
node deploy/local-source-https.mjs start
```

HEAD 只是提交基线。复现脏工作区还需保存已审查 diff、未跟踪源码及哈希的私有部署记录；不得纳入凭据、数据库或日志。构建失败时不要启动旧产物冒充新源码。

## 4. 本机依赖准备

本实例没有 Docker，采用原生进程。Redis 7.4.6 只复用命令，不复用其他实例的数据或端口。需要 `redis-server`、`redis-cli`、OpenSSL、mkcert、C 编译器及 make，不擅自升级系统或安装全局服务。

```bash
GOTOOLCHAIN=go1.27.0 GOBIN="$SUB2API_LOCAL_RUN/bin" \
  go install github.com/caddyserver/caddy/v2/cmd/caddy@v2.11.6
GOTOOLCHAIN=go1.27.0 GOBIN="$SUB2API_LOCAL_RUN/bin" \
  go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.13.0
go version -m "$SUB2API_LOCAL_RUN/bin/caddy"
```

PostgreSQL 官方源码包已校验 SHA-256：`555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f`，与官方 `.sha256` 一致。下载中断留下的 DMG/压缩包不可执行，不能当作已安装依赖。

```bash
curl --fail --location --connect-timeout 10 --max-time 1800 \
  --output "$SUB2API_LOCAL_RUN/downloads/postgresql-18.6.tar.bz2" \
  https://ftp.postgresql.org/pub/source/v18.6/postgresql-18.6.tar.bz2
LC_ALL=C shasum -a 256 "$SUB2API_LOCAL_RUN/downloads/postgresql-18.6.tar.bz2"
# 核对上述官方摘要一致后才解压、编译
tar -xjf "$SUB2API_LOCAL_RUN/downloads/postgresql-18.6.tar.bz2" -C "$SUB2API_LOCAL_RUN/tools"
(cd "$SUB2API_LOCAL_RUN/tools/postgresql-18.6" && \
  ./configure --prefix="$SUB2API_LOCAL_RUN/tools/postgresql" --without-icu --without-readline && \
  make -j6 && make install && make -C contrib/pg_trgm install)
"$SUB2API_LOCAL_RUN/tools/postgresql/bin/postgres" --version
```

务必在独立 PostgreSQL 源码目录运行 configure/make，不能在 Sub2API 根目录生成它的 Makefile。此构建不启用可选 ICU/readline；本地库只接受回环 SCRAM 认证，不配置数据库网络 TLS。现有迁移需要 `pg_trgm`，因此同时安装扩展。首次 `start` 执行 initdb、创建库及应用 AUTO_SETUP；之后不重复初始化、不删除 `.installed`。

## 5. IP 证书与客户端信任

已生成专用 CA 与含 SAN `IP Address:127.0.0.1` 的服务器证书，未加入系统信任。已有证书先检查，不无条件重建 CA。

```bash
openssl x509 -in "$SUB2API_LOCAL_RUN/certs/server.pem" -noout -dates -ext subjectAltName
openssl verify -CAfile "$SUB2API_LOCAL_RUN/ca/rootCA.pem" "$SUB2API_LOCAL_RUN/certs/server.pem"
# 仅在新部署且证书尚不存在时生成
CAROOT="$SUB2API_LOCAL_RUN/ca" mkcert \
  -cert-file "$SUB2API_LOCAL_RUN/certs/server.pem" \
  -key-file "$SUB2API_LOCAL_RUN/certs/server-key.pem" 127.0.0.1
chmod 600 "$SUB2API_LOCAL_RUN/certs/server-key.pem"
```

客户端可单独指定 CA。浏览器要无警告访问，由操作者审阅后执行 `CAROOT="$SUB2API_LOCAL_RUN/ca" mkcert -install`；该命令修改信任存储，本次未执行。不得分发 `rootCA-key.pem` 或服务器私钥；其他客户端只接收根 CA 公有证书。禁止以 `curl -k`、`verify=false` 或关闭 Node TLS 校验作为正常使用方式。

脚本生成的 Caddyfile 仅 bind 127.0.0.1、显式 TLS、无管理端口/访问日志、覆盖转发 IP 并移除 CF/True-Client-IP 头；不压缩 SSE、不设置全局响应写超时、不启用业务重试。应用信任代理明确为 127.0.0.1/32，并关闭原始转发头兼容信任。客户端入口是 HTTPS，代理到应用仍是内部回环 HTTP；局域网、公网、域名 OAuth、Passkey、webhook 均未验收。

## 6. 实际验证结果

```bash
curl --fail --show-error --cacert "$SUB2API_LOCAL_RUN/ca/rootCA.pem" \
  https://127.0.0.1:8443/health
node deploy/tests/local-source-https-test.mjs
node deploy/tests/local-source-https-smoke.mjs
make check-architecture-index
git diff --check
```

[smoke 检查](../deploy/tests/local-source-https-smoke.mjs) 只针对固定本机实例，读取私有凭据进行普通登录、不打印密码/token、不接受合规声明、不调用真实上游。

| 检查 | 结果与边界 |
| --- | --- |
| 普通 build、embed build | 通过，已运行当前源码嵌入版 |
| `make -C backend test` | 串行复跑通过，lint `0 issues` |
| `make -C backend test-unit` | 最终复跑通过 |
| 新契约定向测试、文本生命周期 race | 通过，最终 race 复跑通过 |
| `make test-frontend` | lint、类型检查、critical Vitest 21 文件 / 308 测试通过；不是全套 Vitest |
| `make build-frontend` | 通过；有 Vite 大 chunk 提示 |
| embed web 测试 | SVG 路径修正后通过，未删减缓存断言 |
| `make -C backend test-integration` | 退出 0，但 repository harness 因缺 Docker 自动跳过，**不算集成通过** |
| 脚本语法/配置测试、Compose gateway/security 文本检查 | 通过；Compose simple-mode-env 因缺 Docker 无法完成，未做容器验收 |
| HTTPS、前端、登录 | 自定义 CA 严格验证：health、根页面、JS、SVG、登录和合规状态均 200；无 Key `/v1/models` 为 401 |
| 数据与重启 | 停止/启动后再次 smoke 通过；库中 291 条迁移记录、1 个管理员及 pg_trgm 扩展；未清空数据 |
| 监听范围 | lsof 确认四个 TCP 端口均仅绑定 127.0.0.1 |
| 文档、格式与架构索引 | 三份文档 103 个本地链接、13 段 Bash 语法及围栏检查通过；18 个变动 Go 文件 gofmt 干净；架构索引覆盖 27 个代码路径，`git diff --check` 通过 |
| 真实上游、浏览器视觉、系统 CA 信任 | 未验收/未修改，不用基础健康检查替代 |

日志位于 `.dev/local-https/logs/`，不提交或公开。`start` 中途失败保留已启动的本实例组件和数据，可修复后重试或执行 `stop`。若异常终止遗留 `lifecycle.lock`，先确认没有正在运行的启动/停止操作，再将该单个锁文件移入私有备份目录后重试，不能清空运行目录。

本次未暂存、提交或推送源码；因此没有把暂存区/CI 检查写成通过。合入前仍须按开发规范补齐适用集成门禁、人工评审及暂存区架构索引检查。

## 7. 开关、升级与恢复

本机部署默认 `policy=strict`、`stop_mode=text`、`drain_timeout_seconds=30`，用于让契约方案在运行实例中生效。回滚或兼容旧客户端时可停止后显式选择：

```bash
node deploy/local-source-https.mjs stop
GATEWAY_OPENAI_CHAT_CONTRACT_POLICY=strict \
GATEWAY_OPENAI_CHAT_CONTRACT_STOP_MODE=text \
GATEWAY_OPENAI_CHAT_CONTRACT_DRAIN_TIMEOUT_SECONDS=30 \
node deploy/local-source-https.mjs start
```

对正在运行的实例重复 `start` 不会热更新配置。回滚须停止后显式设置 `legacy/reject/30` 再启动；若 shell 已 export strict 变量，要先清除或覆盖。legacy 仍有历史 stop 丢失、小上限 floor、Codex 上限删除等限制，不能标为五项问题全解决。范围见 [契约方案](SUB2API_OPENAI_CONTRACT_COMPATIBILITY_TECHNICAL_PLAN.md) §1.5：C1 按用户确认解决，其余原始问题保留真实复测状态。

本轮无新增数据库迁移，但新实例会执行基线已有迁移。升级前停止新请求和后台写入，以 `pg_dump -Fc` 备份 PostgreSQL；停止 Redis 后备份完整持久化目录（含 AOF 子目录）；安全保存配置、凭据、安装标记、证书及上一版程序，备份权限 700/600。旧程序回滚前确认 schema 兼容性并在隔离库演练恢复，不能只换二进制就保证恢复。本次不宣称生产迁移或备份恢复演练通过。
