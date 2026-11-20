# Run from experiments/clickhouse-podcast-analytics/.
CH := docker compose exec -T clickhouse clickhouse-client --multiquery

.PHONY: up generate queries bench all down

up:
	docker compose up -d --wait

generate:
	python3 scripts/generate.py

queries:
	@for f in queries/*.sql; do \
	  printf -- '--- %s\n' "$$f"; \
	  $(CH) < "$$f" || exit 1; \
	done

bench:
	python3 scripts/bench.py

all: up generate queries bench

down:
	docker compose down -v
