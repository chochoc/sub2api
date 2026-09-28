# Sub2API 定制开发与官方代码同步操作手册

## 1. 目的

本手册解决以下长期维护问题：

> 使用 Sub2API 搭建自己的 AI MaaS 管理系统，需要修改源码满足自身业务需求，同时又要持续获得 Sub2API 官方的新功能、安全修复和兼容性更新。

解决办法不是避免修改源码，而是把官方代码、自己的稳定代码和正在开发的改动分开管理，并通过固定流程周期性合并官方更新。

本手册适用于当前工作目录：

```text
/Users/james/git/a9/sub2api
```

当前 Git 远端已经配置为：

```text
origin    git@github.com:chochoc/sub2api.git       # 自己的 Fork，可推送
upstream  git@github.com:Wei-Shaw/sub2api.git      # 官方仓库，只拉取
```

官方远端的 push URL 已禁用，防止误推：

```text
upstream (push) = DISABLED
```

本文命令兼容本机 Git 2.20.1，因此使用 `git checkout`，不使用较新版本才支持的 `git switch`。

---

## 2. 总体模型

```text
Wei-Shaw/sub2api
      |
      | fetch / merge
      v
upstream/main -----------------------------+
                                             |
                                             v
chochoc/sub2api                         sync/upstream-*
      |                                      |
      | origin/main <------------------------+  测试、评审后合并
      |
      +---- feature/*   单项定制功能
      +---- fix/*       普通缺陷修复
      +---- hotfix/*    生产紧急修复
```

各分支职责：

| 名称 | 职责 | 是否长期存在 |
| --- | --- | --- |
| `upstream/main` | 官方最新代码的本地远端引用 | 是，只读 |
| `origin/main` | 自己 Fork 中可部署的稳定代码 | 是 |
| 本地 `main` | 跟踪 `origin/main`，保持可发布 | 是 |
| `feature/<name>` | 一项定制需求 | 否，合并后删除 |
| `fix/<name>` | 一项普通修复 | 否，合并后删除 |
| `hotfix/<name>` | 生产紧急修复 | 否，合并后删除 |
| `sync/upstream-<date>` | 一次官方升级 | 否，合并后删除 |

核心规则：

1. 不直接在 `main` 上开发。
2. 不向 `upstream` 推送。
3. 不对已经共享或部署的 `main` 执行 rebase 或强制推送。
4. 一项需求一个分支，提交保持小而清晰。
5. 官方升级必须经过独立同步分支、测试和评审。
6. 生产部署只能使用经过验证的 commit 或自定义 tag，不能直接部署不断变化的 `upstream/main`。

---

## 3. 每次工作前的检查

进入仓库：

```bash
cd /Users/james/git/a9/sub2api
```

确认当前状态：

```bash
git status --short --branch
git remote -v
git branch -vv
```

正常情况下应满足：

- 当前位于预期分支；
- 没有来源不明的未提交文件；
- `main` 跟踪 `origin/main`；
- `origin` 指向 `chochoc/sub2api`；
- `upstream` 指向 `Wei-Shaw/sub2api`，push 显示 `DISABLED`。

如果工作区有未提交修改，不要直接同步官方代码。先完成以下操作之一：

- 提交到当前功能分支；
- 确认修改可以丢弃后再处理；
- 临时使用 `git stash push -u -m "说明"` 保存。

不要在不清楚文件来源时执行 `git reset --hard` 或 `git clean -fd`。

---

## 4. 日常定制开发流程

### 4.1 更新自己的稳定分支

开始一项新需求前：

```bash
cd /Users/james/git/a9/sub2api
git checkout main
git pull --ff-only origin main
git status --short --branch
```

`--ff-only` 可以阻止 Git 在不知情的情况下生成合并提交。

### 4.2 创建功能分支

分支名称使用简短英文：

```bash
git checkout -b feature/custom-billing-rules
```

其他示例：

```text
feature/company-branding
feature/custom-channel-routing
feature/tenant-quota-policy
fix/incorrect-token-accounting
hotfix/payment-callback-validation
```

