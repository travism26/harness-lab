package warden

import (
	"example.com/m/internal/agent"       // want `R2: example.com/m/internal/warden may not import example.com/m/internal/agent`
	"example.com/m/internal/modelclient" // want `R2: example.com/m/internal/warden may not import example.com/m/internal/modelclient`
)

func Run() { agent.Run(); modelclient.Call() }
