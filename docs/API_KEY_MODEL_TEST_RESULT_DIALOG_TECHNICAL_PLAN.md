# API Key 模型测试：结果详情弹窗技术方案

> 版本：v1.0。日期：2026-11-01。状态：已实现，通过自动化、embed 构建及本地浏览器验收；PR #6 已推送，Actions 已恢复并开始运行；最终 CI/合并尚待确认。本文先以“待实施”落盘，再修改代码，以下按真实证据更新状态。
>
> 基线：`02cb2d8148b3a7c4a046fe0571dde812f3e6356e`。遵循 [定制与同步手册](SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md)、[开发规范](DEVELOPMENT_RULES.md)；基础功能见 [模型测试方案](API_KEY_MODEL_TEST_TECHNICAL_PLAN.md)。

## 1. 问题与目标

当前 `KeyModelTestModal.vue` 点击“查看结果”只设置 `detailId`，`ModelTestResult` 固定渲染于表格与分页下方。模型较多或主弹窗已滚动时，使用者无法立即看到详情。单项测试还会自动选择详情。

改为点击行操作后，在主弹窗上方打开独立详情弹窗。用户已确认仅点击“查看结果”时打开，单项/批量测试结束不自动打开。保留测试方式、队列、计费、结果数据、图片预算和安全诊断契约。

## 2. 交互约定

| 行为 | 目标结果 |
| --- | --- |
| 点击有结果行的“查看结果” | 打开该模型的详情，不发送 API 请求 |
| 测试开始、完成或失败 | 更新行状态，不自动打开详情 |
| 详情关闭按钮或 Escape | 仅关闭顶层详情，主弹窗保持打开 |
| 点击详情遮罩 | 不关闭，不穿透到主弹窗 |
| 关闭详情 | 保留筛选、分页、选择、主弹窗滚动、结果及图片预览；恢复发起按钮焦点 |
| 批量执行中查看/关闭详情 | 队列继续，详情读取最新结果状态 |
| 刷新目录、切换 Key、关闭主弹窗 | 清除详情选择，继续沿用现有会话/预览清理 |
| 页面卸载 | 详情随组件卸载，现有请求和图片资源按原流程释放 |

详情使用现有 `BaseDialog`，尺寸 `wide`、z-index 60；主弹窗仍为 `extra-wide`、z-index 50。标题为“测试结果详情”，正文保留原始模型 ID。底部按钮为“关闭详情”。中英文同步，长内容在弹窗内部滚动，支持明暗主题及 390px 窄屏。

复用公共组件的顶层 Escape、焦点进入/恢复与多弹窗滚动锁，不改公共组件。主弹窗在详情显示时不处理 Escape。详情关闭不调用测试会话的 `close` 或 `stop`。

## 3. 组件接线与数据生命周期

修改集中在 `frontend/src/features/key-model-test/components/KeyModelTestModal.vue`：

1. 移除分页后的内联详情，新增同级详情 `BaseDialog`，复用 `ModelTestResult`。
2. `openDetails(modelId)` 只接受当前会话存在的结果；选中 ID 决定详情内容。
3. 详情通过 computed 读取 `state.results`，图片通过现有 `state.previews` 查找；不复制完整响应、不重建 Blob URL、不发网关请求。
4. `closeDetails()` 仅清空选中 ID。结果组件按模型 ID 设置 key，避免切换模型沿用局部图片错误状态。
5. 移除 `prepare` 的自动选中逻辑，明确在刷新、主弹窗关闭、show/keyId 变化时关闭详情。模型目录重置继续清空选中 ID。

`ModelTestResult` 的请求/返回模型、协议端点、时间、HTTP 状态、request ID、usage、错误、文本、图片、复制诊断与使用记录链接保持现有行为。图片被预算淘汰时仍展示“预览已释放”。Key 明文与认证头不进入新增状态或文案。

没有公开 API、DTO、数据库、后端、插件、依赖或功能开关变化。

## 4. 文案与文档同步

中英文 `keyModelTest` 文案新增 `detailsTitle` 和 `closeDetails`。不更改“查看结果”行按钮文案。

同步原模型测试方案 §9、架构指南 §1/§7.3.1/§11，以及 [本地验收记录](API_KEY_MODEL_TEST_LOCAL_ACCEPTANCE.md)。架构索引逐文件记录实际修改的组件、文案和测试。方案状态与本地部署证据分开维护，不能将设计说明当作验证通过。

## 5. 验证方案

### 5.1 组件与真实弹窗集成

- 测试结束后不自动显示详情；点击后显示正确模型，主弹窗内不再包含结果详情。
- 查看/关闭详情不增加网关或 Key API 调用，保留选择、筛选和分页。
- 刷新、换 Key、关闭主弹窗后没有旧详情；无结果 ID 不打开详情。
- 查看运行中结果会更新；关闭详情不取消批量，后续请求仍正常执行。
- 文本、失败错误、图片、预览释放及诊断复制保持正常。
- 使用真实 `BaseDialog` 验证层级、Escape 只关闭顶层、焦点返回行按钮，以及父弹窗仍显示时保持 body 滚动锁；不能只使用 stub 证明这些行为。

### 5.2 必需检查

从仓库根执行，使用项目要求的工具链，不修改锁文件或全局配置：

