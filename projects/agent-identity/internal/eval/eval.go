// Package eval scores the Model client, reaching the Model through the Broker as
// model-eval, on hand-written cases: it loads
// them from JSONL, runs each several times, and aggregates per-category
// accuracy, retries, unstable cases, cost and the raw replies. It writes no
// Audit records and never touches the Model client's testdata.
package eval

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"

	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// Categories lists the case categories in report order.
var Categories = []string{"named", "self", "paraphrase", "no-proposal", "injection"}

// Case is one hand-written Eval case.
type Case struct {
	ID       string `json:"id"`
	Category string `json:"category"`
	Question string `json:"question"`
	// Accept lists the Proposals that pass, by exact match.
	Accept []modelclient.Proposal `json:"accept,omitempty"`
	// NoProposal makes a refusal or a text-only reply pass; any other failure
	// (provider error, stop reason, exhausted repair) still fails.
	NoProposal bool `json:"no_proposal,omitempty"`
	// ReportOnly cases are shown but don't count toward the bar.
	ReportOnly bool `json:"report_only,omitempty"`
}

// LoadCases reads JSONL cases, one per non-blank line, rejecting unknown
// fields, unknown categories, duplicate ids and cases with no passing outcome.
func LoadCases(r io.Reader) ([]Case, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	var cases []Case
	seen := map[string]bool{}
	for i, line := range bytes.Split(data, []byte("\n")) {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var c Case
		dec := json.NewDecoder(bytes.NewReader(line))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&c); err != nil {
			return nil, fmt.Errorf("eval: line %d: %w", i+1, err)
		}
		if err := c.validate(); err != nil {
			return nil, fmt.Errorf("eval: line %d: %w", i+1, err)
		}
		if seen[c.ID] {
			return nil, fmt.Errorf("eval: line %d: duplicate id %q", i+1, c.ID)
		}
		seen[c.ID] = true
		cases = append(cases, c)
	}
	return cases, nil
}

func (c Case) validate() error {
	known := false
	for _, k := range Categories {
		known = known || k == c.Category
	}
	switch {
	case c.ID == "":
		return errors.New("empty id")
	case !known:
		return fmt.Errorf("unknown category %q", c.Category)
	case c.Question == "":
		return errors.New("empty question")
	case len(c.Accept) == 0 && !c.NoProposal:
		return errors.New("a case needs accept or no_proposal")
	}
	return nil
}

// SVIDSource is the small Workload API interface the Eval fetches its JWT-SVID
// through: go-spiffe's workloadapi.JWTSource live, the stand-in in tests.
type SVIDSource interface {
	FetchJWTSVID(ctx context.Context, params jwtsvid.Params) (*jwtsvid.SVID, error)
}

// ClientConfig names the Broker the Eval calls. The Eval holds no provider key.
type ClientConfig struct {
	// BrokerURL is the Broker's base URL.
	BrokerURL string
	// Model is the model id to name in each request; the Broker checks it
	// against the Eval's Pin. Empty names none, which the Broker refuses.
	Model string
	// Source gives the Eval's JWT-SVIDs, fetched for the Broker's audience on
	// every request.
	Source SVIDSource
}

// NewClient builds the Model client for cfg, in Broker mode.
// projects/agent-identity/cmd/eval cannot import the Model client itself (trustlint R1).
func NewClient(cfg ClientConfig) (Proposer, error) {
	if cfg.Source == nil {
		return nil, errors.New("eval: a JWT-SVID source is required")
	}
	return modelclient.New(modelclient.Config{
		BaseURL: cfg.BrokerURL,
		Model:   cfg.Model,
		SVID: func(ctx context.Context) (wire.JWTSVID, error) {
			svid, err := cfg.Source.FetchJWTSVID(ctx, jwtsvid.Params{Audience: broker.ID.String()})
			if err != nil {
				return "", err
			}
			return wire.JWTSVID(svid.Marshal()), nil
		},
	})
}

// Proposer is the Model client's Propose.
type Proposer interface {
	Propose(ctx context.Context, question string) (modelclient.Result, error)
}

// RunResult is one run of one case.
type RunResult struct {
	Pass bool
	// Outcome is the Proposal as target/permission, or the failure code.
	Outcome string
	// Retries is the number of repair retries the run used.
	Retries int
	Cost    float64
	// Raw is every raw live reply, in order.
	Raw []string
	// Provider and Model are what the Broker reported for the run's last reply.
	Provider, Model string
}

// CaseResult is all runs of one case.
type CaseResult struct {
	Case Case
	Runs []RunResult
	// Unstable is true when the runs did not all end the same way.
	Unstable bool
}

// Tally counts runs.
type Tally struct {
	Passed, Total, Retries int
}

// Accuracy is Passed/Total, or 1 when nothing was counted.
func (t Tally) Accuracy() float64 {
	if t.Total == 0 {
		return 1
	}
	return float64(t.Passed) / float64(t.Total)
}

