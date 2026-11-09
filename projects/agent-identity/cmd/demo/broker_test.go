package main

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelrequest"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// A token minted for one hop fails at the other: the Agent's Warden token is
// refused by the Broker, and its Broker token by the Warden. Both refuse on the
// audience, with the same reason code, and the Broker makes no provider request.
func TestCrossAudienceTokensFailAtTheOtherHop(t *testing.T) {
	ids, err := newStandInIdentities()
	if err != nil {
		t.Fatal(err)
	}
	defer ids.Close()
	sink, err := openAudit(filepath.Join(t.TempDir(), "run"), false)
	if err != nil {
		t.Fatal(err)
	}
	defer sink.close()
	e, stop, err := setup(slog.New(slog.NewTextHandler(io.Discard, nil)), options{ids: ids, audit: sink})
	if err != nil {
		t.Fatal(err)
	}
	defer stop()
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	b, err := broker.New(broker.Config{Audience: brokerAud, Bundles: ids.Bundles(), Provider: provider.StandIn, UpstreamURL: m.URL, Audit: sink.broker, Pins: map[spiffeid.ID]pin.Pin{permissionAgent: pin.Agent()}})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	defer srv.Close()

	wl, err := ids.Workload(permissionAgent)
	if err != nil {
		t.Fatal(err)
	}
	token := func(aud string) wire.Bearer {
		svid, err := wl.FetchJWTSVID(context.Background(), jwtsvid.Params{Audience: aud})
		if err != nil {
			t.Fatal(err)
		}
		return wire.BearerFor(wire.JWTSVID(svid.Marshal()))
	}
	post := func(url, path string, auth wire.Bearer, assertion wire.CallerAssertion) (int, string) {
		body := `{"target":"acme/tom","permission":"invoice:approve"}`
		if path == wire.PathMessages {
			raw, err := modelrequest.Body(question)
			if err != nil {
				t.Fatal(err)
			}
			body = string(raw)
		}
		req, _ := http.NewRequest(http.MethodPost, url+path, strings.NewReader(body))
		req.Header.Set(wire.HeaderAuthorization, string(auth))
		if assertion != "" {
			req.Header.Set(wire.HeaderCallerAssertion, string(assertion))
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		raw, _ := io.ReadAll(resp.Body)
		return resp.StatusCode, string(raw)
	}
	assertion, err := e.login.Sign("acme/alice", wardenAud, permissionAgent.String())
	if err != nil {
		t.Fatal(err)
	}

	status, body := post(srv.URL, wire.PathMessages, token(wardenAud), "")
	if status != http.StatusUnauthorized || !strings.Contains(body, `"jwt_svid_audience"`) {
		t.Errorf("the Warden's token at the Broker: %d %s; want 401 jwt_svid_audience", status, body)
	}
	if n := len(m.Requests()); n != 0 {
		t.Errorf("the Model saw %d requests after a wrong-audience token", n)
	}
	status, _ = post(e.url, wire.PathLookup, token(brokerAud), assertion)
	if d := e.lastDecision(); status != http.StatusUnauthorized || d.Reason != "jwt_svid_audience" {
		t.Errorf("the Broker's token at the Warden: %d, reason %q; want 401 jwt_svid_audience", status, d.Reason)
	}
	// Each token works at its own hop.
	if status, _ = post(srv.URL, wire.PathMessages, token(brokerAud), ""); status != http.StatusOK {
		t.Errorf("the Broker's token at the Broker: %d; want 200", status)
	}
	if status, _ = post(e.url, wire.PathLookup, token(wardenAud), assertion); status != http.StatusOK {
		t.Errorf("the Warden's token at the Warden: %d; want 200", status)
	}
}

// The tour's ask goes through a loopback Broker: the footer says so.
func TestTourAskShowsTheBrokerHop(t *testing.T) {
	var out, errOut strings.Builder
	if code := run([]string{"ask", question, "--out", t.TempDir()}, &out, &errOut); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut.String())
	}
	if !strings.Contains(out.String(), "[model: stand-in via broker · id ") || !strings.Contains(errOut.String(), `msg="broker listening"`) {
		t.Errorf("stdout %q\nstderr %s", out.String(), errOut.String())
	}
}