```bash
make test-frontend
pnpm --dir frontend exec vitest run src/features/key-model-test src/views/user/__tests__/KeysView.spec.ts src/components/common/__tests__/BaseDialog.escape.spec.ts src/components/common/__tests__/BaseDialog.scrollLock.spec.ts
pnpm --dir frontend run check:i18n
VITE_KEY_MODEL_TEST_ENABLED=true make build-frontend
(cd backend && go test -tags embed ./internal/web)
make check-architecture-index
git diff --check
# 暂存代码和架构指南后
python3 tools/check_architecture_index.py --staged
```

本次没有 Go 业务、公共 API 客户端、路由或 store 改动，不机械扩展为全套 Go/前端测试。额外测试须针对实际失败或风险。

### 5.3 本地部署与浏览器验收

沿用本机隔离部署，先构建 `.next` embed 程序，显式开启 `VITE_KEY_MODEL_TEST_ENABLED=true`。替换前生成数据库 dump，停止本实例并备份完整持久化数据、配置、凭据、证书和旧程序。只操作本地回环实例，不操作生产。

使用临时专用用户/分组/Key 和本地模拟上游，检查实际嵌入 UI 的中英文、明暗主题、390px 窄屏、长文本滚动、图片、失败详情、查看不增加生成请求、父滚动位置、顶层 Escape、焦点与批量继续执行。清理临时资源后保留本地服务，记录实际版本、源码 SHA、摘要及结果。未进行真实供应商付费调用时明确标注未验证。

## 6. 分支、合入与回滚

从更新后的干净 main 创建 `fix/key-model-test-result-dialog`，先落盘本文，再修改组件、测试和文案。完成本地检查与部署后更新验证状态，推送到 origin，创建到 main 的 PR，按手册完成适用 CI/评审后合并；不直接推 main、不改写历史、不向 upstream 推送。

实际推送代码并创建 PR #6 后，GitHub 未为自动 push/pull_request 事件创建运行或 check suite，工作流状态为 active，仓库权限 API 返回 enabled=true。为执行原有检查，给既有 CI 与 Security Scan 补充 `workflow_dispatch`，原触发、job 内容与权限保持不变；对功能分支手动运行，不能把无检查结果当作通过。此项属于检查触发能力，不改变产品构建开关。实际手动触发 CI 和 Security Scan 均返回 HTTP 422：`Actions has been disabled for this repository`。再次保存现有 enabled=true 设置、启用既有 workflow 后仍被拒绝，未产生运行记录；未绕过门禁合并。所有者随后确认已恢复；重新手动触发成功创建 CI `41263412745` 和安全扫描 `41263412742`。首轮执行暴露架构脚本仅支持 push/PR，因此补齐 workflow_dispatch：从默认分支共同祖先检查全部功能差异；在默认分支上检查最后提交，缺失历史仍失败。真实临时仓库回归确认未登记改动会被拒绝，不跳过门禁。最终按最新提交的实际运行结果更新。

代码回滚还原本次组件/文案修改；本地程序回滚使用备份的已验证产物。没有本次新增迁移，但仍需确认备份与运行基线匹配。恢复旧版会恢复列表底部的详情展示方式。

## 7. 实施与验证记录

执行环境：macOS、Node v24.19.0、pnpm 9.15.9。Node 24 本地检查不替代 Node 20 的 CI。

| 检查 | 结果 |
| --- | --- |
| `make test-frontend` | lint、类型检查及 30 文件 / 578 项 critical 测试通过 |
| 受影响模块、KeysView 与 BaseDialog 定向检查 | 11 文件 / 131 项通过，包含 16 项详情交互测试 |
| `check:i18n` | 双语完整性检查通过 |
| 开启功能的前端构建 | 通过；有既有大 chunk / Browserslist 提示，未修改依赖或关闭检查 |
| 架构索引与 diff | 代码提交的工作区/暂存区检查通过；PR 共覆盖 8 个代码路径（含两个仅增加手动触发的 workflow 及架构门禁脚本/测试） |
| embed 构建与 `go test -tags embed ./internal/web` | 通过，当前本机运行版本 `0.2.19-custom.3-result-dialog-local` |
| 实际 Chrome + 本地 HTTPS + 模拟上游 | 中英文、明暗主题、390px 详情布局、长结果、关闭/焦点/滚动锁、图片、错误、批量实时更新通过，pageerror=0 |
| 本地 HTTPS smoke、权限及清理 | 通过；资源数恢复到测试前，清理失败 0 |
| GitHub CI / Security Scan | 初始 422 阻塞；所有者恢复后创建实际运行，待最新提交全部通过后合并 |

真实弹窗集成测试仅 stub 过渡动画与不相关展示控件，保留 BaseDialog 的真实 Teleport、事件、焦点和滚动锁逻辑；部署后的真实 Chrome 已验证动画与布局。

实际构建源码为干净提交 `3800e8c079a83f6f5737ac35ea132e960a105919`；后续 CI 触发入口及文档提交没有进入该二进制，也未改变产品代码。访问、摘要、备份、完整场景与限制见 [本地验收 §8](API_KEY_MODEL_TEST_LOCAL_ACCEPTANCE.md#8-结果详情弹窗部署与验收2026-11-01)。未验证真实供应商或生产发布。
