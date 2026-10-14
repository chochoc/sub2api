# Sub2API 官方版本升级实施方案

## 目标与现状

将服务器上的 Sub2API 从 **0.2.8** 升级到执行时官方最新正式版。当前调研结果：

- 部署方式：Linux 原生二进制，不使用 Docker。
- 服务：`systemd` 管理，二进制位于 `/opt/sub2api/sub2api`。
- 当前版本：`0.2.8`。
- 数据库：PostgreSQL 15，数据库约 1.47 GB。
- Redis：本机 Redis，监听 `127.0.0.1:6379`。
- 反向代理：Nginx，Sub2API 内部监听 `127.0.0.1:3580`。
- 当前数据规模：6 个用户、35 个上游账号、68 个 API Key、23 个分组。
- 当前 systemd 覆盖配置位于 `/etc/systemd/system/sub2api.service.d/override.conf`，必须保留。

截至 2026-10-11，官方 GitHub 最新正式 Release 为 [v0.2.15](https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.15)，Linux amd64 安装包及 SHA-256 校验值由官方 Release 提供。

升级只能使用 `Wei-Shaw/sub2api` 官方 Release 二进制；不使用本机 Fork 构建、不从源码编译、不执行未锁定版本的在线安装脚本。

## 核心安全原则

- 先下载、校验、演练，最后才停止生产服务。
- 升级前同时备份 PostgreSQL、Redis、配置文件、systemd 配置和旧二进制。
- 使用版本固定的官方 Release URL 和 `checksums.txt`。
- 不覆盖 `config.yaml`、JWT secret、数据库密码、Redis 密码或 systemd override。
- 生产切换开始后设置 300 秒硬截止时间；超过 5 分钟立即回滚或恢复旧服务，放弃本次升级。
- 数据库迁移是前向迁移；官方部署文档明确说明，数据库回滚需要恢复备份或执行人工补偿 SQL。[官方迁移说明](https://github.com/Wei-Shaw/sub2api/blob/main/deploy/README.md)
- 回滚优先只回滚二进制并保留已迁移数据库，避免丢失升级后产生的新数据。只有在服务尚未重新开放、确认没有新写入时，才允许恢复升级前数据库备份。

## 实施步骤

### 1. 生产前置检查

通过 `/Users/james/sub2api_gcp.sh` 使用其 SSH 参数连接服务器，执行只读检查：

- 确认主机、磁盘、内存、CPU、服务状态。
- 记录当前二进制版本、SHA-256、文件权限和所有权。
- 记录 systemd unit、override、Nginx 配置。
- 记录 PostgreSQL、Redis 状态及监听端口。
- 记录关键数据数量和 `schema_migrations` 最大迁移文件。
- 记录健康检查、Nginx HTTPS 访问、管理员登录和一个 API Key 调用结果。

若服务不健康、磁盘空间不足、数据库存在错误、备份目录不可写或无法获得 root 权限，停止升级。

### 2. 固定官方目标版本

在正式执行时重新查询官方 GitHub Release：

```text
GET https://api.github.com/repos/Wei-Shaw/sub2api/releases/latest
```

锁定返回的正式、非草稿、非预发布版本及对应 commit、Release URL、Linux amd64 包名和 SHA-256。

若目标版本不是当前调研得到的 `v0.2.15`，必须重新完成：

1. 官方 Release 变更审查；
2. 数据库迁移差异审查；
3. 本机数据副本演练；
4. 回滚演练。

不得在未重新演练的情况下直接追新版本。

### 3. 创建可验证备份

在服务器上创建仅 root 可读的备份目录，至少保存：

```text
sub2api-pre-upgrade-<timestamp>/
├── postgres.dump                 # pg_dump -Fc
├── postgres-globals.sql          # pg_dumpall --globals-only
├── redis.rdb
├── config.yaml
├── sub2api.service
├── override.conf
├── nginx-sub2api-config
├── sub2api.old
├── manifest.sha256
└── metadata.txt
```

PostgreSQL 备份要求：

- 使用 `pg_dump -Fc`。
- 同时导出 globals。
- 使用 `pg_restore --list` 验证归档可读。
- 记录数据库大小、表数量、关键表行数和 `schema_migrations`。
- 备份文件权限设为 `0600`。

Redis 备份要求：

- 使用 `redis-cli --rdb`。
- 使用 `redis-check-rdb`（若系统提供）验证。
- 记录 keyspace 数量。
- Redis 作为缓存和运行状态数据，仍需备份，但 PostgreSQL 是用户、渠道、Key 等核心数据的权威来源。

配置和旧二进制要求：

- 复制 `config.yaml`，不得在备份内容中公开密码和 secret。
- 复制完整 systemd unit 和 override。
- 复制当前二进制为带时间戳的不可覆盖文件。
- 对所有备份生成 SHA-256 清单。

### 4. 本机隔离演练

按照已选择的“本机隔离演练”执行：

1. 将 PostgreSQL 备份恢复到本机隔离数据库。
2. 使用隔离配置连接恢复后的数据库和 Redis。
3. 使用当前 0.2.8 二进制确认副本可启动。
4. 使用官方目标版本二进制启动，观察迁移耗时和日志。
5. 核对迁移结果：
   - `schema_migrations` 只增加预期迁移；
   - 用户、账号、渠道、分组、API Key、订阅、余额和设置数量一致；
   - 关键业务表无异常删除或截断；
   - 数据库迁移无 checksum mismatch、SQL 错误或锁等待超时。
6. 停止新版本，使用旧 0.2.8 二进制启动同一份“已迁移数据库”。
7. 验证旧版本健康检查、管理员登录、API Key 鉴权、渠道读取和最小 API 请求。

从 0.2.8 到 0.2.15 的已确认迁移包括：

- `payment_orders.bonus_amount` 新增字段；
- TypeSafe 平台约束扩展；
- 删除部分平台数据库 CHECK 约束。

如果旧二进制无法在迁移后的数据库上正常启动，或关键业务数据无法读取，禁止生产升级。

演练必须记录：

- 数据库迁移耗时；
- 新版本启动耗时；
- 旧版本回滚启动耗时；
- 总切换时间；
- 失败时恢复所需时间。

若任一演练结果超过 300 秒，或无法稳定回滚，放弃升级。

### 5. 生产升级切换

升级窗口开始前：

- 暂停后台管理操作和批量任务。
- 确认没有长时间运行的充值、支付回调、批量图片任务或重要流式请求。
- 记录切换开始时间。

执行顺序：

1. 再次确认健康检查和数据库连接正常。
2. 再做一次 PostgreSQL 逻辑备份，作为最终恢复点。
3. 再次复制旧二进制并校验 SHA-256。
4. 将官方 Release 包下载到 `/opt/sub2api/.upgrade-v0.2.15/`。
5. 校验官方 `checksums.txt`，确认包名和 SHA-256 完全匹配。
6. 解压后检查新二进制版本、架构、权限和 SHA-256。
7. 执行 `systemctl stop sub2api`，立即开始 300 秒计时。
8. 保留旧二进制，例如：

   ```text
   /opt/sub2api/sub2api.pre-v0.2.8.<timestamp>
   ```

9. 将已校验的新二进制原子替换为 `/opt/sub2api/sub2api`。
10. 设置所有权为 `sub2api:sub2api`，权限为 `0755`。
11. 保留原有 `config.yaml`、systemd unit、override 和 Nginx 配置。
12. 执行 `systemctl start sub2api`。
13. 观察迁移日志和服务状态。
14. 通过本机健康检查、Nginx HTTPS、管理员登录和 API Key 请求验收。
15. 记录恢复服务耗时。

不得执行会覆盖现有配置或 systemd override 的“一键安装”流程。

## 回滚方案

### A. 二进制回滚

适用于新版本启动失败、健康检查失败或业务验收失败，但数据库仍可被旧版本读取：

1. 停止新版本。
2. 将旧二进制恢复为 `/opt/sub2api/sub2api`。
3. 保持数据库、配置、Redis 和 systemd 配置不变。
4. 启动旧服务。
5. 验证健康检查、登录、API Key 和渠道请求。

这是首选回滚方式，因为不会丢失升级后可能已经写入数据库的新数据。

### B. 数据库恢复

只有同时满足以下条件时才允许恢复升级前数据库：

- 服务尚未重新开放给用户；
- 确认升级后没有任何业务写入；
- 新旧二进制均无法安全运行在迁移后的数据库上；
- 已确认恢复备份不会覆盖有效的新数据。

恢复后启动旧二进制并完成完整验收。

如果升级后已经产生业务写入，禁止直接恢复旧数据库备份；应保留当前数据库，优先修复或回滚二进制，避免违反“数据不能丢失”要求。

## 放弃升级条件

出现任一情况，立即停止本次升级并恢复旧服务：

- 官方 Release 无法获取或 SHA-256 不匹配；
- 目标版本不是正式 Release；
- 本机演练无法完成；
- 旧二进制无法读取迁移后的数据库；
- 迁移出现 checksum mismatch、SQL 错误或数据数量异常；
- 生产服务停止后 300 秒内未恢复健康；
- 用户、渠道、API Key、分组、余额或订阅数据出现差异；
- Nginx、登录、鉴权或最小 API 请求验收失败；
- 回滚所需时间预计超过 300 秒。

## 验收标准

升级只有全部满足以下条件才算成功：

- 运行版本为指定的官方 Release 版本；
- 官方包 SHA-256 校验通过；
- PostgreSQL、Redis、Sub2API、Nginx 全部正常；
- 用户、渠道、账号、API Key、分组、订阅和余额数据与升级前一致；
- 关键表无数据丢失、截断或异常减少；
- 管理员可以登录；
- 旧 API Key 可以完成鉴权和最小请求；
- Nginx HTTPS 访问正常；
- 从停止旧服务到健康检查恢复不超过 300 秒；
- 旧二进制回滚演练已在迁移后数据库上成功完成；
- 备份、校验清单和操作日志已保存。

## 执行记录

- 2026-10-11：官方 Release API 确认最新正式版为 `v0.2.15`。
- 2026-10-11：服务器只读检查通过，生产版本为 `0.2.8`，服务健康。
- 2026-10-11：已创建并验证 PostgreSQL、Redis、配置、systemd、Nginx 和旧二进制备份。
- 2026-10-11：macOS 本机无法执行 Linux amd64 二进制，因此使用服务器隔离数据库、隔离 Redis 和隔离端口完成真实运行时演练。
- 2026-10-11：旧版 0.2.8 副本启动通过；v0.2.15 迁移通过；迁移数由 289 增至 292；用户、账号、API Key、分组、渠道和订阅计数保持一致；旧版 0.2.8 在迁移后的副本数据库上再次启动通过。
- 2026-10-11：生产切换使用官方 `sub2api_0.2.15_linux_amd64.tar.gz`，SHA-256 为 `7119037a56a43cc74d42de627c44abcfb99bb34c743aff4ee7c8defc90e80b1c`。
- 2026-10-11：生产服务切换后约 2 秒恢复健康；systemd、Nginx 根页面和 `/health` 均正常；升级后已有真实 API Key 请求返回 200。
- 2026-10-11：生产数据库迁移数为 292，用户 6、账号 35、API Key 68、分组 23、渠道 1、订阅 3，均与升级前一致。
- 2026-10-11：配置文件和 systemd override 校验未改变；旧二进制保存在 `/opt/sub2api/sub2api.pre-v0.2.8-20261010T231655Z`；最终备份位于 `/var/backups/sub2api-final-v0.2.15-20261010T215725Z`；未执行数据库恢复回滚。