### 4.3 开发和提交

开发过程中经常检查：

```bash
git status --short
git diff
git diff --staged
```

提交时只包含同一目的的修改：

```bash
git add <明确的文件路径>
git commit -m "feat: add tenant quota policy"
```

推荐的提交类型：

```text
feat:     新功能
fix:      缺陷修复
refactor: 不改变行为的重构
test:     测试
docs:     文档
build:    构建和依赖
chore:    其他维护工作
```

不要把品牌替换、计费规则、数据库迁移和协议转换混在一个提交中。拆分后，上游同步发生冲突时更容易判断每一处修改的意图。

### 4.4 验证改动

后端单元测试：

```bash
make -C backend test-unit
```

后端完整测试和静态检查：

```bash
make -C backend test
```

前端依赖安装、检查和构建：

```bash
pnpm --dir frontend install --frozen-lockfile
make test-frontend
make build-frontend
```

整个项目构建：

```bash
make build
```

当前机器曾检测到 Corepack 的 pnpm 签名校验异常。在该问题修复前，不能把“前端未运行”写成“前端验证通过”。

涉及以下功能时还要执行对应的集成或人工验收：

- API Key 鉴权；
- 用户、套餐、余额和配额；
- 预扣费、最终结算和退款；
- OpenAI、Claude、Gemini 等协议转换；
- SSE 流式输出、工具调用和 usage；
- 渠道选择、粘性会话、限流和故障切换；
- 支付回调；
- 数据库迁移；
- 管理后台关键流程。

### 4.5 推送并合并

```bash
git push -u origin feature/custom-billing-rules
```

在 GitHub 创建 Pull Request：

```text
feature/custom-billing-rules -> main
```

PR 至少说明：

- 为什么修改；
- 修改了哪些模块；
- 数据库和配置是否变化；
- 测试命令及真实结果；
- 发布和回滚注意事项。

测试通过并完成评审后再合并。合并完成后更新本地分支：

```bash
git checkout main
git pull --ff-only origin main
```

确认不再需要功能分支后再删除：

```bash
git branch -d feature/custom-billing-rules
git push origin --delete feature/custom-billing-rules
```

---

## 5. 定制代码如何降低上游冲突

定制方式按优先级选择：

1. 配置或环境变量；
2. 数据库配置项；
3. 新增独立文件、package、service、handler 或前端 feature；
4. 在稳定边界增加接口、适配器或 wrapper；
5. 最后才直接修改官方核心流程。

实践要求：

- 密钥、域名、价格、模型列表和部署参数不得硬编码；
- 品牌资源与业务逻辑分开提交；
- 新渠道尽量实现为独立适配器；
- 自定义计费规则集中管理，不散落到多个 handler；
- 不复制整份官方大文件后再修改；
- 不手工编辑生成文件，应修改源定义后运行官方生成命令；
- 自定义逻辑必须有测试，测试应描述自己的业务契约；
- 可以贡献给官方的通用修复优先提交上游 PR，减少永久维护成本。

修改核心转发、鉴权、计费或数据库模型前，先记录：

```text
业务需求
上游原始行为
定制后的行为
兼容边界
测试用例
失败回滚方式
```

这些信息是解决未来合并冲突的依据。

---

## 6. 检查官方是否有更新

只获取远端信息，不修改当前文件：

```bash
cd /Users/james/git/a9/sub2api
git fetch upstream --prune --tags
```

查看官方比自己的 `main` 多出的提交：

```bash
git log --oneline main..upstream/main
```

统计双方差异：

```bash
git rev-list --left-right --count main...upstream/main
```

输出示例：

```text
3    12
```

含义：

- 左侧 `3`：自己的 `main` 有 3 个官方没有的提交；
- 右侧 `12`：官方有 12 个自己的 `main` 尚未合入的提交。

查看文件层面的变化：

```bash
git diff --stat main..upstream/main
git diff --name-status main..upstream/main
```

建议检查频率：

- 每周检查一次官方 `main`；
- 每个官方 Release 都进行评估；
- 安全修复立即评估；
- 正在进行大型定制时，至少每周同步一次，避免差异积累数月。

