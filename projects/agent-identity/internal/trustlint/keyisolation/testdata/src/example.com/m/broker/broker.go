package broker

// DotEnvPath is where the loader looks.
const DotEnvPath = ".env"

// Choice is the chosen provider, with its key.
type Choice struct {
	Name string
	Key  string
}

// Select reads the key.
func Select(name string) (Choice, error) { return Choice{Name: name, Key: "k"}, nil }

// WithDotEnv is the .env loader.
func WithDotEnv(path string) error { return nil }
