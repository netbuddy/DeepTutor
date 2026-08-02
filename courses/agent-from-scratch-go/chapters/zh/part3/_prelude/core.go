// 这个文件是前面各章逐格写出来的代码，一行没改，只是收进了铺底目录。
// 讲义因此不必每章开头重贴一遍。想看某一段当初是怎么来的，回到对应章节。

package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
)

func newID(prefix string) string {
	buf := make([]byte, 6)
	rand.Read(buf)
	return prefix + "_" + hex.EncodeToString(buf)
}

type Block interface{ BlockType() string }

type TextBlock struct{ Text string }

func (TextBlock) BlockType() string { return "text" }

type ToolUseBlock struct {
	ID   string
	Name string
	Args map[string]any
}

func (ToolUseBlock) BlockType() string { return "tool_use" }

type ToolResultBlock struct {
	ToolUseID string
	Content   string
	IsError   bool
}

func (ToolResultBlock) BlockType() string { return "tool_result" }

type Message struct {
	ID      string
	Role    string
	Content []Block
}

func (m Message) Text() string {
	out := ""
	for _, b := range m.Content {
		if t, ok := b.(TextBlock); ok {
			out += t.Text
		}
	}
	return out
}

func (m Message) ToolUses() []ToolUseBlock {
	var calls []ToolUseBlock
	for _, b := range m.Content {
		if c, ok := b.(ToolUseBlock); ok {
			calls = append(calls, c)
		}
	}
	return calls
}

func NewMessage(role string, blocks ...Block) Message {
	return Message{ID: newID("msg"), Role: role, Content: blocks}
}

func NewToolUse(name string, args map[string]any) ToolUseBlock {
	return ToolUseBlock{ID: newID("call"), Name: name, Args: args}
}

type ToolSpec struct {
	Name        string
	Description string
	Parameters  map[string]any
}

type Delta struct {
	Kind string
	Text string
	Tool *ToolUseBlock
}

type Model interface {
	Stream(messages []Message, tools []ToolSpec) (<-chan Delta, <-chan error)
}

func Collect(deltas <-chan Delta, errs <-chan error) (Message, error) {
	var textParts []string
	var blocks []Block
	flushText := func() {
		if len(textParts) > 0 {
			joined := ""
			for _, p := range textParts {
				joined += p
			}
			blocks = append(blocks, TextBlock{Text: joined})
			textParts = nil
		}
	}
	for d := range deltas {
		switch d.Kind {
		case "text":
			textParts = append(textParts, d.Text)
		case "tool_use":
			if d.Tool != nil {
				flushText()
				blocks = append(blocks, *d.Tool)
			}
		}
	}
	flushText()
	if err := <-errs; err != nil {
		return Message{}, err
	}
	return NewMessage("assistant", blocks...), nil
}

type ScriptedCall struct {
	Name string
	Args map[string]any
}

type ScriptedTurn struct {
	Text  string
	Calls []ScriptedCall
}

type ScriptedModel struct {
	Script    []ScriptedTurn
	ChunkSize int
	calls     int
}

func NewScriptedModel(script []ScriptedTurn) *ScriptedModel {
	return &ScriptedModel{Script: script, ChunkSize: 4}
}

func (m *ScriptedModel) Stream(messages []Message, tools []ToolSpec) (<-chan Delta, <-chan error) {
	deltas := make(chan Delta, 8)
	errs := make(chan error, 1)
	if m.calls >= len(m.Script) {
		close(deltas)
		errs <- fmt.Errorf("剧本只有 %d 幕，但模型被调用了第 %d 次", len(m.Script), m.calls+1)
		close(errs)
		return deltas, errs
	}
	turn := m.Script[m.calls]
	m.calls++
	go func() {
		defer close(deltas)
		defer close(errs)
		runes := []rune(turn.Text)
		for i := 0; i < len(runes); i += m.ChunkSize {
			end := i + m.ChunkSize
			if end > len(runes) {
				end = len(runes)
			}
			deltas <- Delta{Kind: "text", Text: string(runes[i:end])}
		}
		for _, c := range turn.Calls {
			call := NewToolUse(c.Name, c.Args)
			deltas <- Delta{Kind: "tool_use", Tool: &call}
		}
		errs <- nil
	}()
	return deltas, errs
}

type wireFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type wireToolCall struct {
	Index    int          `json:"index,omitempty"`
	ID       string       `json:"id,omitempty"`
	Type     string       `json:"type,omitempty"`
	Function wireFunction `json:"function"`
}

type wireMessage struct {
	Role       string         `json:"role"`
	Content    *string        `json:"content"`
	ToolCallID string         `json:"tool_call_id,omitempty"`
	ToolCalls  []wireToolCall `json:"tool_calls,omitempty"`
}

type wireToolDef struct {
	Type     string `json:"type"`
	Function struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		Parameters  map[string]any `json:"parameters"`
	} `json:"function"`
}

type wireRequest struct {
	Model    string        `json:"model"`
	Messages []wireMessage `json:"messages"`
	Tools    []wireToolDef `json:"tools,omitempty"`
	Stream   bool          `json:"stream,omitempty"`
}

type wireChoice struct {
	Delta   wireMessage `json:"delta"`
	Message wireMessage `json:"message"`
}

type wireResponse struct {
	Choices []wireChoice `json:"choices"`
}

