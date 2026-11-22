// Package httpapi is the service's HTTP surface: one endpoint, GET /pass-rate.
package httpapi

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/travism26/harness-lab/projects/go-sandbox/internal/passrate"
)

type response struct {
	Passed  int `json:"passed"`
	Total   int `json:"total"`
	Percent int `json:"percent"`
}

// Handler returns the service's handler.
func Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /pass-rate", passRate)
	return mux
}

func passRate(w http.ResponseWriter, r *http.Request) {
	passed, err := strconv.Atoi(r.URL.Query().Get("passed"))
	if err != nil {
		http.Error(w, "passed must be an integer", http.StatusBadRequest)
		return
	}
	total, err := strconv.Atoi(r.URL.Query().Get("total"))
	if err != nil {
		http.Error(w, "total must be an integer", http.StatusBadRequest)
		return
	}
	rate, err := passrate.New(passed, total)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(response{rate.Passed(), rate.Total(), rate.Percent()})
}
