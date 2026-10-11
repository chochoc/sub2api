# gpt-5.6-terra 五类问题专项复测报告

测试目标：`https://127.0.0.1:8443`  
受测模型：`gpt-5.6-terra`  
部署配置：`legacy/reject`

## 结果

| 问题 | 实测结果 | 结论 |
| --- | --- | --- |
| C1 多轮缓存 | 1 次初始请求 + 10 轮追加，11/11 成功；usage 11/11，`cached_tokens` 0/11 | 命中率 N/A，无法确认 10% / 9.54% |
| C2 重复缓存 | 1 次预热 + 20 次重复，21/21 成功；usage 21/21，`cached_tokens` 0/21 | 命中率 N/A，无法确认 10% / 9.86% |
| S1 stop JSON 字符串 | HTTP 200，但停止串仍在返回内容中，`finish_reason=stop` | **失败** |
| S1 stop JSON 数组 | HTTP 200，但停止串仍在返回内容中，`finish_reason=stop` | **失败** |
| S1 stop 首字符 | HTTP 200，但停止字符仍在返回内容中，`finish_reason=stop` | **失败** |
| S1 stop SSE | HTTP 200，停止串未出现在事件流，`[DONE]` 1 次 | 通过 |
| T1 `tool_choice=none` | HTTP 200，无 tool call | 通过 |
| T1 `tool_choice=auto` | HTTP 200，1 个 tool call | 通过 |
| T1 `tool_choice=required` | HTTP 200，1 个 tool call | 通过 |
| L1 `max_completion_tokens=1` | HTTP 200，`finish_reason=stop`；prompt 24、completion 1207、total 1231 | **失败** |

共 10 个聚合用例，4 个失败（3 个非流式 stop、1 个输出上限终态）。完整逐样本结果见 [`issue-regression-report-gpt-5.6-terra.json`](issue-regression-report-gpt-5.6-terra.json)。

缓存指标保持 N/A，没有把未报告的 `cached_tokens` 当作 0，也没有据此计算命中率。

## 重跑命令

```bash
cd sub2api
SUB2API_API_KEY='你的测试 Key' \
SUB2API_BASE_URL='https://127.0.0.1:8443' \
SUB2API_MODEL='gpt-5.6-terra' \
SUB2API_ISSUE_REPORT='test/issue-regression-report-gpt-5.6-terra.json' \
python3 test/issue_regression_cases.py
```
