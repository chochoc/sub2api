# TC-CC-001：多轮对话的 prompt cache 命中率

本目录是适配 Sub2API 的 CC001 黑盒测试。它通过 `/v1/chat/completions` 发起 1 次冷启动请求和 10 次追加请求，每次把上一次真实返回的 assistant 内容原样放回下一次 `messages`，观察 Sub2API 返回的 usage 中 `prompt_tokens_details.cached_tokens`。

## 执行

先准备一个有余额、固定用户和固定模型的 Sub2API API Key：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/TC-CC-001-multiturn-prompt-cache/run.py
```

默认执行 JSON；要分别验证流式末端 usage，可执行：

```bash
SUB2API_API_KEY='你的测试 Key' \
SUB2API_CACHE_MODE=both \
python3 test/TC-CC-001-multiturn-prompt-cache/run.py \
  --report test/TC-CC-001-multiturn-prompt-cache/report.json
```

参数也可以通过命令行传入：`--model` 固定模型，`--rounds` 调整追加轮数，`--interval-ms` 控制请求间隔，`--context-file` 使用真实的稳定参考资料，`--verify-tls` 启用证书校验。没有 API Key、健康检查失败或模型发现失败会直接退出；成功响应缺少可核对的缓存 usage 时退出码为 `2 (BLOCKED)`。

脚本只在报告中保存请求状态、耗时、响应类型、token 数和命中率，不保存 API Key、Authorization、system/user prompt、assistant 回复或错误正文。默认报告为本目录的 `report.json`。

## 测试步骤与约束

1. 固定用户、group、模型、渠道/账号和有效参数；多实例部署应确认缓存身份密钥一致。测试前记录 Sub2API commit、配置 revision 和时间。
2. 首次请求使用稳定、有意义的参考前缀。默认内置前缀用于可重复冒烟；正式验收应通过 `SUB2API_CACHE_CONTEXT_FILE` 提供满足目标上游最小缓存前缀的 8～16 KiB 资料，不要用随机填充。
3. 同一 session 保持 system、model、生成参数和历史顺序不变，只在末尾添加新 user 消息，并把上一轮实际 assistant 回复原样加入。JSON 与 SSE 应使用不同的 session/report，避免互相预热。
4. SSE 请求强制 `stream_options.include_usage=true`，必须看到唯一 `[DONE]`，并从末端 usage chunk 取值。没有 usage 或缓存字段的成功请求不能当作未命中。
5. 正式验收可在 BASE（无显式稳定 key）、KEY（稳定 key）和 AFF（稳定 key + 亲和性）配置下各执行 3 轮；每轮为 3 个独立 session × 10 次追加，并单独记录 JSON/SSE。脚本负责单 session 快速复测，配置切换、原失败请求重放和上游日志对账需由部署环境完成。

## 命中率口径

对每个成功且 usage 完整的请求记录 `p_i=prompt_tokens`、`c_i=cached_tokens`，并校验 `0 <= c_i <= p_i`：

```text
请求命中率 R_req = count(c_i > 0) / 有效 usage 请求数
token 命中率 R_tok = sum(c_i) / sum(p_i)
usage 覆盖率 = 有效 usage 请求数 / HTTP 成功请求数
```

报告同时给出全窗口（冷启动 + 10 次追加）和预热窗口（第 2～11 次请求）。缺失/估算 usage、HTTP 失败和非法 token 数不进入分母，并单独计数。只有客户端 Chat usage 时，结论只能写“Sub2API 客户端报告命中”；要宣布真实上游命中，还需用请求 ID 或脱敏时间线与上游 Responses 原始 usage、实际账号/模型和计费记录逐条对账。

## 结果判定

- `0`：所有请求成功，usage 覆盖完整，命中率可计算；是否达到业务阈值由报告中的 R_req/R_tok 判断。
- `1`：HTTP、SSE 终态或多轮续接失败。
- `2`：环境阻塞，或成功响应没有完整的可核对 `cached_tokens`，因此不能宣布命中率达标。

`test_cases.py` 是不访问网络的公式和 SSE 解析单元测试：

```bash
python3 -m unittest test/TC-CC-001-multiturn-prompt-cache/test_cases.py
```
