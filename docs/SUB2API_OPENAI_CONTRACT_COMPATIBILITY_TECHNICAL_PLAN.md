# Sub2API OpenAI 契约兼容性技术方案

> 版本：v2.0 · 2026-09-29 代码复核版。
> 代码基线：`b4a9452a68d494c85ee3a1da9bfc0128c2d1da9a`；本次刷新 `origin` 后，本地基线与 `origin/main` 一致。本文的“当前”指该代码快照，不代表已核对所有线上部署或再次合并官方上游。
> 状态：文档修订；已有能力依据源码及现有测试核对，剩余实施项尚未开发、业务测试与真实上游复测尚未执行。
> 规范：[架构与修改指南](ARCHITECTURE_AND_MODIFICATION_GUIDE.md)、[开发规范](DEVELOPMENT_RULES.md)、[Composite 分组](COMPOSITE_GROUPS.md)、[定制与上游同步指南](SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md)。

## 1. 修订结论与范围

旧版针对早期订阅 OAuth → Codex Responses → Chat Completions 链路制定了五项补丁。当前项目已有多种账号、协议分流、稳定缓存身份、工具转换和 usage 处理，不能继续按旧版五项缺陷全部未解决来实施。

本方案继续以 `/v1/chat/completions` 及其 `/chat/completions` 别名为主要入口，重点解决实际转换分支的字段丢失、参数能力和结果语义。订阅业务仍使用现有 Codex 凭据链路；项目同时存在的 API Key、原生 Chat、Anthropic 等分支必须分别判断，不能将某一业务部署的凭据限制描述成全项目架构。

### 1.1 旧问题逐项处置

| 旧编号 | 旧判断 | 当前代码结论 | 修订后的工作 |
| --- | --- | --- | --- |
| 1 多轮缓存 | 客户端不传会话标识，缓存 key 就为空，需要新增派生 | **已有实现，旧根因失效**。Chat → Responses 对支持的模型派生 key；调度也有独立的内容种子兜底。见 §3 | 移出新增开发清单，保留身份稳定、隔离、映射模型与 usage 回归；不再改 `ExtractSessionID` 承担通用派生 |
| 2 重复请求缓存 | 没有本地响应缓存导致约 10% 命中，需要 dedup 保证接近 100% | **撤销该缺陷定义与补丁**。当前主路径没有旧方案设想的整响应缓存，但这不构成 OpenAI 契约缺陷；稳定 prompt cache 与回传能力已存在 | 使用上游真实 cached tokens 评估；取消本地响应重放及人为写满 cached tokens |
| 3 stop | Chat → Responses 未处理 stop | **转换分支仍有缺口**。DTO 有 `Stop`，转换器不读取；原生 Chat 分支须单独判断 | 增加分支能力检查；优先原生映射，Responses 分支可选受限文本截断，其他不支持的组合明确拒绝。见 §4 |
| 4 工具调用 400 | none/auto/required 全失败，且一定是上游拒绝 tools | **旧实测未在当前版本复现，归因失效**。已有 strict 默认值、工具形状规范化、名称别名及调用 ID 处理；本地也能返回 400 | 复用既有诊断，按出站分支复测；另处理仍存在的指定工具被静默降为 auto 的风险。见 §5 |
| 5 token 上限/finish_reason | 统一用本地 tokenizer 截断即可完全兼容 | **上限缺口仍在，但结束原因映射已存在**。Codex 转换主动删除上限；Chat → Responses 还会把正数小上限抬至 128 | 支持路径保留原值，不支持路径明确能力边界；保留既有 incomplete → length 映射，不重写真实 usage。见 §6 |

旧版“请求命中率 10%、token 命中率 9.54%/9.86%”只保留为历史问题背景，缺少本基线的测试时间、账号/模型、样本和原始统计，**不得用作当前故障证据或验收阈值**。用户已反馈新版缓存命中问题得到解决；源码确认相关机制存在，本次没有重新测量线上命中率。

### 1.2 本次明确撤销的设计

