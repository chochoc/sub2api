package apicompat

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestChatContractParameters(t *testing.T) {
	for _, tc := range []struct{ body, param string }{
		{`null`, "body"}, {`{"stop":""}`, "stop"}, {`{"stop":[null]}`, "stop"},
		{`{"stop":["a","b","c","d","e"]}`, "stop"},
		{`{"max_tokens":0}`, "max_tokens"}, {`{"max_completion_tokens":-1}`, "max_completion_tokens"},
		{`{"max_completion_tokens":1.5}`, "max_completion_tokens"}, {`{"max_tokens":"16"}`, "max_tokens"},
		{`{"max_tokens":999999999999999999999999}`, "max_tokens"},
		{`{"max_completion_tokens":16,"max_tokens":0}`, "max_tokens"},
		{`{"tool_choice":"required"}`, "tool_choice"}, {`{"n":0}`, "n"},
		{`{"tools":[{"type":"function","function":{"name":"f"}}],"tool_choice":{"type":"function","function":{"name":"missing"}}}`, "tool_choice"},
		{`{"functions":[{"name":"f"},{"name":"f"}]}`, "functions"},
	} {
		t.Run(tc.body, func(t *testing.T) {
			_, err := ParseChatConstraints([]byte(tc.body))
			require.NotNil(t, err)
			require.Equal(t, tc.param, err.Param)
		})
	}
	for _, body := range []string{`{}`, `{"stop":null}`, `{"stop":[]}`, `{"max_tokens":null}`} {
		c, err := ParseChatConstraints([]byte(body))
		require.Nil(t, err)
		require.Empty(t, c.StopSequences)
		require.Nil(t, c.EffectiveMax)
	}
	c, err := ParseChatConstraints([]byte(`{"max_tokens":100,"max_completion_tokens":16,"stop":"终止"}`))
	require.Nil(t, err)
	require.Equal(t, 16, *c.EffectiveMax)
	require.Equal(t, FieldAbsent, c.ToolChoice.Presence)
	for _, body := range []string{`{"n":2}`, `{"response_format":{"type":"json_object"}}`, `{"modalities":["audio"]}`, `{"functions":[{"name":"f"}]}`} {
		c, err := ParseChatConstraints([]byte(body))
		require.Nil(t, err)
		require.False(t, c.TextSimulationOK)
	}
}

func TestChatContractConversion(t *testing.T) {
	for _, mode := range []string{"none", "auto", "required"} {
		body := `{"model":"gpt-5","messages":[{"role":"user","content":"hi"}],"max_completion_tokens":16,"tools":[{"type":"function","function":{"name":"f"}}],"tool_choice":"` + mode + `"}`
		c, err := ParseChatConstraints([]byte(body))
		require.Nil(t, err)
		var req ChatCompletionsRequest
		require.NoError(t, json.Unmarshal([]byte(body), &req))
		old, e := ChatCompletionsToResponses(&req)
		require.NoError(t, e)
		require.Equal(t, 128, *old.MaxOutputTokens)
		c.ApplyToChat(&req)
		out, e := ChatCompletionsToResponsesWithOptions(&req, ChatToResponsesOptions{PreserveMaxOutputTokens: true, NormalizeFunctionChoice: true})
		require.NoError(t, e)
		require.Equal(t, 16, *out.MaxOutputTokens)
		require.JSONEq(t, `"`+mode+`"`, string(out.ToolChoice))
		require.Equal(t, mode == "none", c.TextSimulationOK)
	}
	body := []byte(`{"model":"gpt-5","messages":[],"functions":[{"name":"f"}],"function_call":{"name":"f"},"tool_choice":null}`)
	c, err := ParseChatConstraints(body)
	require.Nil(t, err)
	var req ChatCompletionsRequest
	require.NoError(t, json.Unmarshal(body, &req))
	c.ApplyToChat(&req)
	out, e := ChatCompletionsToResponsesWithOptions(&req, ChatToResponsesOptions{NormalizeFunctionChoice: true})
	require.NoError(t, e)
	require.JSONEq(t, `{"type":"function","name":"f"}`, string(out.ToolChoice))
}

func TestTextStopScannerAllPartitions(t *testing.T) {
	for _, tc := range []struct {
		text  string
		stops []string
	}{
		{"a终止后文", []string{"终止"}}, {"abx", []string{"abc", "b"}},
		{"ababcZ", []string{"abc", "bab"}}, {"ENDtail", []string{"END"}},
		{"no stop EN", []string{"END"}}, {"abc", []string{"bc", "ab"}},
	} {
		runes := []rune(tc.text)
		want, hit := tc.text, false
		for _, stop := range tc.stops {
			if i := strings.Index(tc.text, stop); i >= 0 && (!hit || i < len(want)) {
				want, hit = tc.text[:i], true
			}
		}
		for mask := 0; mask < 1<<(len(runes)-1); mask++ {
			s := NewTextStopScanner(tc.stops)
			got := ""
			start := 0
			for i := 1; i <= len(runes); i++ {
				if i == len(runes) || mask&(1<<(i-1)) != 0 {
					text, _ := s.Push(string(runes[start:i]))
					got += text
					start = i
				}
			}
			tail, matched := s.Finish()
			got += tail
			require.Equal(t, want, got, "text=%q mask=%d", tc.text, mask)
			require.Equal(t, hit, matched)
		}
	}
}