func toWireMessages(messages []Message) []wireMessage {
	var out []wireMessage
	for _, m := range messages {
		if m.Role == "tool" {
			for _, b := range m.Content {
				if r, ok := b.(ToolResultBlock); ok {
					content := r.Content
					out = append(out, wireMessage{Role: "tool", Content: &content, ToolCallID: r.ToolUseID})
				}
			}
			continue
		}
		text, calls := m.Text(), m.ToolUses()
		wm := wireMessage{Role: m.Role}
		if text != "" {
			wm.Content = &text
		}
		for _, c := range calls {
			args, err := json.Marshal(c.Args)
			if err != nil {
				args = []byte("{}")
			}
			wm.ToolCalls = append(wm.ToolCalls, wireToolCall{ID: c.ID, Type: "function",
				Function: wireFunction{Name: c.Name, Arguments: string(args)}})
		}
		out = append(out, wm)
	}
	return out
}

func toWireTools(specs []ToolSpec) []wireToolDef {
	var out []wireToolDef
	for _, s := range specs {
		var d wireToolDef
		d.Type = "function"
		d.Function.Name = s.Name
		d.Function.Description = s.Description
		if s.Parameters == nil {
			d.Function.Parameters = map[string]any{"type": "object", "properties": map[string]any{}}
		} else {
			d.Function.Parameters = s.Parameters
		}
		out = append(out, d)
	}
	return out
}

func parseArguments(raw string) map[string]any {
	if raw == "" {
		return map[string]any{}
	}
	var args map[string]any
	if err := json.Unmarshal([]byte(raw), &args); err != nil {
		return map[string]any{"_invalid_json": raw}
	}
	return args
}

type toolCallSlot struct{ id, name, arguments string }

type toolCallAccumulator struct{ slots map[int]*toolCallSlot }

func newToolCallAccumulator() *toolCallAccumulator {
	return &toolCallAccumulator{slots: map[int]*toolCallSlot{}}
}

func (a *toolCallAccumulator) Feed(calls []wireToolCall) {
	for _, item := range calls {
		slot, ok := a.slots[item.Index]
		if !ok {
			slot = &toolCallSlot{}
			a.slots[item.Index] = slot
		}
		if item.ID != "" {
			slot.id = item.ID
		}
		if item.Function.Name != "" {
			slot.name = item.Function.Name
		}
		if item.Function.Arguments != "" {
			slot.arguments += item.Function.Arguments
		}
	}
}

func (a *toolCallAccumulator) Finish() []ToolUseBlock {
	indexes := make([]int, 0, len(a.slots))
	for i := range a.slots {
		indexes = append(indexes, i)
	}
	sort.Ints(indexes)
	var blocks []ToolUseBlock
	for _, i := range indexes {
		slot := a.slots[i]
		id := slot.id
		if id == "" {
			id = newID("call")
		}
		blocks = append(blocks, ToolUseBlock{ID: id, Name: slot.name, Args: parseArguments(slot.arguments)})
	}
	return blocks
}

func parseSSELine(line string) (wireResponse, bool) {
	line = strings.TrimSpace(line)
	if line == "" || strings.HasPrefix(line, ":") || !strings.HasPrefix(line, "data:") {
		return wireResponse{}, false
	}
	payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
	if payload == "[DONE]" {
		return wireResponse{}, false
	}
	var parsed wireResponse
	if err := json.Unmarshal([]byte(payload), &parsed); err != nil {
		return wireResponse{}, false
	}
	return parsed, true
}

type OpenAICompatModel struct {
	BaseURL string
	ModelID string
	APIKey  string
	Timeout time.Duration
}

func NewOpenAICompatModel(baseURL, modelID string) *OpenAICompatModel {
	return &OpenAICompatModel{BaseURL: baseURL, ModelID: modelID, Timeout: 180 * time.Second}
}

func (m *OpenAICompatModel) Stream(messages []Message, tools []ToolSpec) (<-chan Delta, <-chan error) {
	deltas := make(chan Delta, 32)
	errs := make(chan error, 1)
	go func() {
		defer close(deltas)
		defer close(errs)
		body := wireRequest{Model: m.ModelID, Messages: toWireMessages(messages),
			Tools: toWireTools(tools), Stream: true}
		raw, err := json.Marshal(body)
		if err != nil {
			errs <- fmt.Errorf("请求体序列化失败：%w", err)
			return
		}
		req, err := http.NewRequest("POST", m.BaseURL+"/chat/completions", bytes.NewReader(raw))
		if err != nil {
			errs <- fmt.Errorf("构造请求失败：%w", err)
			return
		}
		req.Header.Set("Content-Type", "application/json")
		if m.APIKey != "" {
			req.Header.Set("Authorization", "Bearer "+m.APIKey)
		}
		resp, err := (&http.Client{Timeout: m.Timeout}).Do(req)
		if err != nil {
			errs <- fmt.Errorf("请求失败：%w", err)
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			buf := make([]byte, 300)
			n, _ := resp.Body.Read(buf)
			errs <- fmt.Errorf("模型服务返回 %d：%s", resp.StatusCode, string(buf[:n]))
			return
		}
		acc := newToolCallAccumulator()
		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
		for scanner.Scan() {
			chunk, ok := parseSSELine(scanner.Text())
			if !ok || len(chunk.Choices) == 0 {
				continue
			}
			d := chunk.Choices[0].Delta
			if d.Content != nil && *d.Content != "" {
				deltas <- Delta{Kind: "text", Text: *d.Content}
			}
			if len(d.ToolCalls) > 0 {
				acc.Feed(d.ToolCalls)
			}
		}
		if err := scanner.Err(); err != nil {
			errs <- fmt.Errorf("读流中断：%w", err)
			return
		}
		for _, block := range acc.Finish() {
			b := block
			deltas <- Delta{Kind: "tool_use", Tool: &b}
		}
		errs <- nil
	}()
	return deltas, errs
}
