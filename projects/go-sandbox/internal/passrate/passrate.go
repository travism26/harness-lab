// Package passrate holds the Pass rate: how many Stages passed out of how many.
package passrate

import (
	"fmt"
	"math/bits"
)

// Rate is a pair of counts with 0 <= passed <= total and total >= 1.
type Rate struct {
	passed, total int
}

// New returns the Rate for passed out of total, or an error when the pair is
// not a valid Pass rate.
func New(passed, total int) (Rate, error) {
	if total < 1 {
		return Rate{}, fmt.Errorf("total must be at least 1: %d", total)
	}
	if passed < 0 || passed > total {
		return Rate{}, fmt.Errorf("passed must be between 0 and total: %d of %d", passed, total)
	}
	return Rate{passed: passed, total: total}, nil
}

// Passed returns the count that passed.
func (r Rate) Passed() int { return r.passed }

// Total returns the count of all.
func (r Rate) Total() int { return r.total }

// Percent returns the whole-number percentage, rounded half up. The
// intermediate value is 128 bits wide, so no pair of counts overflows it.
func (r Rate) Percent() int {
	p, t := uint64(r.passed), uint64(r.total)
	hi, lo := bits.Mul64(p, 200)
	lo, carry := bits.Add64(lo, t, 0)
	q, _ := bits.Div64(hi+carry, lo, 2*t)
	return int(q)
}
