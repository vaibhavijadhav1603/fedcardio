# On Windows run these from Git Bash (make via `choco install make` or use the commands directly).
PY ?= .venv/Scripts/python
ifeq ($(OS),)
PY = .venv/bin/python
endif

.PHONY: setup data test lint reproduce figures up down

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.lock

data:
	$(PY) -m fl_engine.data.download

test:
	$(PY) -m pytest -q --cov=fl_engine --cov-report=term-missing

lint:
	$(PY) -m ruff check fl_engine experiments tests

# filled in Phase 1/2
reproduce: data
	@echo "experiment pipeline added in Phase 1"

figures:
	@echo "figure pipeline added in Phase 2"

up:
	docker compose up -d --build

down:
	docker compose down
