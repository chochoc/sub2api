# Sub2API 管理 Skill 技术实现方案

日期：2026-10-17。范围：日常管理及后台现有定时测试、备份计划配置；不新增外部日历系统。实施状态和验证结果见文末。

## 1. 核查修正与目标

现有 Python CLI 偏重错误诊断，Node CLI 偏重账户 CRUD，均不直接读取 Keychain。`api-keys-trend` 按 Token 数选 Top K，不能用作金额排行。账户列表已有 current_concurrency，但 CLI 缺少全分页汇总和可选调度评分。用户页面 `/keys` 的真实接口是 `/api/v1/keys`，需要 JWT；管理员密钥不能直接使用该用户接口。管理员 API 原先只有 KEY 分组/限速重置，缺少创建和额度修改。

目标：保留已有诊断/CRUD；新增明确的 users、keys、usage、accounts load、scheduled-tests、backup-schedule 命令；统一凭据、写入确认及输出脱敏；组合查询支持分页、时间、用户、KEY、账户、分组、模型、请求类型等服务端实际支持的筛选。

## 2. 架构与接口

- Python 标准库为新增管理命令的主实现；两个历史入口保持同步副本，旧 Node 账户/兑换码功能保留。
- Keychain 按 service/account 精确读取，可配置 `SUB2API_KEYCHAIN_SERVICE` / `SUB2API_KEYCHAIN_ACCOUNT`，默认 service=sub2api-admin，account=base URL。不扫描全部凭据、不输出明文、不落盘。兼容显式 token 和现有环境变量；明确配置 Keychain 时失败即报错。
- Admin API 增加 `/admin/users/:id/keys` 及 `/:key_id` CRUD，复用原 APIKeyService 的额度、分组权限、所有权、缓存失效和幂等逻辑；操作人保持管理员，不通过替换认证主体伪装目标用户。新增 `/admin/me` 获取真实认证用户。用户 JWT 原路由行为不变。
- 创建 KEY 默认只输出脱敏数据；用户显式指定 `--secret-output` 时用排他创建、0600 文件交付 KEY，不覆盖文件。
- 全页遍历使用响应中的实际 page_size/total，稳定 ID 排序，重复页、超限或分页中断明确失败；不得静默返回不完整排行榜。
- 消费排行读取完整筛选后的 usage 明细，按 api_key_id 汇总 actual_cost（用户实际扣费），可选 total_cost（标准价）或 tokens。Decimal 汇总，时间默认 Asia/Shanghai 今日；返回时间、金额口径、扫描数量和 complete。不调用 Token Top K 冒充金额排行。大数据使用 max-pages 显式限制，达到限制返回错误。
- users 今日统计使用 `/admin/usage/stats` + user_id + 明确日期和 timezone；当前管理员从 `/admin/users/me` 获取。不猜测用户 ID。
- accounts load 自动翻页，并返回服务端列表中的 current_concurrency、priority、group_ids、schedulable、可选 scheduler_score；列表里的实时值为服务端采样，不宣称事务快照。
- 定时测试覆盖按账户计划列表、创建、更新（含 enabled）、删除及结果；备份计划 GET/PUT；已有原始 API 保留作扩展出口。

## 3. 写操作与安全

所有业务写入需命令参数 `--confirm`（用户已授权时代理可直接传入，不重复询问）；KEY 创建支持 Idempotency-Key 和显式 `--secret-output`，不自动重试写入。未知参数直接拒绝，避免拼写错误导致漏筛选。HTTP 禁止重定向携带凭据；生产使用 HTTPS，HTTP 仅允许回环测试。输出保留 api_key_id 等业务标识，屏蔽真正的 key/token/credentials；错误也脱敏。

## 4. 同步、测试、上线与回滚

以 sub2api-admin-skill 为源码，发布时同步 skills/sub2api-admin 副本。测试覆盖 Keychain 成功/失败、认证优先级、全分页、金额而非 Token 排行、时区日期、空数据、写入确认、秘密文件与错误脱敏。Go 测试覆盖管理员目标用户解析、原用户路由隔离和字段校验；运行相关包测试和构建。

本地完成不等于线上已部署。新增管理员 KEY CRUD 和 me 需要发布后端后才能在线使用；旧服务器返回 404 时说明升级要求，不绕过鉴权。无数据库迁移，回滚恢复旧二进制和旧 skill 即可；已经创建或修改的数据不会自动回滚。本任务不修改生产数据、不重启生产服务。

## 5. 实施与验证记录

已实施：Python 13 项单元测试通过，Node 脚本语法检查通过，Python 编译通过，`tools/check_architecture_index.py` 和 `git diff --check` 通过。后端管理员、路由和 handler 定向测试在 `GOEXPERIMENT=jsonv2` 下通过；不设置该开关时 Go 1.26.3 会因 `encoding/json/jsontext` 标准库实验包阻断。skill-creator 校验脚本因环境缺少 PyYAML 未能运行。尚未连接生产服务，未创建或修改真实 KEY、用户或计划。
