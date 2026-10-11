package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/pkg/apicompat"
)

var (
	errChatStopDrainTimeout = errors.New("text stop drain deadline exceeded; upstream usage may be incomplete")
	errChatTextOutput       = errors.New("upstream returned output incompatible with text stop simulation")
)

// The scanner belongs to the response reader. Only timer/cancellation state is
// shared with callbacks; callbacks never access Gin or write client responses.
type chatTextContract struct {
	scanner      *apicompat.TextStopScanner
	stops        []string
	sawText      bool
	body         io.Closer
	cancel       context.CancelFunc
	drainTimeout time.Duration
	mu           sync.Mutex
	timer        *time.Timer
	closed       bool
	expired      bool
	stopWatching func() bool
}

func newChatTextContract(ctx context.Context, body io.Closer, cancel context.CancelFunc, stops []string, seconds int) *chatTextContract {
	if seconds <= 0 {
		seconds = 30
	}
	t := &chatTextContract{scanner: apicompat.NewTextStopScanner(stops), stops: append([]string(nil), stops...), body: body, cancel: cancel, drainTimeout: time.Duration(seconds) * time.Second}
	t.stopWatching = context.AfterFunc(ctx, t.startDrain)
	return t
}

func firstChatTextContract(options []*chatTextContract) *chatTextContract {
	if len(options) == 0 {
		return nil
	}
	return options[0]
}

func (t *chatTextContract) matched() bool { return t != nil && t.scanner.Matched() }

func (t *chatTextContract) startDrain() {
	if t == nil {
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed || t.timer != nil {
		return
	}
	t.timer = time.AfterFunc(t.drainTimeout, func() {
		t.mu.Lock()
		if t.closed {
			t.mu.Unlock()
			return
		}
		t.expired = true
		t.mu.Unlock()
		if t.cancel != nil {
			t.cancel()
		}
		if t.body != nil {
			_ = t.body.Close()
		}
	})
}

func (t *chatTextContract) close() {
	if t == nil {
		return
	}
	t.mu.Lock()
	t.closed = true
	if t.timer != nil {
		t.timer.Stop()
	}
	t.mu.Unlock()
	if t.stopWatching != nil {
		t.stopWatching()
	}
}

func (t *chatTextContract) err() error {
	if t == nil {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.expired {
		return errChatStopDrainTimeout
	}
	return nil
}

func (t *chatTextContract) push(text string) string {
	t.sawText = true
	visible, hit := t.scanner.Push(text)
	if hit {
		t.startDrain()
	}
	return visible
}

func validateChatTextItem(item *apicompat.ResponsesOutput) error {
	if item == nil {
		return nil
	}
	if item.Type != "message" && item.Type != "reasoning" {
		return errChatTextOutput
	}
	if item.Type == "message" {
		for _, part := range item.Content {
			if part.Type != "output_text" {
				return errChatTextOutput
			}
		}
	}
	return nil
}

// Buffered readers scan deltas immediately to start the absolute deadline;
// streaming readers scan their converted text chunks exactly once instead.
func (t *chatTextContract) observe(event *apicompat.ResponsesStreamEvent, buffered bool) error {
	if t == nil {
		return nil
	}
	if err := t.err(); err != nil {
		return err
	}
	// Existing upstream failure / cyber-policy handling takes priority.
	if event.Type == "response.failed" || event.Type == "error" {
		t.close()
		return nil
	}
	if strings.Contains(event.Type, "refusal") || strings.Contains(event.Type, "audio") || strings.Contains(event.Type, "function_call") || strings.Contains(event.Type, "custom_tool_call") {
		return errChatTextOutput
	}
	if err := validateChatTextItem(event.Item); err != nil {
		return err
	}
	if event.Part != nil && strings.HasPrefix(event.Type, "response.content_part.") && event.Part.Type != "output_text" {
		return errChatTextOutput
	}
	if event.Response != nil {
		for i := range event.Response.Output {
			if err := validateChatTextItem(&event.Response.Output[i]); err != nil {
				return err
			}
		}
	}
	if buffered && event.Type == "response.output_text.delta" {
		t.push(event.Delta)
	}
	if isOpenAICompatResponsesTerminalEvent(event.Type) {
		t.close()
	}
	return nil
}

func (t *chatTextContract) chunks(event *apicompat.ResponsesStreamEvent, state *apicompat.ResponsesEventToChatState) []apicompat.ChatCompletionsChunk {
	var chunks []apicompat.ChatCompletionsChunk
	// Some compatible backends supply text only in the terminal response.
	if !t.sawText && event.Response != nil && isOpenAICompatResponsesTerminalEvent(event.Type) {
		chat := apicompat.ResponsesToChatCompletions(event.Response, state.Model)
		if len(chat.Choices) == 1 {
			var text string
			_ = json.Unmarshal(chat.Choices[0].Message.Content, &text)
			if text != "" {
				chunks = append(chunks, apicompat.ResponsesEventToChatChunks(&apicompat.ResponsesStreamEvent{Type: "response.output_text.delta", Delta: text}, state)...)
			}
		}
	}
	chunks = append(chunks, apicompat.ResponsesEventToChatChunks(event, state)...)
	for i := range chunks {
		for j := range chunks[i].Choices {
			choice := &chunks[i].Choices[j]
			if choice.Delta.Content != nil {
				visible := t.push(*choice.Delta.Content)
				choice.Delta.Content = &visible
			}
			if choice.FinishReason != nil {
				tail, hit := t.scanner.Finish()
				if tail != "" {
					choice.Delta.Content = &tail
				}
				if hit && (*choice.FinishReason == "stop" || *choice.FinishReason == "length") {
					reason := "stop"
					choice.FinishReason = &reason
				}
			}
		}
	}
	return chunks
}

func (t *chatTextContract) bufferedResponse(chat *apicompat.ChatCompletionsResponse) error {
	if t == nil {
		return nil
	}
	if len(chat.Choices) != 1 || len(chat.Choices[0].Message.ToolCalls) != 0 {
		return errChatTextOutput
	}
	choice := &chat.Choices[0]
	var text string
	if len(choice.Message.Content) > 0 && json.Unmarshal(choice.Message.Content, &text) != nil {
		return errChatTextOutput
	}
	scanner := apicompat.NewTextStopScanner(t.stops)
	visible, _ := scanner.Push(text)
	tail, hit := scanner.Finish()
	choice.Message.Content, _ = json.Marshal(visible + tail)
	if hit && (choice.FinishReason == "stop" || choice.FinishReason == "length") {
		choice.FinishReason = "stop"
	}
	return nil
}
