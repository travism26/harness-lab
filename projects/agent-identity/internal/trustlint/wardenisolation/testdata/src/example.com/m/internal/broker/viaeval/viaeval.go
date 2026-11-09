package viaeval // want package:"reaches example.com/m/internal/eval via example.com/m/internal/eval, example.com/m/internal/modelclient via example.com/m/internal/eval -> example.com/m/internal/modelclient"

import (
	"example.com/m/internal/eval" // want `R2: example.com/m/internal/broker/viaeval may not import example.com/m/internal/eval; the Broker must not depend on it`
)

func Run() { eval.Do() }
