package warden_test

import (
	"bytes"
	"encoding/json"
	"strings"
	"sync"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// syncBuffer is an audit sink safe for the Warden's handler goroutines.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// records decodes the Audit log strictly: an unknown field fails the test.
func (f *fixture) records(t *testing.T) []warden.AuditRecord {
	t.Helper()
	var out []warden.AuditRecord
	for _, line := range strings.Split(strings.TrimSpace(f.audit.String()), "\n") {
		if line == "" {
			continue
		}
		dec := json.NewDecoder(strings.NewReader(line))
		dec.DisallowUnknownFields()
		var r warden.AuditRecord
		if err := dec.Decode(&r); err != nil {
			t.Fatalf("audit line %q: %v", line, err)
		}
		out = append(out, r)
	}
	return out
}

const goodID = "0123456789abcdef0123456789abcdef"

func TestYesIsAuditedAndTheCorrelationIDEchoed(t *testing.T) {
	f := newFixture(t)
	f.header.Set(wire.HeaderCorrelationID, goodID)

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t))

	if got.header.Get(wire.HeaderCorrelationID) != goodID {
		t.Errorf("echoed %q; want %q", got.header.Get(wire.HeaderCorrelationID), goodID)
	}
	recs := f.records(t)
	if len(recs) != 1 {
		t.Fatalf("got %d records; want 1", len(recs))
	}
	r := recs[0]
	if r.CorrelationID != goodID || r.Status != 200 || r.Outcome != warden.OutcomeAnswerYes ||
		r.Agent != agentID.String() || r.Caller != "acme/alice" ||
		r.Target != "acme/tom" || r.Permission != "invoice:approve" || r.Role != "Finance Approver" ||
		r.FailedCheck != "" || r.Reason != "" || r.RejectedCorrelationIDLen != nil || r.TS.IsZero() {
		t.Errorf("record = %+v", r)
	}
}

func TestMalformedCorrelationIDIsReplacedAndOnlyItsLengthRecorded(t *testing.T) {
	for _, bad := range []string{"SECRET-not-hex", strings.ToUpper(goodID), goodID + "0", "abc"} {
		f := newFixture(t)
		f.header.Set(wire.HeaderCorrelationID, bad)
		got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t))

		echoed := got.header.Get(wire.HeaderCorrelationID)
		if echoed == bad || len(echoed) != 32 || strings.ToLower(echoed) != echoed {
			t.Errorf("%q: echoed %q, want a minted 32-char lowercase ID", bad, echoed)
		}
		recs := f.records(t)
		if len(recs) != 1 || recs[0].CorrelationID != echoed {
			t.Fatalf("%q: records %+v; echoed %q", bad, recs, echoed)
		}
		if n := recs[0].RejectedCorrelationIDLen; n == nil || *n != len(bad) {
			t.Errorf("%q: rejected length %v; want %d", bad, n, len(bad))
		}
		if strings.Contains(f.audit.String(), bad) {
			t.Errorf("%q: the rejected value is in the log", bad)
		}
	}
}

func TestMissingCorrelationIDIsMintedWithoutARejectedLength(t *testing.T) {
	f := newFixture(t)
	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t))
	recs := f.records(t)
	if len(recs) != 1 || recs[0].CorrelationID != got.header.Get(wire.HeaderCorrelationID) || len(recs[0].CorrelationID) != 32 || recs[0].RejectedCorrelationIDLen != nil {
		t.Errorf("records %+v", recs)
	}
}

func TestAgentAndCallerAppearOnlyOnceTheirTokenVerified(t *testing.T) {
	f := newFixture(t)
	good := wire.BearerFor(f.fetch(t, agentID, wardenAudience))

	f.post(t, "", f.valid(t))
	f.post(t, wire.BearerFor(f.fetch(t, unlistedID, wardenAudience)), f.valid(t))
	f.post(t, good, "")
	f.post(t, good, f.valid(t))
	f.postLookup(t, good, f.valid(t), wire.LookupRequest{Target: "globex/sam", Permission: "permission:read"})

	recs := f.records(t)
	if len(recs) != 5 {
		t.Fatalf("got %d records; want 5", len(recs))
	}
	type want struct {
		outcome       warden.Outcome
		check         warden.FailedCheck
		reason        warden.Reason
		agent, caller bool
	}
	for i, w := range []want{
		{warden.OutcomeUnauthenticated, warden.CheckJWTSVID, warden.ReasonJWTSVIDMissing, false, false},
		{warden.OutcomeAgentNotAllowed, warden.CheckAllowlist, "", true, false},
		{warden.OutcomeUnauthenticated, warden.CheckCallerAssertion, warden.ReasonAssertionMissing, true, false},
		{warden.OutcomeAnswerYes, "", "", true, true},
		{warden.OutcomeDenial, warden.CheckLookup, "", true, true},
	} {
		r := recs[i]
		if r.Outcome != w.outcome || r.FailedCheck != w.check || r.Reason != w.reason || (r.Agent != "") != w.agent || (r.Caller != "") != w.caller {
			t.Errorf("record %d = %+v", i, r)
		}
	}
}

func TestEveryResponseHasExactlyOneRecordByCorrelationID(t *testing.T) {
	f := newFixture(t)
	good := wire.BearerFor(f.fetch(t, agentID, wardenAudience))
	ids := map[string]bool{}
	for _, got := range []response{
		f.post(t, "", ""),
		f.post(t, good, ""),
		f.post(t, good, f.valid(t)),
		f.postLookup(t, good, f.valid(t), wire.LookupRequest{Target: "acme/tom", Permission: "nope:nope"}),
	} {
		ids[got.header.Get(wire.HeaderCorrelationID)] = true
	}
	counts := map[string]int{}
	for _, r := range f.records(t) {
		counts[r.CorrelationID]++
	}
	if len(ids) != 4 || len(counts) != 4 {
		t.Fatalf("ids %v, counts %v", ids, counts)
	}
	for id := range ids {
		if counts[id] != 1 {
			t.Errorf("%s has %d records", id, counts[id])
		}
	}
}
