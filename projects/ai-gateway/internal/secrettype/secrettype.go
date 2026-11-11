// Package secrettype holds the analyzer that will keep a credential out of the
// Call record and the logs. The rule is not written yet: the analyzer reports
// nothing.
package secrettype

import "golang.org/x/tools/go/analysis"

// Analyzer is the secret-type analyzer. It reports nothing yet.
var Analyzer = &analysis.Analyzer{
	Name: "secrettype",
	Doc:  "reports a secret type reaching a log or a Call record (rule not written yet)",
	Run:  func(*analysis.Pass) (any, error) { return nil, nil },
}
