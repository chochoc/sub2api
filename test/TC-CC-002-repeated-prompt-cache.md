# TC-CC-002：相同请求重复发送的 prompt cache 命中率

本用例验证 Sub2API 的 `/v1/chat/completions` 在同一个固定用户、模型和缓存身份下，连续收到完全相同的请求时，是否每次都真实调用上游并报告可核对的 `usage.prompt_tokens_details.cached_tokens`。请求命中率和 token 命中率只根据真实 usage 计算，不用响应延迟、响应正文复用或客户端猜测替代缓存证据。

测试步骤、BASE/KEY/AFF 配置对照、JSON/SSE 覆盖、报告字段和判定码见同名目录中的 [README.md](./TC-CC-002-repeated-prompt-cache/README.md)。

执行入口：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_CACHE_MODE=both \
python3 test/TC-CC-002-repeated-prompt-cache/run.py
```

默认每个 session 发送 30 条请求（第 1 条为冷启动，后 29 条完全相同）。没有 API Key、健康检查/模型发现失败或成功响应缺少可核对缓存 usage 时，分别返回失败码或 `2 (BLOCKED)`；缺失值不会被写成 0。
