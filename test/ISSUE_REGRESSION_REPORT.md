# 五类问题专项复测报告

测试时间：2026-10-03（Asia/Shanghai）  
目标：`https://127.0.0.1:8443`  
受测模型：`codex-auto-review`  
运行配置：恢复后的 `legacy/reject`

## 结果

| 问题 | 实测结果 | 结论 |
| --- | --- | --- |
| C1 多轮缓存 | 1 次初始请求 + 10 轮追加，11/11 成功；usage 11/11，但 `cached_tokens` 0/11 | 命中率 N/A，不能确认或复现 10% / 9.54% |
| C2 重复缓存 | 1 次预热 + 20 次重复，21/21 成功；usage 21/21，但 `cached_tokens` 0/21 | 命中率 N/A，不能确认或复现 10% / 9.86% |
| S1 stop JSON 字符串 | HTTP 200，但停止串仍在返回内容中 | **失败** |
| S1 stop JSON 数组 | HTTP 200，但停止串仍在返回内容中 | **失败** |
| S1 stop 首字符 | HTTP 200，但停止字符仍在返回内容中 | **失败** |
| S1 stop SSE | HTTP 200，停止串未出现在事件流，`[DONE]` 1 次 | 通过 |
| T1 `tool_choice=none` | HTTP 200，无 tool call | 通过 |
| T1 `tool_choice=auto` | HTTP 200，1 个合法 tool call | 通过 |
| T1 `tool_choice=required` | HTTP 200，1 个合法 tool call | 通过 |
| L1 `max_completion_tokens=1` | HTTP 200，`finish_reason=stop`，不是期望的 `length`；usage 为 prompt 24、completion 1054、total 1078 | **失败** |

缓存指标没有用 0 填充：上游未报告 `cached_tokens`，所以请求命中率和 token 命中率均保持 N/A。完整逐样本数据见 [`issue-regression-report.json`](issue-regression-report.json)。

## 可重复命令

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
python3 test/issue_regression_cases.py
```

脚本只写请求状态、usage presence、缓存字段和终态，不写入 Key 或响应正文。当前服务已恢复并保持运行在 `legacy/reject`。