- 新增 `StablePromptCacheKey` 并塞入 `ExtractSessionID`：与已有分层派生重复，还会扩大到其他调用路径。
- 将整响应放进 Redis，并在重放时设置 `cached_tokens = prompt_tokens`：改变生成语义，混淆上游输入缓存与网关重放，也遗漏租户、鉴权、计费和保留期设计。
- 用可见文本 tokenizer 将 `completion_tokens` 重写为上限或截断后的计数：不能覆盖推理、工具及不可见 token，会污染结算和下游计费。
- 默认删除 tools/strict、把 function 工具改成 custom 工具、将所有 tools 400 统一改成 501：没有当前失败证据，也不保证语义等价。
- 五项新开关全部默认开启，以及虚构已存在的 `cache.RedisCache`、`SUB2API_*` 配置：当前并无这些方案接口，实施应沿用本仓库 service/repository 和 Viper 边界。

## 2. 当前链路与能力边界

路径均相对仓库根目录；链接从本文所在的 `docs/` 解析。定位以函数名为主，避免旧版本行号失效。

### 2.1 入站、路由和转发

```text
API Key 鉴权 → 客户端原始模型白名单 → Composite 解析/模型改写
  → 按具体平台选择 handler → 审核/配额/调度/并发
  → 按账号原生协议、端点能力和请求形状选择转发
      ├─ Codex 协议：Chat → Responses → Codex transform → 上游 SSE
      ├─ API Key Responses：Chat → Responses → 默认或自定义 Base URL
      ├─ 原生 Chat：按分支修改请求后转发 Chat Completions
      ├─ 原生 Anthropic：现有 Chat → Responses → Anthropic 链
      └─ Grok / OpenCode Go / 其他平台：各自已有分流
  → JSON 聚合或 SSE 转换 → 实际 usage → 既有异步记录与幂等结算
```

主要证据：

| 位置 | 当前职责 |
| --- | --- |
| [routes/gateway.go](../backend/internal/server/routes/gateway.go) · `RegisterGatewayRoutes` | 网关及别名；模型白名单在 Composite 改写之前；Chat 入口按平台选 handler |
| [handler/openai_chat_completions.go](../backend/internal/handler/openai_chat_completions.go) · `ChatCompletions` | 请求/模型/stream/service tier 校验、审核、计费资格、会话、账户调度与失败处理 |
| [service/openai_gateway_chat_completions.go](../backend/internal/service/openai_gateway_chat_completions.go) · `forwardAsChatCompletions` | 账号协议分流、Responses 形状兼容、模型映射、缓存 key 注入、Codex 转换与回程 |
| [openai_compat/upstream_capability.go](../backend/internal/pkg/openai_compat/upstream_capability.go) · `ResolveResponsesSupport` | `openai_responses_mode` 与探测结果；强制 Responses、强制 Chat、自动模式 |
| [service/openai_gateway_forward.go](../backend/internal/service/openai_gateway_forward.go) · `buildUpstreamRequest` | 按凭据选择 Codex、默认 Platform API 或经校验的自定义 Base URL；认证与会话头 |
| [service/openai_gateway_chat_completions_raw.go](../backend/internal/service/openai_gateway_chat_completions_raw.go) · `forwardAsRawChatCompletions` | 原生 Chat 分支，有自身模型/策略/平台处理，不能简单称为完全不修改 body |
| [service/openai_gateway_chat_completions_anthropic_native.go](../backend/internal/service/openai_gateway_chat_completions_anthropic_native.go) · `forwardChatCompletionsViaNativeAnthropic` | Chat → Responses → Anthropic，不能因为最终是 Anthropic 就假设 Chat stop 已保留 |

API Key 并非必定发往 `api.openai.com/v1/responses`。账号配置、端点探测、CN 协议和 OpenCode Go 原生协议都会改变路径；能力未知且 Responses 端点不受支持时还存在原生 Chat fallback。对任何参数的检查必须覆盖**最终实际转发分支及 fallback**。

`isResponsesShape` 表示 `/chat/completions` 收到有 `input`、无 `messages` 的请求。这条路径保留 Responses 形状，不应套用标准 Chat 的缓存派生或文本截断策略。原生 `/responses`、WebSocket、媒体接口也不能因共享函数而被自动纳入本方案。

### 2.2 Composite 不变量

遵守 [COMPOSITE_GROUPS.md](COMPOSITE_GROUPS.md) 的路由、具体平台归属与端点限制；其中“显式路由后直接内置检测”的概览省略了当前代码的账号模型归属解析。以 [composite_route_resolver.go](../backend/internal/service/composite_route_resolver.go) · `Resolve` 和架构指南 §4.3 为准：

