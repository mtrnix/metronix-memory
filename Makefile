.PHONY: setup dev test lint migrate docker-up docker-down clean test-installer verify-checksum update-checksum prepare-release eval eval-all eval-save eval-compare eval-history grid-search

setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[connectors,channels,dev]"
	cp -n .env.example .env 2>/dev/null || true

dev:
	.venv/bin/uvicorn metatron.api.app:create_app --factory --reload --port 8000

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
	.venv/bin/mypy src/metatron/

migrate:
	.venv/bin/alembic upgrade head

migrate-new:
	.venv/bin/alembic revision --autogenerate -m "$(name)"

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f metatron

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

grid-search:
	.venv/bin/python scripts/grid_search_weights.py --workspace $(or $(WORKSPACE),MTRNIX) --step 0.10

# ============================================================================
# Installer Distribution Targets
# ============================================================================

test-installer:
	bash -n install.sh

verify-checksum:
	sha256sum -c .sha256sum

update-checksum:
	sha256sum install.sh > .sha256sum

prepare-release: test-installer verify-checksum
	@echo "✓ Installer ready for release"
