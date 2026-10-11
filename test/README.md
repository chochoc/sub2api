# Sub2API OpenAI 契约黑盒测试

`openai_contract_http_test.py` 对已部署的 Sub2API 实例执行真实 HTTPS 请求，按技术方案 §9 覆盖：

- `/health`、`/v1/models` 与缺失/非法 Bearer Key；
- `/v1/chat/completions` 的 JSON、SSE 和未版本化 `/chat/completions` 别名；
- `stop` 字符串/数组、SSE 终态、非法 stop 形状；
- `max_completion_tokens` 的 1/16/127/128 边界及非法 0/负数；
- 工具选择 `none`、`auto`、`required` 和指定 function；
- usage 加法一致性与重复请求的 `cached_tokens` 观测。

工具选择与缓存命中率专项见 [TC-CC-004](./TC-CC-004-tool-choice.md)，覆盖
`none`、`auto`、`required`、JSON/SSE、工具调用回传和真实 usage 命中率。

测试只使用 Python 标准库，不把 API Key 或完整响应正文写入报告。Key 通过环境变量传入：

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/openai_contract_http_test.py
```

报告默认写入 `test/openai-contract-report.json`。如果 `/v1/models` 返回 `INSUFFICIENT_BALANCE`，真实上游用例会标记为 `BLOCKED` 并跳过；补充余额后重复命令即可继续。`SUB2API_EXPECT_POLICY` 和 `SUB2API_EXPECT_STOP_MODE` 分别用于声明受测实例的 `legacy/strict` 与 `reject/text` 配置，默认按部署样例的 `legacy/reject` 解释结果。测试失败会保留机器可读记录并以非零状态退出，便于 CI 或人工复测定位。

本次报告按 `legacy/reject` 运行：legacy 下 JSON stop 和非法参数的实际行为会记录但不冒充 strict 通过；唯一失败是 `/chat/completions` 返回前端 HTML。SSE stop、工具选择、usage 结构和有效 token 边界通过。需要验收 strict 时设置 `SUB2API_EXPECT_POLICY=strict` 后重新运行。详见 `TEST_REPORT.md` 与 `openai-contract-report.json`。

本目录不保存生产响应正文、凭据或抓包数据。

本地实现回归可用以下命令执行，结果写入 `local-regression.log`：

```bash
test/run_local_regression.sh
```
