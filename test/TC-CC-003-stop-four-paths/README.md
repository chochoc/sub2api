# TC-CC-003：stop 四路径与 prompt cache 命中率

本目录是适配 Sub2API 的 CC003 黑盒测试。测试入口通过公开的
`POST /v1/chat/completions` 验证 JSON/SSE 客户端响应中的 stop 截断、终态、
`[DONE]` 和 usage，同时按真实返回的 `usage.prompt_tokens_details.cached_tokens`
计算请求命中率和 token 命中率。

四个 Run ID 与参考用例保持一致：

| Run ID | 客户端响应 | 上游模式标签 | 说明 |
| --- | --- | --- | --- |
| `CC003-JJ` | JSON | JSON | 非流式客户端请求 |
| `CC003-SJ` | JSON | SSE | 上游强制 SSE 的部署/fixture |
| `CC003-SS` | SSE | SSE | 流式客户端请求 |
| `CC003-JS` | SSE | JSON | 上游强制 JSON 的部署/fixture |

Sub2API 的公开响应只能证明客户端侧模式，不能证明实际渠道上游模式。runner
会保留上游模式标签并写入 `upstream_mode_verified=false`；要完成 JJ/SJ/SS/JS
的上游证据，必须同时保存网关诊断或上游桩日志，不能把标签当作命中证据。

## 执行

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/TC-CC-003-stop-four-paths/run.py \
  --boundary all \
  --report test/TC-CC-003-stop-four-paths/report.json
```

`--repeats` 默认每条路径发送 3 次相同请求，第 1 次作为冷启动，后续请求用于
缓存命中率。正式验收应使用稳定的 `--context-file`，内容大小应满足目标上游
的最小缓存前缀要求；JSON 与 SSE 应在独立 session/报告中执行，避免互相预热。

没有 API Key、健康检查或模型发现失败返回 `1`；HTTP/SSE/stop 断言失败返回
`1`；成功响应缺少可核对的 cached usage 返回 `2 (BLOCKED)`。响应正文、请求
prompt 和 API Key 不写入报告。

离线单元测试：

```bash
python3 test/TC-CC-003-stop-four-paths/test_cases.py
```

## 覆盖内容

runner 的 `--boundary all` 覆盖 stop 在首字符、末尾、跨 chunk、未命中、中文/emoji、
重叠 stop（`['abc', 'b']`）和最多四个非空字符串时的最早匹配 oracle，并验证
`stop=null` 与省略 stop 不截断；每个启用 stop 的成功 SSE 响应要求恰好一个终态
usage chunk 和一个 `[DONE]`。启用 stop 时 JSON/SSE 正文必须为 stop 之前的内容，
不能出现 `<EN`、`<END>` 或后文 `secret`，finish reason 必须是 `stop`。

`--boundary all` 还会发送类型错误、空字符串、空数组、超过四个 stop 和超长 stop，
要求明确返回 HTTP 400。工具 arguments、隐藏推理以及异常 EOF/重复终态/取消/超限
等项目不能由公开黑盒稳定注入，应在上游 fixture 或网关集成环境中执行并附脱敏
断言；本 runner 不会把未执行项目报告成通过。

## 命中率口径

对每个成功且 usage 完整的请求记录 `p_i=prompt_tokens`、`c_i=cached_tokens`，
校验 `0 <= c_i <= p_i`：

```text
请求命中率 = count(c_i > 0) / 有效 usage 请求数
token 命中率 = sum(c_i) / sum(p_i)
usage 覆盖率 = 有效 usage 请求数 / HTTP 成功请求数
```

缺失/估算 usage、HTTP 失败和非法 token 数不进入分母，并单独记录。没有上游
原始 usage 或请求 ID 对账时，结论只能写“Sub2API 客户端报告的命中率”；不能
宣布真实上游缓存命中。

## 通过标准

- 四条客户端路径均无 stop 半串和后文泄漏，正文/finish reason 等价；SSE 无重复终态、usage 或 `[DONE]`。
- 每条成功路径 usage 完整且缓存字段合法，报告给出请求命中率、token 命中率和覆盖率。
- 上游模式、原始 usage/账单、错误/取消/超限和原失败请求的证据来自网关/fixture，且与客户端响应逐条对账。
