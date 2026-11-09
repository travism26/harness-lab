package viabrokerhelper // want package:"reaches example.com/m/internal/broker via example.com/m/internal/usesbroker -> example.com/m/internal/broker"

import (
	"example.com/m/internal/usesbroker" // want `R2: example.com/m/internal/warden/viabrokerhelper may not import example.com/m/internal/usesbroker, which reaches example.com/m/internal/broker \(example.com/m/internal/usesbroker -> example.com/m/internal/broker\)`
)

func Run() { usesbroker.Run() }
