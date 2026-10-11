# TC-CC-002：相同请求重复发送的 prompt cache 命中率

本目录是适配 Sub2API 的 CC002 黑盒测试。它为每个 session 生成一个隔离的稳定参考前缀，然后发送 30 次完全相同的 Chat Completions 请求。第 1 次用于预热，后 29 次用于观察重复请求是否命中输入前缀缓存。JSON 和 SSE 使用独立 session；SSE 从末端 usage chunk 读取缓存字段。

## 执行

先准备一个有余额、固定用户和固定模型的 Sub2API API Key：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/TC-CC-002-repeated-prompt-cache/run.py
```

默认执行 JSON。要同时覆盖 JSON 和流式末端 usage：

```bash
SUB2API_API_KEY='你的测试 Key' \
SUB2API_CACHE_MODE=both \
python3 test/TC-CC-002-repeated-prompt-cache/run.py \
  --report test/TC-CC-002-repeated-prompt-cache/report.json
```

常用参数：`--model` 固定模型，`--requests` 调整每个 session 的请求数（也接受兼容别名 `--rounds`），`--interval-ms` 控制间隔，`--context-file` 指定满足目标上游最小缓存前缀的真实资料，`--verify-tls` 启用证书校验。请求数至少为 2，正式验收应保持默认的 30 条。默认报告写入本目录的 `report.json`。

脚本不会把 API Key、Authorization、system/user prompt、响应正文或错误正文写入报告，只保存请求状态、耗时、响应类型、usage 中的 token 字段和聚合命中率。

## 与 MAAS CC002 的对应关系

MAAS 用例的 `CC002-ORIG`、`CC002-BASE`、`CC002-KEY`、`CC002-AFF` 和 `CC002-FAILOVER` 是部署配置与上游证据矩阵，不能由 Sub2API 客户端 API 自行切换。使用本 runner 时，应在相同模型、用户、渠道/账号和有效参数下分别运行：

1. `BASE`：关闭显式稳定 cache key；
2. `KEY`：启用稳定 cache key；
3. `AFF`：启用稳定 cache key 和账号/渠道亲和性；
4. `FAILOVER`：单独进行并发或渠道/账号切换，不与串行重复请求合并统计；
5. `ORIG`：按原失败请求与原配置、修订配置各重放一次，使用同一套真实上游 usage 对账。

每种配置至少执行 3 轮，每轮使用新的 session 前缀；JSON、SSE 分开记录。固定配置 revision、commit、模型、账号/渠道和请求间隔，确认多实例使用相同缓存身份密钥。上游日志或请求 ID 应能证明每个成功响应都有对应真实调用；客户端报告本身只能证明“Sub2API 返回的 usage 命中”，不能单独宣布上游命中。

## 请求和缓存约束

- 同一 session 的 model、messages、工具顺序和生成参数完全不变；请求正文逐条相同。
- 每个 session 的 system 前缀含不可逆 run ID，避免不同 session 互相预热；正式验收可用 `SUB2API_CACHE_CONTEXT_FILE` 提供稳定、有意义且达到上游最小缓存长度的资料。
- SSE 强制 `stream_options.include_usage=true`，要求恰好一个 `[DONE]`；JSON 和 SSE 不共享 session。
- 不能复用历史完整回复、改写 `cached_tokens`、把缺失 usage 当作 0，或把并发/故障切换样本混入串行窗口。
- 合法 usage 必须满足 `prompt_tokens >= 0`、`cached_tokens` 为整数且 `0 <= cached_tokens <= prompt_tokens`。

## 命中率口径

对每个 HTTP 成功且 usage 完整的请求记录 `p_i=prompt_tokens`、`c_i=cached_tokens`：

```text
请求命中率 R_req = count(c_i > 0) / 有效 usage 请求数
token 命中率 R_tok = sum(c_i) / sum(p_i)
usage 覆盖率 = 有效 usage 请求数 / HTTP 成功请求数
```

报告同时给出 `all_window`（冷启动 + 重复请求）和 `warm_window`（排除第 1 条）。缺失/估算 usage、HTTP 失败和非法 token 数不进入分母，并单独计数。30 条含冷启动的窗口即使第 1 条未命中，理论请求命中率也不应被要求为 100%；工程目标“重复请求命中率至少 90%、加权 token 命中率至少 80%”应作为目标单独记录，不能冒充 MAAS 原用例阈值。

## 判定码

- `0`：所有请求成功，usage 覆盖完整，JSON/SSE 的命中率可计算。
- `1`：HTTP 失败或 SSE 终态失败。
- `2`：环境阻塞，或成功响应没有完整的可核对 `cached_tokens`，因此不能宣布命中率达标。

不访问网络的公式和 SSE 解析单元测试：

```bash
python3 test/TC-CC-002-repeated-prompt-cache/test_cases.py
```
