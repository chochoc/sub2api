package service

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/Wei-Shaw/sub2api/internal/pkg/apicompat"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"github.com/tidwall/gjson"
)

func chatTextFixture(deltas []string, status, reason string) string {
	var out strings.Builder
	for _, delta := range deltas {
		event, _ := json.Marshal(map[string]any{"type": "response.output_text.delta", "delta": delta})
		fmt.Fprintf(&out, "data: %s\n\n", event)
	}
	response := map[string]any{"id": "r", "status": status, "model": "gpt-5", "output": []any{map[string]any{"type": "message", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": strings.Join(deltas, "")}}}}, "usage": map[string]any{"input_tokens": 2048, "output_tokens": 17, "input_tokens_details": map[string]any{"cached_tokens": 1024}}}
	if reason != "" {
		response["incomplete_details"] = map[string]string{"reason": reason}
	}
	event, _ := json.Marshal(map[string]any{"type": "response." + status, "response": response})
	fmt.Fprintf(&out, "data: %s\n\n", event)
	return out.String()
}

func TestChatTextContractJSONAndSSE(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, tc := range []struct {
		name                         string
		deltas                       []string
		want, status, reason, finish string
	}{
		{"split", []string{"你好EN", "Dhidden"}, "你好", "completed", "", "stop"},
		{"empty", []string{"ENDhidden"}, "", "completed", "", "stop"},
		{"tail", []string{"hello EN"}, "hello EN", "completed", "", "stop"},
		{"limit", []string{"hello"}, "hello", "incomplete", "max_output_tokens", "length"},
		{"stop_before_limit", []string{"helloENDhidden"}, "hello", "incomplete", "max_output_tokens", "stop"},
		{"filter", []string{"helloENDhidden"}, "hello", "incomplete", "content_filter", "content_filter"},
	} {
		for _, stream := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/stream=%t", tc.name, stream), func(t *testing.T) {
				rec := httptest.NewRecorder()
				c, _ := gin.CreateTestContext(rec)
				c.Request = httptest.NewRequest("POST", "/v1/chat/completions", nil)
				resp := &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(chatTextFixture(tc.deltas, tc.status, tc.reason)))}
				contract := newChatTextContract(c.Request.Context(), resp.Body, func() {}, []string{"END"}, 1)
				defer contract.close()
				svc := &OpenAIGatewayService{cfg: &config.Config{}}
				account := &Account{ID: 1, Platform: PlatformOpenAI}
				var result *OpenAIForwardResult
				var err error
				if stream {
					result, err = svc.handleChatStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", time.Now(), 0, contract)
				} else {
					result, err = svc.handleChatBufferedStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", time.Now(), contract)
				}
				require.NoError(t, err)
				require.NotNil(t, result)
				require.Equal(t, 17, result.Usage.OutputTokens)
				text, finish := "", ""
				finishes, usages := 0, 0
				if stream {
					require.Equal(t, 1, strings.Count(rec.Body.String(), "data: [DONE]"))
					for _, line := range strings.Split(rec.Body.String(), "\n") {
						if !strings.HasPrefix(line, "data: {") {
							continue
						}
						body := strings.TrimPrefix(line, "data: ")
						text += gjson.Get(body, "choices.0.delta.content").String()
						if v := gjson.Get(body, "choices.0.finish_reason"); v.Type == gjson.String {
							finish = v.String()
							finishes++
						}
						if gjson.Get(body, "usage").Exists() {
							usages++
							require.Equal(t, int64(1024), gjson.Get(body, "usage.prompt_tokens_details.cached_tokens").Int())
						}
					}
					require.Equal(t, 1, finishes)
					require.Equal(t, 1, usages)
				} else {
					text = gjson.Get(rec.Body.String(), "choices.0.message.content").String()
					finish = gjson.Get(rec.Body.String(), "choices.0.finish_reason").String()
				}
				require.Equal(t, tc.want, text)
				require.Equal(t, tc.finish, finish)
			})
		}
	}
}

func TestChatTextContractBoundedDrain(t *testing.T) {
	for _, disconnect := range []bool{false, true} {
		for _, stream := range []bool{false, true} {
			t.Run(fmt.Sprintf("disconnect=%t/stream=%t", disconnect, stream), func(t *testing.T) {
				rec := httptest.NewRecorder()
				c, _ := gin.CreateTestContext(rec)
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				c.Request = httptest.NewRequest("POST", "/v1/chat/completions", nil).WithContext(ctx)
				reader, writer := io.Pipe()
				defer func() { _ = reader.Close() }()
				defer func() { _ = writer.Close() }()
				resp := &http.Response{StatusCode: 200, Header: make(http.Header), Body: reader}
				contract := newChatTextContract(ctx, reader, func() {}, []string{"END"}, 1)
				contract.drainTimeout = 30 * time.Millisecond
				defer contract.close()
				go func() {
					delta := "END"
					if disconnect {
						delta = "hello"
					}
					_, _ = fmt.Fprintf(writer, "data: {\"type\":\"response.output_text.delta\",\"delta\":%q}\n\n", delta)
					if disconnect {
						cancel()
					}
					for {
						if _, err := io.WriteString(writer, ": heartbeat\n\n"); err != nil {
							return
						}
						time.Sleep(time.Millisecond)
					}
				}()
				svc := &OpenAIGatewayService{cfg: &config.Config{}}
				account := &Account{ID: 1, Platform: PlatformOpenAI}
				start := time.Now()
				var result *OpenAIForwardResult
				var err error
				if stream {
					result, err = svc.handleChatStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", start, 0, contract)
				} else {
					result, err = svc.handleChatBufferedStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", start, contract)
				}
				require.Error(t, err)
				require.NotNil(t, result)
				require.Less(t, time.Since(start), time.Second)
				var replay *UpstreamFailoverError
				require.NotErrorAs(t, err, &replay)
				require.NotContains(t, rec.Body.String(), "data: [DONE]")
			})
		}
	}
}

