package service

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/Wei-Shaw/sub2api/internal/pkg/apicompat"
	"github.com/gin-gonic/gin"
	"github.com/tidwall/gjson"
	"github.com/tidwall/sjson"
)

type chatContractBranch string

const (
	contractRawChat   chatContractBranch = "raw_chat"
	contractResponses chatContractBranch = "responses"
	contractCodex     chatContractBranch = "codex"
	contractAnthropic chatContractBranch = "anthropic"
)

type chatContractPlan struct {
	constraints  *apicompat.ChatConstraints
	simulateStop bool
}

// ParseOpenAIChatContract validates only standard Chat requests in strict mode.
// Responses-shaped and other protocols retain their existing validation.
func ParseOpenAIChatContract(cfg *config.Config, body []byte) (*apicompat.ChatConstraints, *apicompat.ParameterError) {
	if cfg == nil || cfg.Gateway.OpenAIChatContract.Policy != "strict" ||
		(!gjson.GetBytes(body, "messages").Exists() && gjson.GetBytes(body, "input").Exists()) {
		return nil, nil
	}
	return apicompat.ParseChatConstraints(body)
}

// WriteChatContractError handles local errors once and never exposes inputs.
func WriteChatContractError(c *gin.Context, err error) bool {
	var parameter *apicompat.ParameterError
	if !errors.As(err, &parameter) {
		return false
	}
	MarkResponseCommitted(c)
	payload := gin.H{"error": gin.H{"type": "invalid_request_error", "code": parameter.Code, "param": parameter.Param, "message": parameter.Message}}
	if c.Writer.Written() {
		encoded, _ := json.Marshal(payload)
		_, _ = fmt.Fprintf(c.Writer, "data: %s\n\n", encoded)
		c.Writer.Flush()
	} else {
		c.JSON(http.StatusBadRequest, payload)
	}
	return true
}

func IsChatContractParameterError(err error) bool {
	var parameter *apicompat.ParameterError
	return errors.As(err, &parameter)
}

func prepareChatContract(cfg *config.Config, c *gin.Context, body []byte, branch chatContractBranch) (chatContractPlan, error) {
	constraints, err := ParseOpenAIChatContract(cfg, body)
	if err != nil {
		WriteChatContractError(c, err)
		return chatContractPlan{}, err
	}
	plan := chatContractPlan{constraints: constraints}
	if constraints == nil {
		return plan, nil
	}
	var rejected *apicompat.ParameterError
	switch {
	case branch != contractRawChat && (constraints.ToolPolicy.HasUnmappedTools || constraints.ToolPolicy.Kind == "branch_specific"):
		rejected = apicompat.UnsupportedChatParameter("tools")
	case branch == contractCodex && constraints.EffectiveMax != nil:
		rejected = apicompat.UnsupportedChatParameter(constraints.EffectiveMaxParam)
	case (branch == contractCodex || branch == contractResponses) && len(constraints.StopSequences) > 0:
		if cfg.Gateway.OpenAIChatContract.StopMode != "text" || !constraints.TextSimulationOK {
			rejected = apicompat.UnsupportedChatParameter("stop")
		} else {
			plan.simulateStop = true
		}
	}
	if rejected != nil {
		WriteChatContractError(c, rejected)
		return chatContractPlan{}, rejected
	}
	return plan, nil
}

func (p chatContractPlan) convert(req *apicompat.ChatCompletionsRequest) (*apicompat.ResponsesRequest, error) {
	if p.constraints == nil {
		return apicompat.ChatCompletionsToResponses(req)
	}
	local := *req
	p.constraints.ApplyToChat(&local)
	return apicompat.ChatCompletionsToResponsesWithOptions(&local, apicompat.ChatToResponsesOptions{
		PreserveMaxOutputTokens: true, NormalizeFunctionChoice: true,
	})
}

func (p chatContractPlan) applyAnthropic(req *apicompat.AnthropicRequest) error {
	if p.constraints == nil {
		return nil
	}
	req.StopSeqs = append([]string(nil), p.constraints.StopSequences...)
	if p.constraints.EffectiveMax != nil {
		req.MaxTokens = *p.constraints.EffectiveMax
		if req.Thinking != nil && req.Thinking.Type == "enabled" && req.Thinking.BudgetTokens >= req.MaxTokens {
			return apicompat.UnsupportedChatParameter(p.constraints.EffectiveMaxParam)
		}
	}
	return nil
}

// Builders may apply additional thinking defaults or strip stop sequences.
// Refuse such a rewrite before dispatch instead of claiming the constraint held.
func (p chatContractPlan) validateAnthropicBody(body []byte) error {
	if p.constraints == nil {
		return nil
	}
	if p.constraints.EffectiveMax != nil && gjson.GetBytes(body, "max_tokens").Int() != int64(*p.constraints.EffectiveMax) {
		return apicompat.UnsupportedChatParameter(p.constraints.EffectiveMaxParam)
	}
	if p.constraints.EffectiveMax != nil && gjson.GetBytes(body, "thinking.type").String() == "enabled" && gjson.GetBytes(body, "thinking.budget_tokens").Int() >= int64(*p.constraints.EffectiveMax) {
		return apicompat.UnsupportedChatParameter(p.constraints.EffectiveMaxParam)
	}
	if len(p.constraints.StopSequences) > 0 {
		var stops []string
		if json.Unmarshal([]byte(gjson.GetBytes(body, "stop_sequences").Raw), &stops) != nil || len(stops) != len(p.constraints.StopSequences) {
			return apicompat.UnsupportedChatParameter("stop")
		}
		for i, stop := range stops {
			if stop != p.constraints.StopSequences[i] {
				return apicompat.UnsupportedChatParameter("stop")
			}
		}
	}
	return nil
}

func (p chatContractPlan) rawBody(body []byte) ([]byte, error) {
	if p.constraints == nil {
		return body, nil
	}
	if p.constraints.EffectiveMax != nil {
		other := "max_tokens"
		if p.constraints.EffectiveMaxParam == other {
			other = "max_completion_tokens"
		}
		var err error
		body, err = sjson.DeleteBytes(body, other)
		if err != nil {
			return nil, err
		}
	}
	if p.constraints.ToolChoice.Presence == apicompat.FieldValue {
		return sjson.DeleteBytes(body, "function_call")
	}
	if p.constraints.ToolChoice.Presence == apicompat.FieldNull && p.constraints.FunctionCall.Presence == apicompat.FieldValue {
		return sjson.DeleteBytes(body, "tool_choice")
	}
	return body, nil
}
