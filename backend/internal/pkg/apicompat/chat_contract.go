package apicompat

import (
	"bytes"
	"encoding/json"
	"strconv"
	"strings"
	"unicode/utf8"
)

// ParameterError describes a local request constraint, not an upstream failure.
// Messages must never contain request text, tool schemas or credentials.
type ParameterError struct {
	Param   string `json:"param"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (e *ParameterError) Error() string { return e.Message }

func invalidChatParameter(param string) *ParameterError {
	return &ParameterError{Param: param, Code: "invalid_parameter", Message: "Invalid value for " + param + "."}
}

// UnsupportedChatParameter is intentionally independent of provider identities.
func UnsupportedChatParameter(param string) *ParameterError {
	return &ParameterError{Param: param, Code: "unsupported_parameter", Message: "The selected upstream path cannot enforce " + param + "."}
}

type FieldPresence uint8

const (
	FieldAbsent FieldPresence = iota
	FieldNull
	FieldValue
)

type RawJSONField struct {
	Presence FieldPresence
	Raw      json.RawMessage
}

type ChatToolPolicy struct {
	Kind                  string
	FunctionName          string
	DeclaredFunctionNames []string
	HasExecutableTools    bool
	HasUnmappedTools      bool
}

// ChatConstraints is a request-owned snapshot. Never mutate it between attempts.
type ChatConstraints struct {
	Stop                RawJSONField
	StopSequences       []string
	MaxTokens           RawJSONField
	MaxCompletionTokens RawJSONField
	EffectiveMax        *int
	EffectiveMaxParam   string
	ToolChoice          RawJSONField
	FunctionCall        RawJSONField
	ToolPolicy          ChatToolPolicy
	ChoiceCount         int
	TextSimulationOK    bool
	effectiveChoice     json.RawMessage
}

func rawChatField(fields map[string]json.RawMessage, name string) RawJSONField {
	raw, ok := fields[name]
	if !ok {
		return RawJSONField{}
	}
	raw = bytes.TrimSpace(raw)
	presence := FieldValue
	if bytes.Equal(raw, []byte("null")) {
		presence = FieldNull
	}
	return RawJSONField{Presence: presence, Raw: append(json.RawMessage(nil), raw...)}
}

func ParseChatStop(raw json.RawMessage) ([]string, *ParameterError) {
	value := bytes.TrimSpace(raw)
	if len(value) == 0 || bytes.Equal(value, []byte("null")) {
		return nil, nil
	}
	var stops []string
	switch value[0] {
	case '"':
		var stop string
		if json.Unmarshal(value, &stop) != nil {
			return nil, invalidChatParameter("stop")
		}
		stops = []string{stop}
	case '[':
		var items []json.RawMessage
		if json.Unmarshal(value, &items) != nil || len(items) > 4 {
			return nil, invalidChatParameter("stop")
		}
		for _, item := range items {
			item = bytes.TrimSpace(item)
			var stop string
			if len(item) == 0 || item[0] != '"' || json.Unmarshal(item, &stop) != nil {
				return nil, invalidChatParameter("stop")
			}
			stops = append(stops, stop)
		}
	default:
		return nil, invalidChatParameter("stop")
	}
	for _, stop := range stops {
		if stop == "" || !utf8.ValidString(stop) {
			return nil, invalidChatParameter("stop")
		}
	}
	return stops, nil
}

func positiveChatInteger(field RawJSONField, name string) (*int, *ParameterError) {
	if field.Presence != FieldValue {
		return nil, nil
	}
	for _, b := range field.Raw {
		if b < '0' || b > '9' {
			return nil, invalidChatParameter(name)
		}
	}
	v, err := strconv.ParseInt(string(field.Raw), 10, strconv.IntSize)
	if err != nil || v <= 0 {
		return nil, invalidChatParameter(name)
	}
	value := int(v)
	return &value, nil
}

func ParseChatConstraints(body []byte) (*ChatConstraints, *ParameterError) {
	var fields map[string]json.RawMessage
	if json.Unmarshal(body, &fields) != nil || fields == nil {
		return nil, invalidChatParameter("body")
	}
	c := &ChatConstraints{
		Stop: rawChatField(fields, "stop"), MaxTokens: rawChatField(fields, "max_tokens"),
		MaxCompletionTokens: rawChatField(fields, "max_completion_tokens"),
		ToolChoice:          rawChatField(fields, "tool_choice"), FunctionCall: rawChatField(fields, "function_call"),
		ChoiceCount: 1,
	}
	var err *ParameterError
	c.StopSequences, err = ParseChatStop(c.Stop.Raw)
	if err != nil {
		return nil, err
	}
	modern, err := positiveChatInteger(c.MaxCompletionTokens, "max_completion_tokens")
	if err != nil {
		return nil, err
	}
	legacy, err := positiveChatInteger(c.MaxTokens, "max_tokens")
	if err != nil {
		return nil, err
	}
	c.EffectiveMax, c.EffectiveMaxParam = legacy, "max_tokens"
	if modern != nil {
		c.EffectiveMax, c.EffectiveMaxParam = modern, "max_completion_tokens"
	}
	if c.EffectiveMax == nil {
		c.EffectiveMaxParam = ""
	}
	if err := c.parseTools(fields); err != nil {
		return nil, err
	}
	n, err := positiveChatInteger(rawChatField(fields, "n"), "n")
	if err != nil {
		return nil, err
	}
	if n != nil {
		c.ChoiceCount = *n
	}
	c.TextSimulationOK = c.ChoiceCount == 1 && !c.ToolPolicy.HasExecutableTools
	if f := rawChatField(fields, "modalities"); f.Presence == FieldValue {
		var modalities []string
		if json.Unmarshal(f.Raw, &modalities) != nil {
			return nil, invalidChatParameter("modalities")
		}
		c.TextSimulationOK = c.TextSimulationOK && len(modalities) == 1 && modalities[0] == "text"
	}
	if f := rawChatField(fields, "response_format"); f.Presence == FieldValue {
		var format struct {
			Type string `json:"type"`
		}
		if json.Unmarshal(f.Raw, &format) != nil {
			return nil, invalidChatParameter("response_format")
		}
		c.TextSimulationOK = c.TextSimulationOK && format.Type == "text"
	}
	return c, nil
}

func (c *ChatConstraints) parseTools(fields map[string]json.RawMessage) *ParameterError {
	names := make(map[string]struct{})
	count := 0
	for _, field := range []string{"tools", "functions"} {
		f := rawChatField(fields, field)
		if f.Presence != FieldValue {
			continue
		}
		var items []json.RawMessage
		if json.Unmarshal(f.Raw, &items) != nil {
			return invalidChatParameter(field)
		}
		for _, item := range items {
			var function ChatFunction
			if field == "tools" {
				var tool struct {
					Type     string          `json:"type"`
					Function json.RawMessage `json:"function"`
				}
				if json.Unmarshal(item, &tool) != nil || tool.Type == "" {
					return invalidChatParameter(field)
				}
				if tool.Type != "function" {
					count++
					c.ToolPolicy.HasUnmappedTools = true
					continue
				}
				item = tool.Function
			}
			if json.Unmarshal(item, &function) != nil || strings.TrimSpace(function.Name) == "" {
				return invalidChatParameter(field)
			}
			if _, exists := names[function.Name]; exists {
				return invalidChatParameter(field)
			}
			if raw := bytes.TrimSpace(function.Parameters); len(raw) > 0 && !bytes.Equal(raw, []byte("null")) && raw[0] != '{' {
				return invalidChatParameter(field)
			}
			names[function.Name] = struct{}{}
			c.ToolPolicy.DeclaredFunctionNames = append(c.ToolPolicy.DeclaredFunctionNames, function.Name)
			count++
		}
	}
	// Validate both choices, even when the modern field takes precedence.
	kind, name, err := parseChatChoice(c.ToolChoice, false, names)
	if err != nil {
		return err
	}
	legacyKind, legacyName, err := parseChatChoice(c.FunctionCall, true, names)
	if err != nil {
		return err
	}
	c.effectiveChoice = append(json.RawMessage(nil), c.ToolChoice.Raw...)
	if c.ToolChoice.Presence != FieldValue {
		kind, name = legacyKind, legacyName
		c.effectiveChoice = nil
		if c.FunctionCall.Presence == FieldValue {
			if kind == "function" {
				c.effectiveChoice, _ = json.Marshal(map[string]any{"type": "function", "function": map[string]string{"name": name}})
			} else {
				c.effectiveChoice, _ = json.Marshal(kind)
			}
		}
	}
	if kind == "" {
		kind = "none"
		if count > 0 {
			kind = "auto"
		}
	}
	if kind == "required" && count == 0 {
		return invalidChatParameter("tool_choice")
	}
	c.ToolPolicy.Kind, c.ToolPolicy.FunctionName = kind, name
	c.ToolPolicy.HasExecutableTools = count > 0 && kind != "none"
	return nil
}

func parseChatChoice(field RawJSONField, legacy bool, names map[string]struct{}) (string, string, *ParameterError) {
	param := "tool_choice"
	if legacy {
		param = "function_call"
	}
	if field.Presence != FieldValue {
		return "", "", nil
	}
	var choice string
	if json.Unmarshal(field.Raw, &choice) == nil {
		if choice == "none" || choice == "auto" || (!legacy && choice == "required") {
			return choice, "", nil
		}
		return "", "", invalidChatParameter(param)
	}
	var object struct {
		Type     string `json:"type"`
		Name     string `json:"name"`
		Function struct {
			Name string `json:"name"`
		} `json:"function"`
	}
	if json.Unmarshal(field.Raw, &object) != nil {
		return "", "", invalidChatParameter(param)
	}
	if !legacy && object.Type != "function" {
		if object.Type == "" {
			return "", "", invalidChatParameter(param)
		}
		return "branch_specific", "", nil
	}
	name := object.Name
	if !legacy {
		name = object.Function.Name
	}
	if _, ok := names[name]; !ok || name == "" {
		return "", "", invalidChatParameter(param)
	}
	return "function", name, nil
}

// ApplyToChat only changes a request-owned DTO, never the preserved input body.
func (c *ChatConstraints) ApplyToChat(req *ChatCompletionsRequest) {
	if c == nil {
		return
	}
	req.MaxTokens, req.MaxCompletionTokens = nil, nil
	if c.EffectiveMax != nil {
		value := *c.EffectiveMax
		if c.EffectiveMaxParam == "max_completion_tokens" {
			req.MaxCompletionTokens = &value
		} else {
			req.MaxTokens = &value
		}
	}
	req.ToolChoice = append(json.RawMessage(nil), c.effectiveChoice...)
	req.FunctionCall = nil
}
