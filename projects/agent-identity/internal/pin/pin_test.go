package pin_test

import (
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
)

func shape(t *testing.T, body string) string {
	t.Helper()
	h, err := pin.Shape([]byte(body))
	if err != nil {
		t.Fatalf("Shape(%s): %v", body, err)
	}
	return h
}

func TestShapeIgnoresMessagesModelAndMaxTokensAndKeyOrder(t *testing.T) {
	base := shape(t, `{"system":"s","tools":[{"name":"a"}],"messages":[1]}`)
	for name, body := range map[string]string{
		"other messages": `{"system":"s","tools":[{"name":"a"}],"messages":[{"role":"user"}]}`,
		"a model":        `{"model":"m","system":"s","tools":[{"name":"a"}],"messages":[1]}`,
		"max_tokens":     `{"max_tokens":5,"system":"s","tools":[{"name":"a"}],"messages":[1]}`,
		"key order":      `{"messages":[1],"tools":[{"name":"a"}],"system":"s"}`,
		"spacing":        `{"system": "s", "tools": [ {"name" : "a"} ]}`,
	} {
		if got := shape(t, body); got != base {
			t.Errorf("%s changed the shape hash", name)
		}
	}
}

func TestShapeSeesEveryOtherTopLevelField(t *testing.T) {
	base := shape(t, `{"system":"s","tools":[],"messages":[]}`)
	for name, body := range map[string]string{
		"system":        `{"system":"t","tools":[],"messages":[]}`,
		"tools":         `{"system":"s","tools":[1],"messages":[]}`,
		"a new field":   `{"system":"s","tools":[],"messages":[],"temperature":1}`,
		"a missing one": `{"system":"s","messages":[]}`,
		"nested value":  `{"system":"s","tools":[{}],"messages":[]}`,
	} {
		if got := shape(t, body); got == base {
			t.Errorf("%s did not change the shape hash", name)
		}
	}
}

func TestShapeRefusesWhatIsNotAJSONObject(t *testing.T) {
	for _, body := range []string{"", "null", "[]", "nope"} {
		if _, err := pin.Shape([]byte(body)); err == nil {
			t.Errorf("Shape(%q) = nil error", body)
		}
	}
}
