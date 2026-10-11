# OpenAI 契约测试报告

测试时间：2026-10-03 08:58（Asia/Shanghai）  
目标：`https://127.0.0.1:8443`  
受测模型：`codex-auto-review`（由 `/v1/models` 自动选择）  
声明配置：`SUB2API_EXPECT_POLICY=legacy`，`SUB2API_EXPECT_STOP_MODE=reject`（与部署样例默认值一致）

## 真实部署结果

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 健康检查 | 通过 | `/health` HTTP 200，JSON |
| 鉴权 | 通过 | 缺失 Key 为 401 `API_KEY_REQUIRED`；非法 Key 为 401 `INVALID_API_KEY` |
| 模型发现 | 通过 | `/v1/models` HTTP 200，返回 13 个模型 |
| 重复请求缓存观测 | 部分通过 | 两次相同请求均 200 且有 usage；`cached_tokens` 未返回，不能计算命中率 |
| stop JSON 字符串 | legacy 行为通过 | HTTP 200；停止串仍出现在内容中，strict 未启用 |
| stop JSON 数组 | legacy 行为通过 | HTTP 200；停止串仍出现在内容中，strict 未启用 |
| stop SSE | legacy 行为通过 | HTTP 200，停止串未出现在事件流，`[DONE]` 恰好 1 次 |
| 非法 stop（空串、`[null]`） | legacy 行为通过 | HTTP 200；legacy 不启用 strict 预校验 |
| 非法 max（0、负数） | legacy 行为通过 | HTTP 200；legacy 不启用 strict 预校验 |
| max 边界 1/16/127/128 | 通过 | 均 HTTP 200；本黑盒测试无法观察最终上游字段是否被抬高 |
| tools `none` / `auto` / `required` | 通过 | 均 HTTP 200，调用语义分别符合预期 |
| 指定 function tool | 通过 | HTTP 200，返回的 function 名为 `get_weather` |
| usage 结构 | 通过 | `prompt_tokens + completion_tokens == total_tokens` |
| `/chat/completions` 别名 | 通过 | 重建后 HTTP 200，`Content-Type: application/json` |

测试命令：

```bash
SUB2API_API_KEY='***' SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/openai_contract_http_test.py
```

机器可读明细在 [`openai-contract-report.json`](openai-contract-report.json)。报告只记录 Key 是否配置，不保存 Key；错误正文也没有写入报告。

另行临时启动 `strict/text` 配置进行验收，结果保存在 [`openai-contract-report-strict-text-after-alias.json`](openai-contract-report-strict-text-after-alias.json)：13 个用例全部通过；stop JSON/SSE 截断、非法 stop/max 拒绝、tools、usage、别名均通过；Codex 路径对显式 `max_completion_tokens` 返回方案规定的 `unsupported_parameter`。

## 结论与限制

当前部署实例已恢复 `legacy/reject`，并确实执行了真实 ChatGPT 订阅上游请求。legacy 下 stop 串保留属于预期旧行为；临时 strict/text 验收确认新增 stop 截断、非法参数拒绝、工具路径和 `/chat/completions` 别名均可用。缓存请求有 usage，但没有 `cached_tokens`，C2 命中率标记为不可计算；没有据此推断缓存改善。

黑盒请求无法证明最终出站的 `max_output_tokens` 原值、协议分支、账户切换、预留释放、计费幂等和上游 stop/max body。上述项目仍需受控 mock/服务端日志或集成测试验证，不能由 HTTP 200 推断通过。

## 本地实现回归

`run_local_regression.sh` 已执行并通过，输出保存在 `local-regression.log`：

- `internal/pkg/apicompat`：通过；
- `internal/config`：通过；
- 方案涉及的 `internal/service` 定向测试：通过。

本地回归只证明源码转换、策略和 stop 文本接线，不替代真实上游验收。别名修复后，strict/text 真实黑盒 13 个用例全部通过；legacy 结果保留在历史报告中，legacy 下 stop/max 旧行为按配置预期保留。