func TestChatContractActualResponsesDispatch(t *testing.T) {
	for _, tc := range []struct {
		name, policy string
		floor, want  int64
	}{
		{"strict-preserves-client-limit", "strict", 64, 16},
		{"legacy-uses-configured-floor", "legacy", 64, 64},
		{"legacy-uses-default-floor", "legacy", 0, 128},
	} {
		for _, mode := range []string{"none", "auto", "required"} {
			t.Run(tc.name+"/"+mode, func(t *testing.T) {
				rec := httptest.NewRecorder()
				c, _ := gin.CreateTestContext(rec)
				body := []byte(`{"model":"gpt-5.4","messages":[{"role":"user","content":"hi"}],"max_tokens":100,"max_completion_tokens":16,"tools":[{"type":"function","function":{"name":"f"}}],"tool_choice":"` + mode + `"}`)
				c.Request = httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(string(body)))
				upstream := &httpUpstreamRecorder{resp: &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(chatTextFixture([]string{"hello"}, "completed", "")))}}
				cfg := &config.Config{}
				cfg.Gateway.MinOutputTokens = int(tc.floor)
				cfg.Gateway.OpenAIChatContract = config.OpenAIChatContractConfig{Policy: tc.policy, StopMode: "reject", DrainTimeoutSeconds: 30}
				svc := &OpenAIGatewayService{cfg: cfg, httpUpstream: upstream}
				account := &Account{ID: 1, Platform: PlatformOpenAI, Type: AccountTypeAPIKey, Credentials: map[string]any{"api_key": "test-only"}, Extra: map[string]any{"openai_responses_supported": true}}
				_, err := svc.ForwardAsChatCompletions(context.Background(), c, account, body, "", "gpt-5.4")
				require.NoError(t, err)
				require.Equal(t, tc.want, gjson.GetBytes(upstream.lastBody, "max_output_tokens").Int())
				require.Equal(t, mode, gjson.GetBytes(upstream.lastBody, "tool_choice").String())
			})
		}
	}
}

func TestChatTextContractUnexpectedOutputAndMissingTerminal(t *testing.T) {
	for _, payload := range []string{
		`data: {"type":"response.output_item.added","item":{"type":"function_call","name":"f","call_id":"c"}}` + "\n\n",
		`data: {"type":"response.refusal.delta","delta":"no"}` + "\n\n",
		`data: {"type":"response.output_text.delta","delta":"ENDhidden"}` + "\n\n",
	} {
		for _, stream := range []bool{false, true} {
			rec := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(rec)
			c.Request = httptest.NewRequest("POST", "/v1/chat/completions", nil)
			resp := &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(payload))}
			contract := newChatTextContract(c.Request.Context(), resp.Body, func() {}, []string{"END"}, 1)
			svc := &OpenAIGatewayService{cfg: &config.Config{}}
			account := &Account{ID: 1, Platform: PlatformOpenAI}
			var result *OpenAIForwardResult
			var err error
			if stream {
				result, err = svc.handleChatStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", time.Now(), 0, contract)
			} else {
				result, err = svc.handleChatBufferedStreamingResponse(resp, c, account, "gpt-5", "gpt-5", "gpt-5", time.Now(), contract)
			}
			contract.close()
			require.Error(t, err)
			require.NotNil(t, result)
			var replay *UpstreamFailoverError
			require.NotErrorAs(t, err, &replay)
			require.NotContains(t, rec.Body.String(), "hidden")
			require.NotContains(t, rec.Body.String(), "data: [DONE]")
		}
	}
}

func TestChatContractBranchPolicy(t *testing.T) {
	for _, branch := range []chatContractBranch{contractCodex, contractResponses, contractRawChat, contractAnthropic} {
		rec := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(rec)
		cfg := &config.Config{}
		cfg.Gateway.OpenAIChatContract = config.OpenAIChatContractConfig{Policy: "strict", StopMode: "reject", DrainTimeoutSeconds: 30}
		_, err := prepareChatContract(cfg, c, []byte(`{"messages":[],"max_completion_tokens":16}`), branch)
		if branch == contractCodex {
			require.Error(t, err)
			require.True(t, IsChatContractParameterError(err))
			require.Equal(t, 400, rec.Code)
		} else {
			require.NoError(t, err)
		}
		_, err = prepareChatContract(cfg, c, []byte(`{"messages":[],"stop":"END"}`), branch)
		if branch == contractCodex || branch == contractResponses {
			require.Error(t, err)
		} else {
			require.NoError(t, err)
		}
	}
	var legacy config.Config
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	plan, err := prepareChatContract(&legacy, c, []byte(`{"stop":123}`), contractCodex)
	require.NoError(t, err)
	require.Nil(t, plan.constraints)
	_, err = apicompat.ParseChatConstraints([]byte(`{"stop":123}`))
	require.Error(t, err)
}
