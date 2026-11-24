package redact

import (
	"bytes"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

// Failure messages in this file never print a record, a body or a matched
// string: they print booleans, kinds, counts and line numbers.

// fakeMarker is in every fake secret of the fixtures.
const fakeMarker = "FIXTUREONLY"

func decodeLines(t *testing.T, data []byte) []map[string]any {
	t.Helper()
	var recs []map[string]any
	for i, line := range bytes.Split(bytes.TrimSuffix(data, []byte("\n")), []byte("\n")) {
		var rec map[string]any
		dec := json.NewDecoder(bytes.NewReader(line))
		dec.UseNumber()
		if err := dec.Decode(&rec); err != nil {
			t.Fatalf("line %d is not valid JSON", i+1)
		}
		recs = append(recs, rec)
	}
	return recs
}

func streamFixture(t *testing.T, name string) (in, out []byte, counts Counts) {
	t.Helper()
	in, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	counts, err = Stream(bytes.NewReader(in), &buf)
	if err != nil {
		t.Fatalf("Stream: %v", err)
	}
	return in, buf.Bytes(), counts
}

func TestSecretsFixtureIsRedacted(t *testing.T) {
	in, out, counts := streamFixture(t, "with-secrets.jsonl")

	if !bytes.Contains(in, []byte(fakeMarker)) {
		t.Fatal("fixture lost its fake secrets; the test would prove nothing")
	}
	if bytes.Contains(out, []byte(fakeMarker)) {
		t.Fatal("output still contains a fake secret")
	}

	// Counted by hand from the fixture: one sk-ant- key (record 1), two
	// Bearer values (record 2), one PEM block (record 3), one x-api-key value
	// (record 4), one sk-ant-oat token and one access_token value (record 4).
	want := Counts{"anthropic-key": 1, "bearer": 2, "pem": 1, "header": 1, "oauth": 2}
	if !reflect.DeepEqual(counts, want) {
		t.Fatalf("counts = %v, want %v", counts, want)
	}
	for kind := range want {
		if !bytes.Contains(out, []byte("[REDACTED:"+kind+"]")) {
			t.Errorf("tag for kind %q is missing from the output", kind)
		}
	}
}

func TestSecretsFixtureKeepsEverythingElse(t *testing.T) {
	in, out, _ := streamFixture(t, "with-secrets.jsonl")
	inRecs, outRecs := decodeLines(t, in), decodeLines(t, out)
	if len(inRecs) != len(outRecs) {
		t.Fatalf("%d records in, %d out", len(inRecs), len(outRecs))
	}
	for i := range inRecs {
		a, b := inRecs[i], outRecs[i]
		bodyChanged := false
		for _, f := range []string{"request_body", "response_body"} {
			bodyChanged = bodyChanged || a[f] != b[f]
			delete(a, f)
			delete(b, f)
		}
		if !reflect.DeepEqual(a, b) {
			t.Errorf("record %d: a non-body field changed (order or value)", i+1)
		}
		// Every record of this fixture holds at least one secret.
		if !bodyChanged {
			t.Errorf("record %d: no body changed", i+1)
		}
	}
}

func TestBodiesThatAreJSONStayJSON(t *testing.T) {
	_, out, _ := streamFixture(t, "with-secrets.jsonl")
	recs := decodeLines(t, out)
	// Record 3's request body is JSON text holding a PEM block.
	body, _ := recs[2]["request_body"].(string)
	var inner map[string]any
	if err := json.Unmarshal([]byte(body), &inner); err != nil {
		t.Fatal("request_body of record 3 is no longer valid JSON")
	}
	if inner["file"] != "[REDACTED:pem]" {
		t.Error("the PEM block was not replaced as one value")
	}
	if !strings.Contains(inner["after"].(string), "BODYTEXT-THREE") {
		t.Error("text after the PEM block was lost")
	}
}

func TestNoSecretsFixtureIsUnchanged(t *testing.T) {
	in, out, counts := streamFixture(t, "no-secrets.jsonl")
	if len(counts) != 0 {
		t.Fatalf("counts = %v, want none", counts)
	}
	if !reflect.DeepEqual(decodeLines(t, in), decodeLines(t, out)) {
		t.Fatal("a record changed meaning")
	}
}

func TestStringsNestedInAnyValueAreRedacted(t *testing.T) {
	in := `{"a":["x",{"b":"Bearer FIXTUREONLYnested00000"}],"n":12345678901234567890,"f":true,"z":null,"s":"sk-ant-api03-FIXTUREONLYtop0000"}` + "\n"
	var out bytes.Buffer
	counts, err := Stream(strings.NewReader(in), &out)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(out.Bytes(), []byte(fakeMarker)) {
		t.Error("a nested string kept its fake secret")
	}
	if counts["bearer"] != 1 || counts["anthropic-key"] != 1 {
		t.Errorf("counts = %v", counts)
	}
	rec := decodeLines(t, out.Bytes())[0]
	if rec["n"] != json.Number("12345678901234567890") || rec["f"] != true || rec["z"] != nil {
		t.Error("a non-string value changed")
	}
}

func TestPatterns(t *testing.T) {
	cases := []struct {
		name, in, wantKind string // wantKind "" means unchanged
	}{
		{"api key", "x sk-ant-api03-FIXTUREONLYabcdef y", "anthropic-key"},
		{"api key short", "sk-ant-abc", ""},
		{"env assignment", `ANTHROPIC_API_KEY="FIXTUREONLYenvvalue000"`, "anthropic-key"},
		{"escaped env assignment", `ANTHROPIC_API_KEY=\"FIXTUREONLYenvvalue000\"`, "anthropic-key"},
		{"oauth token", "sk-ant-oat01-FIXTUREONLYabcdef", "oauth"},
		{"refresh token", "sk-ant-ort01-FIXTUREONLYabcdef", "oauth"},
		{"oauth json field", `{"refresh_token":"FIXTUREONLYrefresh0"}`, "oauth"},
		{"escaped oauth json field", `{\"refresh_token\":\"FIXTUREONLYrefresh0\"}`, "oauth"},
		{"jwt shaped", "eyJFIXTURE.eyJONLYFIX.sigFIXT", "oauth"},
		{"bearer", "Bearer FIXTUREONLYtoken123", "bearer"},
		{"bearer lower case", "bearer FIXTUREONLYtoken123", "bearer"},
		{"bearer prose", "bearer authentication is common", ""},
		{"bearer too short", "Bearer abc1", ""},
		{"pem", "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----", "pem"},
		{"pem escaped newlines", `-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----`, "pem"},
		{"pem unterminated", "-----BEGIN PRIVATE KEY-----\nFAKE", "pem"},
		{"public key is kept", "-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----", ""},
		{"authorization header", "Authorization: Basic FIXTUREONLYbasic000", "header"},
		{"x-api-key header", "x-api-key: FIXTUREONLYkey00000", "header"},
		{"authorization with bearer", "Authorization: Bearer FIXTUREONLYtoken123", "bearer"},
		{"plain text", "nothing to see, 12345 and sk- and Bearer", ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			counts := Counts{}
			got := String(c.in, counts)
			if c.wantKind == "" {
				if got != c.in || len(counts) != 0 {
					t.Fatalf("text changed or counted: counts=%v", counts)
				}
				return
			}
			if strings.Contains(got, fakeMarker) {
				t.Error("fake secret survived")
			}
			if counts[c.wantKind] != 1 || len(counts) != 1 {
				t.Errorf("counts = %v, want exactly one %q", counts, c.wantKind)
			}
			if !strings.Contains(got, "[REDACTED:"+c.wantKind+"]") {
				t.Error("tag missing")
			}
		})
	}
}

func TestInvalidLineErrorNamesNoContent(t *testing.T) {
	in := `{"ok":1}` + "\n" + `{"leak": "SECRETISH-TEXT"` + "\n"
	_, err := Stream(strings.NewReader(in), &bytes.Buffer{})
	if err == nil {
		t.Fatal("want an error")
	}
	if strings.Contains(err.Error(), "SECRETISH") || !strings.Contains(err.Error(), "line 2") {
		t.Errorf("error should name line 2 and no content: %q", "line-number check")
	}
}

func TestBlankLinesSkippedAndNoTrailingNewlineRead(t *testing.T) {
	var out bytes.Buffer
	if _, err := Stream(strings.NewReader("\n{\"a\":\"b\"}\n\n{\"c\":1}"), &out); err != nil {
		t.Fatal(err)
	}
	if got := out.String(); got != "{\"a\":\"b\"}\n{\"c\":1}\n" {
		t.Errorf("output has %d bytes, unexpected shape", len(got))
	}
}
