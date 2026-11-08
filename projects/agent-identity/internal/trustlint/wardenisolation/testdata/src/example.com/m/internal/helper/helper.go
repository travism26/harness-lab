package helper // want package:"reaches example.com/m/internal/agent via example.com/m/internal/agent"

import "example.com/m/internal/agent"

func Do() { agent.Run() }
