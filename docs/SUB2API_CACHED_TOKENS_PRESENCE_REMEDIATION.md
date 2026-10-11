# `cached_tokens` 缺失修复方案

> 状态：已实现协议 presence 修复，并在重建本机隔离服务后完成 CC002 JSON/SSE 复测。
> 适用范围：OpenAI Responses → Chat Completions 的 JSON/SSE usage 回程。

## 1. 问题与证据

修复前的 CC002 在固定模型、固定前缀和串行重复请求下观察到：所有请求均为 HTTP 200，但 JSON session 有 2 条、SSE session 有 1 条成功响应没有 `usage.prompt_tokens_details.cached_tokens`。命中请求能够返回非零缓存 token，因此问题不是请求鉴权、模型路由或上游整体不可用。

现有转换链路把 `input_tokens_details` 的所有字段解码为整数。`promptDetailsFromResponses` 在所有细分为零时返回 `nil`，`ChatTokenDetails.cached_tokens` 又使用 `omitempty`。当上游明确报告 `cached_tokens: 0` 时，网关会把“明确未命中”变成“字段不存在”。这会使 CC002 无法计算有效 usage 覆盖率，也会让下游级联代理丢失上游的 presence 证据。

## 2. 目标和边界

目标：

- 上游明确返回 `cached_tokens: 0` 时，Chat JSON 和终态 SSE usage 必须保留该字段。
- 上游返回非零 `cached_tokens` 时，保持现有值、计费和命中统计不变。
- 上游完全没有 `cached_tokens` 时，继续保持缺失；网关不得根据 `prompt_tokens`、延迟、请求序号或缓存 key 推断为 0。
- 反向 Chat → Responses 转换保留该 presence，避免再次丢失。

非目标：

- 不新增整响应缓存，不修改 prompt cache key、调度亲和性或重试策略。
- 不为缺失字段填充 0，不把缺失 usage 计入 CC002 命中率分母。
- 不修改 `CacheReadInputTokens` 的计费数值；presence 只影响协议字段的可观察性。

## 3. 实现

### 3.1 Presence 标记

`ResponsesInputTokensDetails` 增加内部 `CachedTokensPresent` 标记，并提供自定义 JSON 编解码：

- 解析对象时仅依据 JSON key 是否存在设置标记，`0` 和缺失严格区分。
- 序列化时，只有标记为 true 或数值非零才输出 `cached_tokens`。
- 其他输入 token 明细字段沿用原来的零值省略规则。

`ChatTokenDetails` 使用同样的内部标记和自定义 JSON 编解码，保证 `prompt_tokens_details: {"cached_tokens":0}` 能从网关返回，并能在下一跳 Chat JSON 解码时恢复 presence。

### 3.2 转换链路

```text
上游 Responses usage
  → ResponsesUsage.UnmarshalJSON（记录 cached_tokens presence）
  → promptDetailsFromResponses（保留显式零）
  → ResponsesEventToChatChunks / ResponsesToChatCompletions
  → ChatTokenDetails.MarshalJSON（输出显式零）
  → 客户端 JSON 或 SSE 终态 usage
```

反向 `ChatUsageToResponsesUsage` 在 Chat usage 带有 presence 时恢复 `ResponsesInputTokensDetails`，保证多级代理不会在下一跳丢失字段。

内部 `OpenAIUsage.CacheReadInputTokens` 仍然只保存数值。显式零和缺失在计费上均为 0，但只有显式零可作为“上游报告了缓存读取桶”的协议证据；计费不会因为该修复改变。

## 4. 语义矩阵

| 上游输入 | 网关 Chat usage | CC002 统计 | 计费 |
| --- | --- | --- | --- |
| `cached_tokens: 0` | 输出 `cached_tokens: 0` | 有效未命中样本 | cache read = 0 |
| `cached_tokens: N > 0` | 输出 N | 有效命中样本 | 按 N 进入既有 cache-read 桶 |
| 无 `cached_tokens` 且无其他明细 | 不输出该字段 | usage 缺失，仍不进入分母 | 按已知真实 usage 处理 |
| `cached_tokens` 非法/负数 | 沿现有解析和错误路径处理 | 不伪造成 0 | 不新增扣费路径 |

因此，该修复解决的是网关转换造成的字段丢失；如果上游本身完全不报告该字段，CC002 仍应报告 usage 不完整，而不是把缺失伪装成缓存未命中。

## 5. 回归测试

新增/更新的 `internal/pkg/apicompat` 测试覆盖：

- Responses JSON 显式 `cached_tokens: 0` → Chat JSON 保留字段。
- Responses SSE 终态显式零 → Chat usage chunk 保留字段。
- Chat JSON 解码 → Responses round-trip 保留显式零。
- 上游完全没有缓存明细时，网关不生成 `cached_tokens`。
- 既有非零缓存、cache-write 和 reasoning 明细测试继续通过。

定向命令：

```bash
(cd backend && go test ./internal/pkg/apicompat -count=1)
(cd backend && go test ./internal/service -run 'Test(CopyOpenAIUsage|.*CachedTokens|.*Usage)' -count=1)
```

部署后的 CC002 复测已完成：JSON/SSE 各 30 条请求全部 HTTP 200，usage coverage 均为 `30/30 (100%)`，显式零值已被识别为有效未命中；SSE 每条均有一个 `[DONE]`。本轮 JSON/SSE warm request hit rate 均为 `28/29 (96.55%)`，token hit rate 分别约 `64.44%` 和 `64.39%`，低于 80% 工程目标，说明剩余问题是上游缓存命中覆盖率而非 `cached_tokens` 字段缺失。报告位置为 `test/TC-CC-002-repeated-prompt-cache/report.json`；后续复测仍应单列显式零、非零和真正缺失三类样本。

## 6. 发布、回滚与限制

该改动无数据库迁移、无新增配置、无新的外部依赖。发布前必须完成 Go Gate、架构索引 Gate 和重建服务后的 CC002 复测。若回归发现兼容性问题，可回退到上一个已验证构建；回退会恢复旧的显式零字段丢失行为，但不会改变 prompt cache key 或计费算法。

本方案不能保证上游一定提供缓存明细，也不能据此宣布上游 prompt cache 命中率达标。最终验收仍以真实上游 usage 的字段 presence、`cached_tokens <= prompt_tokens`、JSON/SSE 终态完整性和既有计费记录一致性为准。
