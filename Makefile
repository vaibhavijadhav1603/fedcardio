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

# Phase 1: centralised baselines (~45 min on 16 cores). Phase 2 targets are appended later.
reproduce: data
	$(PY) -m experiments.run_centralized --dataset uci --repeats 5 --folds 5 --budget 20
	$(PY) -m experiments.run_centralized --dataset cardio --repeats 2 --folds 5 --budget 20
	$(PY) -m experiments.run_centralized --dataset cardio_lowprev --repeats 2 --folds 5 --budget 20
	$(PY) -m experiments.make_tables

figures:
	@echo "figure pipeline added in Phase 2"

up:
	docker compose up -d --build

down:
	docker compose down
