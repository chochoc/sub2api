# TC-CC-003：stop 四路径与 prompt cache 命中率

本用例参考 `maas/test/TC-CC-003-stop-four-paths.md`，适配 Sub2API 的公开
OpenAI-compatible API。它验证 stop 在 JSON/SSE 客户端路径上的截断与终态完整性，
并记录真实 usage 中的 `cached_tokens` 以计算缓存命中率。

详细步骤、四路径矩阵、边界/异常限制、命中率口径和执行命令见同名目录的
[README.md](./TC-CC-003-stop-four-paths/README.md)。执行入口：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
python3 test/TC-CC-003-stop-four-paths/run.py --boundary all
```

没有完整上游诊断或 fixture 证据时，只能报告 Sub2API 客户端观察结果，不能将
上游模式或真实上游缓存命中宣称为已验证。