1. 显式规则 → 已装配的账号模型归属 → 内置检测；归属歧义拒绝，归属查询失败仅对可识别模型允许检测兜底。
2. 显式规则按 exact、具体 endpoint、最长 prefix、较小 priority、较小 route ID 决胜，禁用规则不参与。
3. Chat 使用 `chat_completions` 路由域，保留原始模型白名单检查；分清公共模型、路由模型、账号上游模型和计费模型。
4. 参数能力判断在既有路由/调度边界内进行；不能为满足 stop/token 上限擅自跨平台换账号或绕过套餐、配额和渠道价格。
5. 具体平台继续贯穿计费、Ops 和报表。组合别名本身不创建价格或能力记录。

## 3. 缓存：保留已有能力，改为回归与观测

### 3.1 当前实现

| 环节 | 实际行为与源码 |
| --- | --- |
| 显式标识 | `ExtractSessionID` 在 [openai_gateway_scheduling.go](../backend/internal/service/openai_gateway_scheduling.go) 读取会话 header/body key；它返回空并不代表后续不会派生 |
| 调度粘性 | 同文件 `GenerateSessionHash` 缺显式标识时调用 [openai_content_session_seed.go](../backend/internal/service/openai_content_session_seed.go) · `deriveOpenAIContentSessionSeed`；支持 Chat/Responses 的模型、工具、开头 system/developer、instructions、首条 user 等种子 |
| 上游 prompt key | [openai_compat_prompt_cache_key.go](../backend/internal/service/openai_compat_prompt_cache_key.go) · `deriveCompatPromptCacheKey` 使用映射模型、reasoning effort、tool choice、tools/functions、system、首条 user 派生稳定 key；后续普通 user/assistant 轮次不会直接进入该种子 |
| 生效条件 | `forwardAsChatCompletions` 仅在无显式 key、标准 Chat 形状、Codex 协议或 OpenAI API Key、且 `shouldAutoInjectPromptCacheKeyForCompat` 命中时派生；当前含受支持 GPT-5/Codex 与 GPT-6 模型拼写，并非全部模型 |
| 隔离 | 自动派生的 OpenAI API Key body key 经 `isolateOpenAISessionID`；Codex 上游会话头使用 [openai_codex_account_identity.go](../backend/internal/service/openai_codex_account_identity.go) · `isolateOpenAIUpstreamSessionID`，加入 API Key 和可用的凭据身份命名空间；显式 key、body key、最终 header 不是同一个处理规则，不宣称所有字段都被统一改写 |
| usage | [responses_to_chatcompletions.go](../backend/internal/pkg/apicompat/responses_to_chatcompletions.go) · `chatUsageFromResponsesUsage` 保留缓存读/写、推理等明细；Chat SSE 回程当前强制 `IncludeUsage=true`，包括客户端未请求 stream options 的情况 |
| 计费 | [openai_gateway_usage.go](../backend/internal/service/openai_gateway_usage.go) · `RecordUsage` 分别处理普通输入、缓存读、缓存创建和输出，复用既有结算链路 |

调度 seed 与上游 prompt key 是不同用途，输入集合也不同。不能为了“统一 key”删除其中一个或改成全请求哈希；若发现 developer/instructions 等输入的行为差异，先在各自真实调用点复现，再决定是否需要定向修正。

源码测试证据（本次仅阅读，未执行）：

- [openai_compat_prompt_cache_key_test.go](../backend/internal/service/openai_compat_prompt_cache_key_test.go)：`StableAcrossLaterTurns`、`DiffersAcrossSessions`、映射模型族。
- [openai_gateway_chat_completions_test.go](../backend/internal/service/openai_gateway_chat_completions_test.go)：`APIKeyAutoDerivesStableIsolatedPromptCacheKey`、`ResponsesShapeDoesNotAutoDerivePromptCacheKey`、`StreamsUsageWithoutClientStreamOptions`、顶层终态 usage 和断连继续收集 usage。
- [openai_content_session_seed_test.go](../backend/internal/service/openai_content_session_seed_test.go)、[openai_gateway_service_session_isolation_test.go](../backend/internal/service/openai_gateway_service_session_isolation_test.go)、[openai_codex_account_identity_test.go](../backend/internal/service/openai_codex_account_identity_test.go)：内容种子与会话隔离。

### 3.2 更新后的验收方法

缓存不再设“超过旧版 10%”或“重复请求接近 100%”硬门槛。Prompt caching 复用的是输入前缀计算，仍会生成新回复；key 和相同请求都不保证命中。官方公开 API 的说明也不能直接当作 ChatGPT 内部 Codex 后端的 TTL 或最低长度承诺。依据：[OpenAI Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)。

