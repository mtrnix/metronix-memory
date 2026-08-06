.PHONY: setup dev test lint migrate docker-up docker-down clean test-installer prepare-release eval eval-all eval-save eval-compare eval-history memory-eval grid-search graph-rebuild graph-rebuild-dry graph-process bench-lme-setup bench-lme-smoke bench-lme bench-watch uninstall

setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[connectors,channels,dev]"
	cp -n .env.example .env 2>/dev/null || true

dev:
	.venv/bin/uvicorn metronix.api.app:create_app --factory --reload --port 8000

test:
	.venv/bin/pytest tests/ -v --tb=short -m "not integration"

test-all:
	.venv/bin/pytest tests/ -v --tb=short

lint:
	.venv/bin/ruff check src/ tests/
	.venv/bin/ruff format --check src/ tests/

format:
	.venv/bin/ruff check --fix src/ tests/
	.venv/bin/ruff format src/ tests/

typecheck:
	.venv/bin/mypy src/metronix/

migrate:
	.venv/bin/alembic upgrade head

migrate-new:
	.venv/bin/alembic revision --autogenerate -m "$(name)"

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

uninstall:
	./uninstall.sh

docker-logs:
	docker compose logs -f

clean:
	rm -rf .venv dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

# ============================================================================
# Search Quality Eval
# ============================================================================

eval:
	.venv/bin/python scripts/run_eval.py --workspace $(or $(WORKSPACE),MTRNIX)

eval-all:
	.venv/bin/python scripts/run_eval.py --workspace $(or $(WORKSPACE),MTRNIX) --all

eval-save:
	.venv/bin/python scripts/run_eval.py --workspace $(or $(WORKSPACE),MTRNIX) --save

eval-compare:
	.venv/bin/python scripts/run_eval.py --workspace $(or $(WORKSPACE),MTRNIX) --compare

eval-history:
	.venv/bin/python scripts/run_eval.py --history

memory-eval:
	.venv/bin/python scripts/run_memory_eval.py $(MEMORY_EVAL_ARGS)

grid-search:
	.venv/bin/python scripts/grid_search_weights.py --workspace $(or $(WORKSPACE),MTRNIX) --step 0.10

grid-search-cache:
	.venv/bin/python scripts/grid_search_weights.py --cache --workspace $(or $(WORKSPACE),MTRNIX)

grid-search-fine:
	.venv/bin/python scripts/grid_search_weights.py --workspace $(or $(WORKSPACE),MTRNIX) --step 0.05

graph-rebuild:
	.venv/bin/python scripts/graph_rebuild.py --workspace $(or $(WORKSPACE),MTRNIX)

graph-rebuild-dry:
	.venv/bin/python scripts/graph_rebuild.py --workspace $(or $(WORKSPACE),MTRNIX) --dry-run

graph-process:
	.venv/bin/python scripts/graph_process.py --workspace $(or $(WORKSPACE),MTRNIX)

# ============================================================================
# Installer
# ============================================================================

test-installer:
	bash -n install.sh
	bash -n uninstall.sh
	bash -n scripts/install-bootstrap.sh
	bash tests/installer/test_bootstrap.sh
	bash tests/installer/test_uninstall.sh
	shellcheck install.sh uninstall.sh
	shellcheck scripts/install-bootstrap.sh tests/installer/test_bootstrap.sh tests/installer/test_uninstall.sh

prepare-release: test-installer
	@echo "✓ Installer ready for release"

# ============================================================================
# LongMemEval agent-memory benchmark
# ============================================================================

bench-lme-setup:
	bash benchmarks/longmemeval/setup.sh

bench-lme-smoke:
	bash benchmarks/longmemeval/run.sh --smoke

bench-lme:
	bash benchmarks/longmemeval/run.sh

bench-watch:
	@if [ -z "$(RESULTS)" ]; then echo "Usage: make bench-watch RESULTS=benchmarks/longmemeval/results/<file>.jsonl"; exit 1; fi
	benchmarks/longmemeval/.venv/bin/python benchmarks/longmemeval/scripts/watch_progress.py "$(RESULTS)"