“检查更新”和“合并更新”是两件事。`git fetch` 是安全的只读操作，不会改变工作区。

---

## 7. 标准官方同步流程

以下流程适用于自己的 `main` 已经包含定制代码之后。

### 7.1 准备同步分支

```bash
cd /Users/james/git/a9/sub2api
git fetch origin --prune
git fetch upstream --prune --tags
git checkout main
git pull --ff-only origin main
git status --short --branch
```

工作区必须干净，然后创建同步分支：

```bash
git checkout -b sync/upstream-20260928
```

日期替换为实际同步日期。一次同步只使用一个分支。

### 7.2 合并官方代码

```bash
git merge --no-ff upstream/main -m "merge: sync upstream main 2026-09-28"
```

这样保留自己的提交历史和官方历史，不重写已经共享的 `main`。

如果团队决定只跟随官方发布版本，可先查看 tag：

```bash
git tag --sort=-version:refname | head -20
git show --no-patch <官方版本标签>
```

确认标签没有落后于当前代码并完成评估后，再把 `<官方版本标签>` 作为 merge 目标。不要为了追求旧 tag 对 `main` 执行 reset 或降级。

### 7.3 无冲突时

立即查看本次合并的内容：

```bash
git status --short --branch
git log --oneline --decorate --graph -30
git diff --stat main..HEAD
```

然后执行第 9 节的升级验证。

### 7.4 有冲突时

Git 会停止合并。查看冲突：

```bash
git status
git diff --name-only --diff-filter=U
```

在本流程中：

- `ours` 是自己的定制分支内容；
- `theirs` 是本次合入的官方内容。

不要对所有文件批量选择 `ours` 或 `theirs`。逐个文件理解双方修改目的后处理。

可用于检查单个文件：

```bash
git diff --ours -- <文件>
git diff --theirs -- <文件>
```

确实需要完整保留某一侧时才使用：

```bash
git checkout --ours -- <文件>
git checkout --theirs -- <文件>
```

手工解决后：

```bash
git add <已经解决的文件>
git status
git commit
```

当前仓库已经启用 `rerere`。Git 会记录冲突解决方式，在未来遇到相似冲突时尝试复用，但仍必须审查结果和运行测试。

如果发现本次升级范围不清楚或无法安全解决，可以完整撤销正在进行的 merge：

```bash
git merge --abort
```

该操作应在合并冲突尚未提交时执行。

### 7.5 推送同步分支并评审

```bash
git push -u origin sync/upstream-20260928
```

创建 PR：

```text
sync/upstream-20260928 -> main
```

升级 PR 必须记录：

- 上游起止 commit；
- 上游重要变化；
- 冲突文件和解决原则；
- 数据库迁移；
- 新增或废弃配置；
- 测试结果；
- 生产升级和回滚步骤。

禁止绕过测试直接把同步分支推成 `main`。

### 7.6 合并后的本地整理

PR 合并后：

```bash
git checkout main
git pull --ff-only origin main
git branch -d sync/upstream-20260928
```

如果 Git 提示分支未合并，先检查 GitHub PR 的合并方式和提交内容，不要立即使用 `-D`。

---

## 8. 功能开发期间如何吸收新的 main

短期、尚未共享的个人功能分支可以 rebase：

```bash
git fetch origin
git checkout feature/custom-billing-rules
git rebase origin/main
```

但满足以下任一条件时，不要随意 rebase：

- 分支已经由多人使用；
- 分支已经进入联合测试；
- 分支提交已被其他分支引用；
- 分支已经部署。

这类情况下使用普通 merge：

```bash
git checkout feature/custom-billing-rules
git merge origin/main
```

严禁对共享的 `main` 使用：

```text
git rebase upstream/main
git push --force origin main
```

---

## 9. 官方升级验证清单

每次同步上游后至少完成以下检查。

### 9.1 代码和依赖