线上若需复测，固定代码版本、账号协议、映射后的模型、API Key、前缀内容和请求节奏，区分冷启动、预热后重复请求与多轮追加；记录账号切换、失败请求和 usage 缺失，避免将它们混入一个百分比。

- 请求命中率：有效 usage 样本中 `cached_tokens > 0` 的请求数 / 有效样本数。
- token 命中率：同一有效样本集的 `sum(cached_tokens) / sum(prompt_tokens)`；分母为零时记为不可计算。
- 单列 usage 缺失数量；缓存写入 tokens 不计为缓存读取命中；显式零值与未报告字段分别保留观测状态。
- 结构验收检查同一稳定前缀的派生值、显式标识优先级、跨 API Key 隔离，以及上游 → 下游 → 用量记录的值是否一致。

本方案不新增整响应缓存。未来若另有业务需求，应单独设计租户/Key/分组隔离、权限撤销、随机输出、工具、模型版本、计费、TTL 和数据保留；不得用 OpenAI `cached_tokens` 表示网关本地响应重放。

## 4. stop：解决实际转换丢失，明确模拟范围

### 4.1 当前缺口

[types.go](../backend/internal/pkg/apicompat/types.go) 的 `ChatCompletionsRequest.Stop` 为 `json.RawMessage`，但 [chatcompletions_to_responses.go](../backend/internal/pkg/apicompat/chatcompletions_to_responses.go) · `ChatCompletionsToResponses` 不读取该字段，`ResponsesRequest` 也无 stop。当前两个 Chat 回程处理函数没有 stop 扫描器，因此该转换路径会丢失 stop。

原生 Chat 路径不经过上述 DTO 重建，是否支持由最终模型/上游决定；经 Responses 中转的原生 Anthropic 分支同样需要补显式映射。不能将这一缺陷推广为“所有入口都不支持 stop”。

### 4.2 拟实施行为

按 §8 的兼容策略灰度启用，先解析并保留原始 stop 选项，随后依据最终协议选择：

| 最终路径 | 严格策略下的处理 |
| --- | --- |
| 原生 Chat | 保留字段，遵守已确认的模型能力和上游错误；不重复截断 |
| 原生 Anthropic 的 Chat 桥 | 从原始 Chat 请求显式解析并写入 `AnthropicRequest.StopSeqs`，避免经 Responses 中转丢失；验证上游与回程终态 |
| Codex / API Key Responses 桥 | 默认拒绝不支持的 stop；仅显式启用网关文本模拟模式时接入下述扫描器 |
| Responses 形状兼容、其他平台/协议 | 使用其原有契约；扩展须独立验证，不能自动套用 |

解析接受字符串、字符串数组或 null/缺省；最多 4 条。空字符串、非字符串元素等无效输入返回 OpenAI 风格 400；空数组按无约束处理并固定测试。前述形状、数量及输出不含停止串的语义参考 [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)，具体模型支持范围另行判断。

**可选文本模拟模式是网关扩展，不能承诺停止上游生成或节约上游费用。** 首期仅支持单 choice、普通文本输出、无可执行 tools/functions 的请求；structured output、音频、多 choice 或工具组合在模拟模式下明确拒绝，不得截断工具 JSON、推理字段或破坏 schema。无工具/工具禁用状态须按实际解析结果判定，不能只检查 `tools` 长度。

实现要求：

1. 纯扫描逻辑放 `apicompat`；service 在选定路径后传入请求级选项。通用 Responses → Chat 转换器默认保持现有行为，避免影响 Grok 等复用方。
2. 非流式对普通 `message.content` 按最早匹配位置截断，排除停止串；未命中保持原终态。命中仅覆盖正常文本结束为 `stop`，不把 failed/refusal/content_filter 伪装成成功。
3. 流式在已解析的文本 delta 上扫描，暂存可能构成停止串的后缀，支持跨 chunk、重叠串和 UTF-8；按累计输出位置裁定，不能按“先做 token 再做 stop”的固定顺序。
4. 命中后停止下发文本，继续在既有有界超时/资源生命周期内读终态 usage；收到有效终态后只写一次 finish、usage 和 `[DONE]`。不要提前写 `[DONE]` 后再补 usage。
5. 上游读取失败/缺失终态仍保留错误语义和已得到的 usage，不执行跨账号重放；客户端断开后复用现有取消/收尾机制，不能新增无界后台 drain。
6. 下游和 `OpenAIForwardResult.Usage` 继续报告上游真实用量，不按截断后字符串重算。实际费用可能包含被网关隐藏的后续生成，须在启用说明中写明。

