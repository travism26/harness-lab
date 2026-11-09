package broker_test

import (
	"example.com/m/internal/warden" // want `R2: example.com/m/internal/broker may not import example.com/m/internal/warden; the Broker must not depend on it`
)

func helper() { warden.Run() }
