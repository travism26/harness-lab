package main

import (
	"example.com/m/internal/eval" // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/eval; the Broker must not depend on it`
)

func helperForTest() { eval.Do() }