- 阅读官方新增提交和 Release Notes；
- 检查 `go.mod`、`go.sum`、`frontend/package.json` 和 lockfile；
- 检查环境变量、配置结构和默认值变化；
- 检查 Docker Compose、构建脚本和端口变化；
- 检查生成代码是否需要重新生成。

### 9.2 自动化验证

```bash
make -C backend test-unit
make -C backend test
make test-frontend
make build
```

根据变更范围增加集成测试、端到端测试或协议回归。不能因为冲突已经解决，就认为行为仍然正确。

### 9.3 数据库升级

- 阅读新增 migration；
- 用生产数据库的脱敏副本演练升级；
- 记录迁移耗时和锁表风险；
- 确认旧版本应用能否读取迁移后的数据库；
- 如果不能，回滚方案必须是“应用与数据库一起恢复”。

不要在没有备份和演练的情况下直接让新版本连接生产数据库执行迁移。

### 9.4 MaaS 业务验收

- 管理员和普通用户登录；
- API Key 创建、禁用和鉴权；
- 渠道创建、测试和调度；
- 套餐、充值、余额和配额；
- 请求预扣和最终结算；
- OpenAI Chat Completions / Responses；
- Claude Messages；
- Gemini；
- SSE、工具调用和 usage；
- 限流、并发和失败重试；
- 日志脱敏；
- 自己增加的全部定制功能。

---

## 10. 发布与版本标记

不要只使用官方版本号标记自己的构建，否则无法判断部署的是官方版本还是定制版本。

推荐格式：

```text
<上游版本>-custom.<自定义修订号>
```

示例：

```text
v0.3.0-custom.1
v0.3.0-custom.2
v0.4.0-custom.1
```

创建发布 tag：

```bash
git checkout main
git pull --ff-only origin main
git status --short --branch
git tag -a v0.3.0-custom.1 -m "release: v0.3.0-custom.1"
git push origin v0.3.0-custom.1
```

每次发布记录：

```text
定制版本号
main commit SHA
对应上游 tag 或 commit SHA
数据库 migration 状态
镜像 tag 与 digest
配置版本
测试和验收结果
已知问题
回滚目标版本
```

生产环境必须部署 tag、完整 commit SHA 或不可变镜像 digest，不要部署含义会变化的 `latest`。

---

## 11. 生产升级和回滚原则

升级前至少备份：

- PostgreSQL 数据库；
- 实际使用的配置文件和环境变量清单；
- JWT、加密密钥及支付回调相关秘密的安全副本；
- 自定义静态资源和挂载数据；
- 当前运行镜像 digest 或二进制；
- 当前数据库 schema/migration 版本。

升级顺序：

1. 在开发环境完成自动化测试；
2. 在预生产环境使用数据库副本演练；
3. 创建自定义发布 tag；
4. 完成生产备份并验证备份可读；
5. 部署固定版本；
6. 执行健康检查和 MaaS 核心验收；
7. 观察错误率、延迟、结算和渠道状态；
8. 确认稳定后再清理旧版本。

回滚时不要只回滚应用而忽略数据库兼容性。如果新 migration 不能被旧应用读取，应恢复升级前数据库备份或执行经过验证的逆向迁移。

---

## 12. 紧急安全修复

如果官方发布需要立即采用的安全修复，但完整升级来不及验证：

1. 从自己的 `main` 创建 `hotfix/*`；
2. 确认安全修复对应的官方 commit；
3. 使用 `git cherry-pick` 只引入明确提交；
4. 运行受影响模块及核心回归测试；
5. 发布新的 custom patch 版本；
6. 后续仍要执行一次完整的官方同步。

示例：

```bash
git checkout main
git pull --ff-only origin main
git checkout -b hotfix/upstream-security-fix
git cherry-pick <官方修复 commit SHA>
```

`cherry-pick` 是紧急措施，不应替代正常上游同步，否则相同提交未来合并时更难判断。

---

## 13. 常见问题与恢复

### 13.1 `git pull` 提示无法快进

不要去掉 `--ff-only` 强行拉取。先检查：

```bash
git fetch origin
git log --oneline --left-right main...origin/main
```

