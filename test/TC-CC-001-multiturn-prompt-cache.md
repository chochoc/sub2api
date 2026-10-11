# TC-CC-001：多轮对话的 prompt cache 命中率

本用例验证 Sub2API 的 `/v1/chat/completions` 多轮对话是否保留可复用的输入前缀，并根据真实返回的 `usage.prompt_tokens_details.cached_tokens` 计算请求命中率和 token 命中率。测试过程、约束、报告口径和运行命令见同名目录中的 [README.md](./TC-CC-001-multiturn-prompt-cache/README.md)。

执行入口：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
python3 test/TC-CC-001-multiturn-prompt-cache/run.py
```

测试不会将 API Key、请求正文或响应正文写入报告。没有可核对的缓存 usage 时，结果标记为 `BLOCKED`，不会把缺失值当作未命中。
