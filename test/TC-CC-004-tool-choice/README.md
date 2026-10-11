# TC-CC-004：工具选择契约与 prompt cache 命中率

本目录是适配 Sub2API 的 CC004 黑盒测试。它复用 MAAS CC004 的核心覆盖矩阵，
但只依赖 Sub2API 的公开 `POST /v1/chat/completions` 接口。每个矩阵项都在独立
的稳定前缀下发送一条冷请求和若干条完全相同的请求，因此可以同时观察工具语义
和真实返回的 `usage.prompt_tokens_details.cached_tokens`。

## 覆盖矩阵

| Run ID | `tool_choice` | tools | 客户端 | 预期工具语义 |
| --- | --- | --- | --- | --- |
| `CC004-BASE-J/S` | 省略 | 无 | JSON / SSE | 2xx，无 tool calls，建立同模型基线 |
| `CC004-NONE-J/S` | `none` | `lookup_city` | JSON / SSE | 2xx，无 tool calls |
| `CC004-AUTO-TEXT-J/S` | `auto` | `lookup_city` | JSON / SSE | 2xx，可返回普通正文，无 tool calls |
| `CC004-AUTO-TOOL-J/S` | `auto` | `lookup_city` | JSON / SSE | 需要工具的提示实际产生合法 tool call |
| `CC004-REQ-J/S` | `required` | `lookup_city` | JSON / SSE | 2xx，至少一个合法 tool call，`finish_reason=tool_calls` |

`lookup_city` 的 schema 为：

```json
{"type":"object","properties":{"city":{"type":"string"}},"required":["city"],"additionalProperties":false}
```

## 与参考用例相同的异常覆盖

以下项目属于 MAAS 用例中的契约断言；它们需要可控的上游 fixture 或网关诊断，
不能由公开 Sub2API 请求稳定制造。执行 fixture 时应把它们记为失败样本，而不是
跳过后宣称 CC004 完成：

| 异常 | 预期 |
| --- | --- |
| `none` 却返回工具、`required` 只返回正文 | 非 2xx 或明确契约失败，不能伪装成功 |
| arguments 分三帧、ID/name 中途变化、terminal 快照缺 output | 只能拼接合法调用；身份冲突应失败，不能重复追加 |
| 上游 HTTP 400、已开始 SSE 后 error、转换阶段本地 400 | 阶段可定位、无错误后成功终态 |
| 错误中注入 prompt/token canary | 客户端、日志、诊断和计费出口均不得出现原文 |
| assistant `tool_calls` + `role=tool` 回传 | 每个 `tool_call_id` 精确配对并能继续生成 |

本目录 runner 会执行公开客户端可观察的正向矩阵、SSE 身份不变量和第二轮回传；
原始请求重放、上游调用次数、错误阶段、能力 profile/revision 和 canary 全出口
扫描仍需把本报告中的 request ID 与部署侧 fixture/日志合并验收。

runner 默认使用普通 schema；可用 `--strict` 或 `SUB2API_CC004_STRICT=1` 再跑一轮
`strict: true` 变体。多工具、工具结果回传、上游原始请求/日志、故障注入和能力
发布属于网关 fixture 或真实渠道验收，公开客户端不能自行证明这些上游证据；本
runner 会把 follow-up 的精确 `tool_call_id` 保留下来供部署日志对账。

## 执行

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/TC-CC-004-tool-choice/run.py --mode both \
  --report test/TC-CC-004-tool-choice/report.json
```

常用参数：

- `--model` 固定模型；不传时从 `/v1/models` 选择可用模型。
- `--repeats` 每个 Run ID 的请求数，默认 `3`，至少为 `2`；第 1 次是冷请求。
- `--mode json|sse|both` 选择客户端传输模式，默认 `both`。
- `--context-file` 提供有意义且达到目标上游最小缓存前缀的稳定资料；不传使用内置
  可重复 fixture。
- `--verify-tls` 或 `SUB2API_VERIFY_TLS=1` 开启证书校验。

正式验收应固定用户、group、模型、渠道/账号、配置 revision 和多实例缓存身份；
JSON 与 SSE 应使用不同报告，避免互相预热。重复请求的 body（包括 tools、schema、
choice、model、messages 和生成参数）必须保持不变。SSE 必须带
`stream_options.include_usage=true`，并且恰好一个末端 usage chunk 和一个 `[DONE]`。

## 命中率口径

对每个成功且 usage 完整的请求记录 `p_i=prompt_tokens`、`c_i=cached_tokens`，并
校验 `0 <= c_i <= p_i`：

```text
请求命中率 R_req = count(c_i > 0) / 有效 usage 请求数
token 命中率 R_tok = sum(c_i) / sum(p_i)
usage 覆盖率 = 有效 usage 请求数 / HTTP 成功请求数
```

报告同时给出 `all_window`（冷请求 + 重复请求）和 `warm_window`（排除第 1 次）。
HTTP 失败、非法 token 数和缺失/估算 usage 不进入分母，并单独计数。客户端报告
只能证明“Sub2API 返回的 usage 命中”；要宣布真实上游命中，必须用请求 ID、上游
原始 usage、实际账号/模型和计费记录逐条对账。

## 通过与阻塞

- 通过：矩阵中请求均为 2xx；`none`/BASE/auto-text 无工具调用；auto-tool 和
  `required` 产生合法的 function name、唯一非空 call ID 和可解析 arguments；SSE
  分帧可拼接；每个工具的非空 ID 帧数恰好为 1，身份冲突失败，终态完整；每个
  成功请求都有可核对缓存 usage。
- 失败：违反 choice 语义、`required` 只返回正文、工具名/ID/arguments 损坏、
  SSE 缺终态或 HTTP 非 2xx。
- 阻塞：响应成功但没有 `cached_tokens`，或没有权限/余额完成真实请求。阻塞不等
  于缓存未命中。

## 离线单元测试

```bash
python3 test/TC-CC-004-tool-choice/test_cases.py
```

报告不会保存 API Key、Authorization、请求 prompt、工具参数值、响应正文或错误
正文，只保存脱敏的调用结构和统计字段。
