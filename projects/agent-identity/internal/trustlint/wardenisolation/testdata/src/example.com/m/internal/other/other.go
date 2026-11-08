package other // want package:"reaches example.com/m/internal/agent via example.com/m/internal/agent"

import "example.com/m/internal/agent"

func Run() { agent.Run() }
