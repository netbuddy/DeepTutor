// 这个文件是前面各章逐格写出来的代码，一行没改，只是收进了铺底目录。
// 讲义因此不必每章开头重贴一遍。想看某一段当初是怎么来的，回到对应章节。

package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

type ToolResult struct {
	Content       string
	IsError       bool
	IsInvalidArgs bool
}

type Tool interface {
	Spec() ToolSpec
	Run(args map[string]any) (string, error)
}

type FuncTool struct {
	spec ToolSpec
	fn   func(args map[string]any) (string, error)
}

func NewFuncTool(name, description string, parameters map[string]any,
	fn func(args map[string]any) (string, error)) *FuncTool {
	return &FuncTool{spec: ToolSpec{Name: name, Description: description, Parameters: parameters}, fn: fn}
}

func (t *FuncTool) Spec() ToolSpec                          { return t.spec }
func (t *FuncTool) Run(args map[string]any) (string, error) { return t.fn(args) }

func argString(args map[string]any, key string) string {
	s, _ := args[key].(string)
	return s
}

func jsonTypeOf(value any) string {
	switch v := value.(type) {
	case string:
		return "string"
	case bool:
		return "boolean"
	case float64:
		if v == math.Trunc(v) {
			return "integer"
		}
		return "number"
	case int:
		return "integer"
	case []any:
		return "array"
	case map[string]any:
		return "object"
	case nil:
		return "null"
	}
	return "unknown"
}

