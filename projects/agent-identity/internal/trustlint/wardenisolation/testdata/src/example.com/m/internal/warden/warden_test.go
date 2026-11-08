package warden_test

import (
	"example.com/m/internal/agent" // want `R2: example.com/m/internal/warden may not import example.com/m/internal/agent`
)

func helper() { agent.Run() }