查明本地为什么产生额外提交，再决定通过功能分支、merge 或其他方式处理。

### 13.2 错误地在 main 上修改了文件但尚未提交

创建功能分支接住当前修改：

```bash
git checkout -b feature/<name>
```

确认状态后在该分支继续开发和提交。

### 13.3 merge 冲突解决错误但尚未提交

```bash
git merge --abort
```

然后重新建立同步分支再处理。

### 13.4 已经提交了错误的官方同步

如果提交已经推送或部署，不要改写历史。创建新的修复或回滚提交，并先评估数据库变化。

### 13.5 Fork 落后官方很多版本

不要删除仓库重新复制代码。按第 7 节创建同步分支，分阶段处理冲突。差异过大时可以按模块拆分验证，但最终仍要保留清楚的 Git 历史。

### 13.6 查看某段代码来自官方还是定制

```bash
git log --oneline -- <文件>
git blame <文件>
git diff upstream/main...main -- <文件>
```

---

## 14. 禁止事项

除非已经确认影响并有恢复方案，否则禁止：

```text
直接在生产服务器修改源码
直接在 main 开发
git push --force origin main
git reset --hard upstream/main
git clean -fd
用官方代码整目录覆盖定制代码
批量把冲突全部选择 ours 或 theirs
跳过数据库备份直接升级
把密钥、密码或真实用户数据提交到 Git
把“没有运行的测试”记录为“通过”
```

---

## 15. 合规注意事项

当前仓库根目录 `LICENSE` 为 GNU LGPL v3。项目中文 README 同时包含“无商业授权”提示，并提醒可能涉及上游服务商服务条款风险。

在对外提供商业 MaaS 服务前，应单独完成：

- 对仓库许可证和 README 附加声明的法律评估；
- 对 OpenAI、Anthropic、Google 等上游账号及 API 使用条款的评估；
- 支付、个人信息、日志留存和数据跨境合规评估；
- 密钥管理、权限隔离、审计和数据脱敏检查。

本节仅用于提示工程和运营风险，不构成法律意见。

---

## 16. 快速命令表

### 开始新定制

```bash
cd /Users/james/git/a9/sub2api
git checkout main
git pull --ff-only origin main
git checkout -b feature/<name>
```

### 检查官方更新

```bash
git fetch upstream --prune --tags
git log --oneline main..upstream/main
git rev-list --left-right --count main...upstream/main
```

### 同步官方更新

```bash
git fetch origin --prune
git fetch upstream --prune --tags
git checkout main
git pull --ff-only origin main
git checkout -b sync/upstream-<YYYYMMDD>
git merge --no-ff upstream/main -m "merge: sync upstream main <YYYY-MM-DD>"
make -C backend test-unit
git push -u origin sync/upstream-<YYYYMMDD>
```

### 查看自己的定制与官方差异

```bash
git fetch upstream
git diff --stat upstream/main...main
git log --oneline upstream/main..main
```

### 发布定制版本

```bash
git checkout main
git pull --ff-only origin main
git tag -a <upstream-version>-custom.<N> -m "release: <version>"
git push origin <upstream-version>-custom.<N>
```

---

## 17. 每次同步的完成标准

只有同时满足以下条件，才可以认为一次官方同步完成：

- [ ] 同步发生在独立 `sync/upstream-*` 分支；
- [ ] 已记录上游起止 commit；
- [ ] 所有冲突都按业务语义解决；
- [ ] 后端测试通过；
- [ ] 前端检查和构建通过，或明确记录真实阻塞；
- [ ] 数据库 migration 已评审和演练；
- [ ] MaaS 核心流程已验收；
- [ ] 自定义功能回归通过；
- [ ] 配置变化已记录；
- [ ] 生产备份与回滚方案可执行；
- [ ] PR 已评审并合入 `main`；
- [ ] 已创建可追溯的定制发布版本。

遵守这套流程后，官方更新与定制开发不再是二选一：官方代码通过 `upstream` 持续进入独立同步分支，定制代码通过小型功能分支持续进入自己的 `main`，二者在测试和评审门禁处汇合。
