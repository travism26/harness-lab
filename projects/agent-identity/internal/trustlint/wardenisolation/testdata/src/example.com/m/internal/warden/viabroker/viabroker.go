package viabroker // want package:"reaches example.com/m/internal/broker via example.com/m/internal/broker"

import (
	"example.com/m/internal/broker" // want `R2: example.com/m/internal/warden/viabroker may not import example.com/m/internal/broker; the Warden must not depend on it`
)

func Run() { broker.Run() }