## 5. tools：复用已实现兼容，按证据定位剩余错误

### 5.1 已有能力与仍需关注的分支

- `convertChatToolsToResponses` 已将 function 定义转换到顶层 name/parameters，并用 `defaultStrictFalse` 在缺省时明确发送 `strict:false`，显式 true/false 保留；已有 `ToolStrict` 等测试。
- [openai_codex_transform.go](../backend/internal/service/openai_codex_transform.go) 已处理旧 functions/function_call、嵌套 function 定义、保留名称别名、tool choice 和续链调用 ID。`none/auto/required` 字符串在 `normalizeCodexToolChoice` 中不被改写。
- [openai_codex_transform_test.go](../backend/internal/service/openai_codex_transform_test.go) 已覆盖 known/legacy function choice、allowed_tools、调用 ID 配对等；这些源码测试不能替代真实账号的成功证据。
- **仍有语义风险**：缺失或未声明的指定 function、未知工具类型在 `normalizeCodexToolChoice` 中可能降为 `auto`；已有 `DowngradesMissingFunctionToolChoice` / `DowngradesUnknownToolChoice` 测试明确记录了当前行为。严格策略应在该变换前拒绝无效限制，不得静默放宽调用者约束。
- **本地 400 确实存在**：handler 的模型/service tier 校验、Codex transform 错误，以及 raw Chat 对特定 GPT-6 Sol/Luna 推理+工具组合的能力拒绝。不能从“收到 400”推断请求已到上游。

### 5.2 拟实施诊断和修复流程

1. 复用 [openai_gateway_cc_pipeline.go](../backend/internal/service/openai_gateway_cc_pipeline.go) · `readOpenAIUpstreamError`、`failoverOpenAIUpstreamHTTPError` 与既有 Ops 错误链。已有读取、响应体恢复和消息净化，不另建一套读响应流程。
2. 用合成 fixture 覆盖 none/auto/required、指定函数、legacy function_call、strict 缺省/true/false、多工具与 tool result 续链；同时检查实际发送的 URL、JSON 形状、调用 ID 和恢复后的工具名称。
3. 若当前版本仍失败，记录来源层（入口/转换/上游 HTTP/上游流终态）、具体平台、账号类型、协议、映射模型、HTTP status、受控 type/code 与请求关联 ID。工具名称、arguments、schema、正文和凭据不写普通日志；任意上游 message 不能仅截断后就视为安全。
4. 现有错误路径有受 `LogUpstreamErrorBody` 控制的 detail 捕获，**本方案不以开启它作为诊断前提，也不宣称旧链路已经实现全量正文脱敏**。新增诊断使用字段白名单并验证无敏感回显。
5. 严格策略先验证指定工具存在且形状正确，非法组合返回 OpenAI 风格 400；只对确实不支持的能力给出稳定、可操作的错误。不要将所有上游 400 改成 501，不要把 none 改成“删除所有工具历史”。
6. 只有失败 fixture 能证明转换问题时才修改相应转换器；响应缓存、function→custom 改写和通用 schema 删字段不属于默认修复。

真实上游验收按支持能力判定成功或明确拒绝；不能要求所有模型上的所有 tool_choice 一律 2xx。若历史故障无法复现，记录具体版本和测试组合，关闭该故障项，而非为旧假设新增代码。

## 6. token 上限与 finish_reason：保留原值、拒绝虚假保证

### 6.1 源码确认的三件不同事情

1. `ChatCompletionsToResponses` 优先取 `max_completion_tokens`，其次 `max_tokens`；仅正数被转换，并统一用 `minMaxOutputTokens = 128` 抬高较小值。因此请求 16 可能实际发送 128。这是当前需要处理的精度问题，非单纯缺一个结束原因映射。
2. `applyCodexOAuthTransformWithOptions` 的 `openAICodexOAuthUnsupportedFields` 已含 `max_output_tokens` / `max_completion_tokens`，主动移除它们。旧版“准备新增 strip”的任务已经失效；代码本身不能证明远端永久不支持，但当前链路明确不会传递上限。
3. `responsesStatusToChatFinishReason` 和流式 `resToChatHandleCompleted` 已将 `incomplete + max_output_tokens` 映射成 `length`，并保留 content_filter/tool_calls。已有 [chatcompletions_responses_test.go](../backend/internal/pkg/apicompat/chatcompletions_responses_test.go) 的 `Incomplete`、`ResponseDoneIncomplete` 测试；不能把默认 stop 直接认定为映射 bug。

