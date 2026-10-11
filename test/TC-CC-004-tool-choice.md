# TC-CC-004：none / auto / required 工具调用契约与 prompt cache 命中率

本用例参考 `maas/test/TC-CC-004-tool-choice.md`，适配 Sub2API 的公开
OpenAI-compatible API。它在 `/v1/chat/completions` 上验证 `tool_choice` 的
`none`、`auto`、`required` 语义、无 tools 基线、JSON/SSE 响应，以及真实 usage
中的 prompt cache 命中率。

测试入口、请求约束、报告字段和判定码见同名目录中的
[README.md](./TC-CC-004-tool-choice/README.md)。

执行入口：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
python3 test/TC-CC-004-tool-choice/run.py --mode both
```

缺失 API Key、健康检查/模型发现失败时返回 `1`；成功响应缺少可核对的
`cached_tokens` 时返回 `2 (BLOCKED)`，不会将缺失值当作未命中。

