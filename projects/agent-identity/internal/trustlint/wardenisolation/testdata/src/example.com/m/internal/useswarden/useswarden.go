package useswarden // want package:"reaches example.com/m/internal/warden via example.com/m/internal/warden"

import "example.com/m/internal/warden"

func Run() { warden.Run() }