公开契约的 `max_completion_tokens` 包括可见输出和推理 token；输出用量还可能包含不可见格式 token。本地对字符串计数无法严格模拟。依据：[OpenAI Counting tokens](https://developers.openai.com/api/docs/guides/token-counting)。仓库虽有 `tiktoken-go/tokenizer v0.8.0`，依赖存在不等于能准确控制这些上游 token。

### 6.2 拟实施方案

| 最终路径 | 严格策略下的目标行为 |
| --- | --- |
| 已确认支持限制的原生 Chat | 按该模型支持的参数发送原始合法值，保留原生 finish_reason/usage |
| API Key Responses 桥 | 将合法上限原值映射到 max_output_tokens；若上游有最低值约束，明确拒绝低于约束的值，不能静默提高 |
| Codex 协议桥 | 在删除参数前检测显式上限，返回 400 `invalid_request_error`，指出当前路径不能严格执行该限制；不新增官方 Key、不自动跨平台改路由 |
| 经中转的原生 Anthropic | 在该分支按原始请求恢复合法 max_tokens，保留模型限制与 thinking 预算校验；不让 Responses 的 128 floor 无条件影响它 |

实施时给 Chat 转换添加显式选项或分支专用转换入口，让旧调用方保持兼容；不要直接修改全局 `minMaxOutputTokens`，其还被 Anthropic 等转换器及测试使用。解析需区分缺省/null、零、负数、非整数和溢出；两个字段同时存在时保持明确优先级，但任何非法字段不得被另一个字段掩盖。

保留现有“上游真实终态 → finish_reason”的映射。自然结束、工具调用、内容过滤和错误不能因为本地计数恰好达到阈值就被改为 length；`completion_tokens` 不要求等于请求上限。

如未来确需可见文本长度限制，应作为**单独命名、默认关闭的网关扩展**设计，说明不限制推理/上游成本、不代替 max_completion_tokens。本版不把它列为完全兼容的解决方案，也不再设计 stop/max_tokens 的统一强制后处理管线。

## 7. 实施边界与文件所有权

以下是后续代码任务的落点，本次文档修订不创建这些新代码或配置。

| 工作 | 拟落点与复用要求 |
| --- | --- |
| 请求约束解析 | 在 `backend/internal/pkg/apicompat/` 新增独立纯解析/校验文件及测试；保留 presence、RawMessage、原始限制与错误字段，不依赖 Redis/Gin |
| 能力和策略选择 | 在 `backend/internal/service/` 添加小型策略 helper，由 `forwardAsChatCompletions` 及实际受影响分支调用；重试/fallback 每次都按最终分支核对 |
| stop 文本扫描 | `apicompat` 独立扫描器；在 `handleChatStreamingResponse` / `handleChatBufferedStreamingResponse` 接线，明确请求级启用，不改变共享转换器默认语义 |
| token 原值与 Anthropic 映射 | `chatcompletions_to_responses.go` 的显式转换选项和原生 Anthropic 桥接点；保留旧调用方行为后再逐项迁移 |
| 工具限制验证 | 复用现有 Codex tools/choice 转换与名称映射；先校验后变换，不另建通用工具协议 |
| 诊断 | 复用 `openai_gateway_cc_pipeline.go`、既有日志/Ops 和 `backend/internal/util/logredact/`；如需新分类器只扩充稳定字段 |
| 配置 | `backend/internal/config/config.go` 与 `deploy/config.example.yaml`、`deploy/.env.example` 同步；不直接从业务函数读取环境变量 |
| 计费与并发 | 复用 handler → `OpenAIForwardResult` → usage worker → 既有幂等结算；不新增独立扣费或缓存命中免鉴权通道 |

不新增数据库表、Redis 整响应缓存、前端开关页面或依赖。若实施时证明确实需要，应另行扩展范围、迁移/配置说明与对应 Gate，不能由本表推断已经获得产品支持。

## 8. 配置、兼容与回滚设计

旧版 `SUB2API_RESPONSE_CACHE_*`、`SUB2API_STABLE_CACHE_KEY_ENABLED`、`SUB2API_CLIENT_MAX_TOKENS_ENABLED` 等名称从部署方案中撤销，**当前项目并不因此获得这些环境变量**。

后续建议增加以下配置字段，均为拟议名称，必须完成 config 类型、Viper 默认值/环境绑定、样例及测试后才可使用：

| 拟议配置键 | 默认值 | 行为 |
| --- | --- | --- |
| `gateway.openai_chat_contract.policy` | `legacy` | `legacy` 保持当前转换；`strict` 对本文已定义的不支持限制明确返回错误，支持路径保留原值 |
| `gateway.openai_chat_contract.stop_mode` | `reject` | strict 下 `reject` 拒绝无原生支持的 stop；`text` 仅开放 §4 的受限模拟；原生路径仍优先原生映射 |

非法枚举在启动校验时失败；配置按进程启动读取，需要重启，不假称热更新。strict 的范围是本文覆盖的字段与分支，不能宣传为完整 OpenAI 全协议认证；legacy 状态也不能标为缺口已修复。

先在隔离实例/指定受测账号池启用 strict，验证客户端错误处理后再扩大发布。回滚时将 policy 恢复 legacy 并重启，必要时回退已验证 commit；这样会恢复原有参数丢失限制，运维记录应明确。stop_mode 仅控制新模拟，不关闭既有缓存身份与 usage 能力。本方案无数据库迁移，仍应按同步指南保留部署版本与配置快照。

## 9. 测试与验收

### 9.1 后续实现必须补充或保留的矩阵

| 范围 | 可观察结果与必测边界 |
| --- | --- |
| 缓存回归 | 稳定前缀多轮同派生 key；显式 header/body 优先级；映射模型；自动派生 API Key 隔离；Codex 换账号会话头；Responses 形状不误注入；cached/cache-write/reasoning usage 不丢失 |
| stop 原生映射 | raw Chat 保留 stop；原生 Anthropic 桥不经 Responses 丢失；上游明确不支持时保留可操作错误 |
| stop 模拟 | 单/多停止串、首字符命中、跨 chunk、重叠、UTF-8、结尾残留、未命中；JSON 与任意分块 SSE 输出一致；非法/工具/schema/多 choice 组合先拒绝 |
| token 参数 | 1/16/127/128、正常大值、零/负数/null/缺省/非整数/溢出、两字段优先级；支持路径实际出站不抬高；Codex strict 拒绝且上游调用次数为零 |
| 工具 | none/auto/required、指定 function、allowed_tools、legacy、strict true/false、名称别名还原、并行调用 ID/结果关联；未声明 choice strict 返回 400，不能变 auto |
| 终态与计费 | incomplete→length、自然 stop、tool_calls、content_filter、failed、缺终态；停止下发后仍收 usage；上游真实用量不改写；部分失败按既有结算规则处理且不重复扣费 |
| 断连与重试 | 文本输出后不换账号重放；stop 命中后读超时；客户端断开；响应体/并发槽位回收；usage/finish/[DONE] 各一次且有序 |
| 分支与安全 | Codex、API Key Responses、raw fallback、Anthropic 桥、Responses 形状；Composite 原始模型准入及具体平台计费；日志含恶意错误回显仍不泄露凭据/正文 |
| 配置与回滚 | 缺省 legacy、strict/reject、strict/text、非法枚举、关闭后原行为、现有缓存不受影响 |

fixture 必须是合成/脱敏数据；不能用降低断言、删除原生分支用例或统一允许错误来获得通过。修改旧 floor/choice 测试时，要增加 strict/legacy 分别验证的用例并说明语义变化。

### 9.2 命令与 Gate

以下从 **sub2api 仓库根目录**执行；Go 模块在 `backend/`，不沿用旧方案的本机版本目录或根目录 `go test ./backend/...`。

本次只有说明文档，按开发规范 §17 执行路径/链接/命令核对、Markdown 结构检查和 `git diff --check`，无需运行业务测试。目标文档首次纳入仓库时，必须同步架构指南 §1 的入口。

后续代码实施的定向回归入口（不是本次已运行结果）：

```bash
(cd backend && go test ./internal/pkg/apicompat -count=1)
(cd backend && go test -tags=unit ./internal/service -run 'Test(ForwardAsChatCompletions|HandleChatStreamingResponse|ShouldAutoInjectPromptCacheKeyForCompat|DeriveCompatPromptCacheKey|ApplyCodexOAuthTransform|NormalizeCodexToolChoice)' -count=1)
```

代码合入还须完成开发规范要求的 Go Gate、受影响网关/计费集成和架构索引：

```bash
make -C backend test-unit
make -C backend test
make -C backend build
make -C backend test-integration
make check-architecture-index
# 仅在暂存本次明确路径后执行
python3 tools/check_architecture_index.py --staged
```

使用 `backend/go.mod` 及 CI 要求的 Go 工具链，不能降版本绕过失败。定向 mock 测试只能证明本地契约；真实 Codex、第三方 API、数据库与 Redis 验收须记录各自环境和结果，不能用编译成功替代。未影响前端时无需机械执行前端全套。

### 9.3 完成标准

- [ ] 已有缓存能力无回退；如需实测，记录有效样本/缺失 usage/冷暖状态，不设置虚构命中率门槛。
- [ ] strict 下 stop 要么原生保留、要么按明确启用的文本模拟生效、要么在转发前明确拒绝；不得静默丢弃。
- [ ] 支持 token 上限的分支发送原值；不支持分支不伪装成严格执行；真实 usage 和正确终态映射保留。
- [ ] tools 历史故障已有当前复现或关闭记录；已验证组合正常，非法/不支持组合有明确错误且无静默降级。
- [ ] SSE 终态、断连、重试、幂等结算与 Composite 不变量通过受影响回归。
- [ ] 配置默认值、灰度、回滚、实际 Gate 和架构变更索引完整；未执行项明确标注。

## 10. 实施顺序、风险与文档维护

### 10.1 实施顺序

| 阶段 | 产出 | 依赖与结束条件 |
| --- | --- | --- |
| P0 当前基线复核 | 本文 v2.0、源码与测试入口、旧方案处置表 | 本次文档任务；不等于剩余缺口已修复 |
| P1 请求约束与分支策略 | strict/legacy 策略、参数解析、工具 choice 校验、失败 fixture | 先完成能力/不支持错误契约和配置回归 |
| P2 原生语义修复 | token 原值、Anthropic stop/max 映射、Responses 终态回归 | 依赖 P1；不全局改写共享转换器或 usage |
| P3 可选 stop 文本模拟 | 纯扫描器、JSON/SSE 接线、usage 收尾 | 依赖 P1/P2 的策略和终态约束；混合输出不承诺支持 |
| P4 真实上游复测与灰度 | 缓存/工具复测报告、部署配置、回滚记录 | 无新证据时不扩增缓存或工具补丁；受影响 Gate 通过后才扩大启用 |

### 10.2 主要风险

| 风险 | 处理 |
| --- | --- |
| strict 使过去静默接受的请求变成 400 | 默认 legacy，明确灰度和客户端迁移说明；严格契约验收必须在 strict 下完成 |
| 共享函数影响其他平台或入站形状 | 请求级显式选项，记录最终分支；覆盖 fallback、Grok 复用和原生 Anthropic 桥 |
| 本地 stop 后上游继续生成、终态迟到 | 明示模拟与费用边界，有界收尾；不提前伪造 usage 或完成事件 |
| 上游模型能力和 token 最小值变化 | 按账号/模型/协议复测，原值转发或明确拒绝，不凭旧版本数字永久硬编码 |
| 诊断读取改变错误/重试流程或泄露正文 | 复用既有响应体读取与 Ops 路径，新增结构化字段白名单，测试敏感回显 |

### 10.3 本次验证记录与 Git 流程

本次修改范围为本文和架构指南的文档入口/变更记录，未实施后端功能、配置或数据库变更。源码、现有测试、公开契约和本地路径已核对；Markdown 结构、链接和 diff 检查的实际结果在架构指南本次索引中记录。Go/前端业务测试、真实上游缓存命中和工具调用复测未运行，§9.3 保持未验收。

按 [同步指南](SUB2API_CUSTOMIZATION_AND_UPSTREAM_SYNC_GUIDE.md) 在 `feature/openai-contract-plan-refresh` 分支维护；不在 main 直接开发，不推 upstream，不 rebase/强推共享 main。提交时只暂存本次明确的文档路径；需要推送时推送 origin 功能分支，经 PR 评审与对应 Gate 后合入 main。本次核对没有执行官方上游合并。

后续实现每阶段同步本文的状态、源码证据、实际验证和限制，并按开发规范 §19 在架构指南 §11 新增文件级索引。本文替代 v1.0 的补丁清单和错误语义；不再引用 maas 的规范、本机 `sub2api-0.2.8` 路径或不存在的 deliverables 落点。
