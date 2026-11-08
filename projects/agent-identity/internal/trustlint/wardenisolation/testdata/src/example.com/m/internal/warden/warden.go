package warden // want package:"reaches example.com/m/internal/agent via example.com/m/internal/agent, example.com/m/internal/modelclient via example.com/m/internal/modelclient"

import (
	"example.com/m/internal/agent"       // want `R2: example.com/m/internal/warden may not import example.com/m/internal/agent`
	"example.com/m/internal/modelclient" // want `R2: example.com/m/internal/warden may not import example.com/m/internal/modelclient`
)

func Run() { agent.Run(); modelclient.Call() }
