package warden

// seedUser is what the Warden knows about one User.
type seedUser struct {
	Role string
}

// seedUsers is the Seed data: every User the Warden knows, by tenant/name id,
// with their one Role.
var seedUsers = map[string]seedUser{
	"acme/alice": {Role: "Access Auditor"},
	"acme/tom":   {Role: "Finance Approver"},
	"acme/bob":   {Role: "Employee"},
	"globex/tom": {Role: "Finance Approver"},
	"globex/sam": {Role: "Access Auditor"},
}