// Report is the result of an Eval run.
type Report struct {
	// Provider and Model are what the Broker reported serving the first reply
	// that named them; empty if the Broker never served one.
	Provider, Model string
	Runs            int
	Cases           []CaseResult
	// Categories counts only the cases that are not report-only.
	Categories map[string]Tally
	ReportOnly Tally
	Cost       float64
}

// Run asks every case `runs` times, one request at a time.
func Run(ctx context.Context, p Proposer, cases []Case, runs int) Report {
	rep := Report{Runs: runs, Categories: map[string]Tally{}}
	for _, c := range cases {
		cr := CaseResult{Case: c}
		for i := 0; i < runs; i++ {
			rr := runOnce(ctx, p, c)
			if rep.Provider == "" && rr.Provider != "" {
				rep.Provider, rep.Model = rr.Provider, rr.Model
			}
			cr.Runs = append(cr.Runs, rr)
			if rr.Outcome != cr.Runs[0].Outcome {
				cr.Unstable = true
			}
			rep.Cost += rr.Cost
			t := &Tally{}
			if c.ReportOnly {
				t = &rep.ReportOnly
			} else if existing, ok := rep.Categories[c.Category]; ok {
				t = &existing
			}
			t.Total++
			t.Retries += rr.Retries
			if rr.Pass {
				t.Passed++
			}
			if !c.ReportOnly {
				rep.Categories[c.Category] = *t
			}
		}
		rep.Cases = append(rep.Cases, cr)
	}
	return rep
}

func runOnce(ctx context.Context, p Proposer, c Case) RunResult {
	res, err := p.Propose(ctx, c.Question)
	rr := RunResult{Retries: max(len(res.Attempts)-1, 0)}
	for _, a := range res.Attempts {
		rr.Cost += a.Cost
		rr.Raw = append(rr.Raw, a.Raw)
		if a.Provider != "" {
			rr.Provider, rr.Model = a.Provider, a.Model
		}
	}
	if err == nil {
		rr.Outcome = res.Proposal.Target + "/" + res.Proposal.Permission
		for _, a := range c.Accept {
			rr.Pass = rr.Pass || a == res.Proposal
		}
		return rr
	}
	var f *modelclient.Failure
	if errors.As(err, &f) {
		rr.Outcome = string(f.Code)
		rr.Pass = c.NoProposal && (f.Code == modelclient.CodeRefusal || f.Code == modelclient.CodeTextOnly)
	} else {
		rr.Outcome = "error"
	}
	return rr
}

// Passed reports whether every category with counted runs reaches minAccuracy.
// A minAccuracy of 0 is report-only and always passes.
func (r Report) Passed(minAccuracy float64) bool {
	if minAccuracy <= 0 {
		return true
	}
	for _, t := range r.Categories {
		if t.Accuracy() < minAccuracy {
			return false
		}
	}
	return true
}

// ExitCode is 0 when the Eval passed and 1 when it did not.
func (r Report) ExitCode(minAccuracy float64) int {
	if r.Passed(minAccuracy) {
		return 0
	}
	return 1
}

// Write prints the report: the provider and model the Broker reported, accuracy per category, retries,
// unstable cases, total cost and every raw reply.
func (r Report) Write(w io.Writer, minAccuracy float64) {
	fmt.Fprintf(w, "provider: %s\nmodel: %s\nruns per case: %d\nmin accuracy: %.2f\n\n", orNone(r.Provider), orNone(r.Model), r.Runs, minAccuracy)
	fmt.Fprintln(w, "category      passed/runs  accuracy  retries")
	for _, k := range Categories {
		if t, ok := r.Categories[k]; ok {
			fmt.Fprintf(w, "%-13s %5d/%-5d  %7.1f%%  %d\n", k, t.Passed, t.Total, 100*t.Accuracy(), t.Retries)
		}
	}
	if t := r.ReportOnly; t.Total > 0 {
		fmt.Fprintf(w, "%-13s %5d/%-5d  %7.1f%%  %d  (report-only, not counted)\n", "multi-part", t.Passed, t.Total, 100*t.Accuracy(), t.Retries)
	}
	var unstable []string
	for _, c := range r.Cases {
		if c.Unstable {
			unstable = append(unstable, c.Case.ID)
		}
	}
	sort.Strings(unstable)
	fmt.Fprintf(w, "\nunstable cases: %s\n", orNone(strings.Join(unstable, ", ")))
	fmt.Fprintf(w, "total cost: $%.6f (%s)\n", r.Cost, orNone(r.Provider))
	verdict := "PASS"
	if !r.Passed(minAccuracy) {
		verdict = "FAIL"
	}
	fmt.Fprintf(w, "result: %s\n\nraw replies:\n", verdict)
	for _, c := range r.Cases {
		for i, rr := range c.Runs {
			status := "fail"
			if rr.Pass {
				status = "pass"
			}
			fmt.Fprintf(w, "- %s run %d: %s (%s, retries %d)\n", c.Case.ID, i+1, status, rr.Outcome, rr.Retries)
			for _, raw := range rr.Raw {
				fmt.Fprintf(w, "    %s\n", strings.TrimSpace(raw))
			}
		}
	}
}

func orNone(s string) string {
	if s == "" {
		return "none"
	}
	return s
}