func requiredNames(schema map[string]any) []string {
	switch v := schema["required"].(type) {
	case []string:
		return v
	case []any:
		var out []string
		for _, item := range v {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func ValidateArgs(args map[string]any, schema map[string]any) string {
	if raw, bad := args["_invalid_json"]; bad {
		text := fmt.Sprint(raw)
		if len(text) > 120 {
			text = text[:120]
		}
		return "参数不是合法的 JSON：" + text
	}
	props, _ := schema["properties"].(map[string]any)
	if props == nil {
		props = map[string]any{}
	}
	for _, name := range requiredNames(schema) {
		if _, ok := args[name]; !ok {
			return "缺少必填参数 " + name
		}
	}
	for _, key := range sortedKeys(args) {
		spec, known := props[key].(map[string]any)
		if !known {
			return fmt.Sprintf("不认识的参数 %s；这个工具接受 %s", key, strings.Join(sortedKeys(props), "、"))
		}
		value := args[key]
		if want, _ := spec["type"].(string); want != "" {
			got := jsonTypeOf(value)
			if !(got == want || (want == "number" && got == "integer")) {
				return fmt.Sprintf("参数 %s 应该是 %s，收到的是 %s", key, want, got)
			}
		}
		if enum, ok := spec["enum"].([]any); ok && len(enum) > 0 {
			hit := false
			var allowed []string
			for _, candidate := range enum {
				allowed = append(allowed, fmt.Sprint(candidate))
				if fmt.Sprint(candidate) == fmt.Sprint(value) {
					hit = true
				}
			}
			if !hit {
				return fmt.Sprintf("参数 %s 只能是 %s 之一", key, strings.Join(allowed, "、"))
			}
		}
	}
	return ""
}

type ToolRegistry struct {
	tools map[string]Tool
	order []string
}

func NewToolRegistry(tools ...Tool) *ToolRegistry {
	reg := &ToolRegistry{tools: map[string]Tool{}}
	for _, t := range tools {
		reg.Add(t)
	}
	return reg
}

func (reg *ToolRegistry) Add(tool Tool) {
	name := tool.Spec().Name
	if _, exists := reg.tools[name]; !exists {
		reg.order = append(reg.order, name)
	}
	reg.tools[name] = tool
}

func (reg *ToolRegistry) Names() []string { return reg.order }

func (reg *ToolRegistry) Specs() []ToolSpec {
	var out []ToolSpec
	for _, name := range reg.order {
		out = append(out, reg.tools[name].Spec())
	}
	return out
}

func (reg *ToolRegistry) Execute(name string, args map[string]any) (result ToolResult) {
	tool, ok := reg.tools[name]
	if !ok {
		return ToolResult{Content: fmt.Sprintf("没有叫 %s 的工具。可用的：%s",
			name, strings.Join(reg.order, "、")), IsError: true}
	}
	if problem := ValidateArgs(args, tool.Spec().Parameters); problem != "" {
		return ToolResult{Content: "参数不合格：" + problem, IsError: true, IsInvalidArgs: true}
	}
	defer func() {
		if r := recover(); r != nil {
			result = ToolResult{Content: fmt.Sprintf("工具 %s 执行时崩溃了：%v", name, r), IsError: true}
		}
	}()
	output, err := tool.Run(args)
	if err != nil {
		return ToolResult{Content: err.Error(), IsError: true}
	}
	return ToolResult{Content: output}
}

type GetTimeTool struct{ Now func() time.Time }

func (t GetTimeTool) Spec() ToolSpec {
	return ToolSpec{Name: "get_time", Description: "查询某个城市的当前时间",
		Parameters: map[string]any{"type": "object", "properties": map[string]any{
			"city": map[string]any{"type": "string", "description": "城市名"},
			"unit": map[string]any{"type": "string", "enum": []any{"24h", "12h"}}},
			"required": []string{"city"}}}
}

func (t GetTimeTool) Run(args map[string]any) (string, error) {
	now := time.Now()
	if t.Now != nil {
		now = t.Now()
	}
	layout := "15:04"
	if argString(args, "unit") == "12h" {
		layout = "03:04 PM"
	}
	return fmt.Sprintf("%s 现在是 %s", argString(args, "city"), now.Format(layout)), nil
}

type calcParser struct {
	src []rune
	pos int
}

func (p *calcParser) peek() rune {
	for p.pos < len(p.src) && (p.src[p.pos] == ' ' || p.src[p.pos] == '\t') {
		p.pos++
	}
	if p.pos >= len(p.src) {
		return 0
	}
	return p.src[p.pos]
}

func (p *calcParser) parseExpr() (float64, error) {
	value, err := p.parseTerm()
	if err != nil {
		return 0, err
	}
	for {
		op := p.peek()
		if op != '+' && op != '-' {
			return value, nil
		}
		p.pos++
		rhs, err := p.parseTerm()
		if err != nil {
			return 0, err
		}
		if op == '+' {
			value += rhs
		} else {
			value -= rhs
		}
	}
}

func (p *calcParser) parseTerm() (float64, error) {
	value, err := p.parseAtom()
	if err != nil {
		return 0, err
	}
	for {
		op := p.peek()
		if op != '*' && op != '/' {
			return value, nil
		}
		p.pos++
		rhs, err := p.parseAtom()
		if err != nil {
			return 0, err
		}
		if op == '*' {
			value *= rhs
		} else {
			if rhs == 0 {
				return 0, fmt.Errorf("除数不能是 0")
			}
			value /= rhs
		}
	}
}

func (p *calcParser) parseAtom() (float64, error) {
	c := p.peek()
	switch {
	case c == '(':
		p.pos++
		value, err := p.parseExpr()
		if err != nil {
			return 0, err
		}
		if p.peek() != ')' {
			return 0, fmt.Errorf("括号没配对")
		}
		p.pos++
		return value, nil
	case c == '-':
		p.pos++
		value, err := p.parseAtom()
		return -value, err
	case c >= '0' && c <= '9':
		start := p.pos
		for p.pos < len(p.src) && ((p.src[p.pos] >= '0' && p.src[p.pos] <= '9') || p.src[p.pos] == '.') {
			p.pos++
		}
		return strconv.ParseFloat(string(p.src[start:p.pos]), 64)
	case c == 0:
		return 0, fmt.Errorf("表达式在这里就断了，后面少了东西")
	default:
		return 0, fmt.Errorf("看不懂的字符 %q，只支持数字和 + - * / ( )", string(c))
	}
}

func Calculate(expression string) (string, error) {
	if len(expression) > 200 {
		return "", fmt.Errorf("表达式太长了（%d 个字符，上限 200）", len(expression))
	}
	p := &calcParser{src: []rune(expression)}
	value, err := p.parseExpr()
	if err != nil {
		return "", err
	}
	if p.peek() != 0 {
		return "", fmt.Errorf("表达式在第 %d 个字符之后还有多余内容", p.pos)
	}
	return strconv.FormatFloat(value, 'f', -1, 64), nil
}

func NewCalcTool() Tool {
	return NewFuncTool("calculate", "计算一个算术表达式，比如 (3+5)*2",
		map[string]any{"type": "object", "properties": map[string]any{
			"expression": map[string]any{"type": "string", "description": "只含数字和 + - * / ( ) 的表达式"}},
			"required": []string{"expression"}},
		func(args map[string]any) (string, error) { return Calculate(argString(args, "expression")) })
}
