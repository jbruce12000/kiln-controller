VENV := venv
PYTHON := $(VENV)/bin/python3

.PHONY: test lint dev-setup

test:
	uv run pytest Test -q

lint:
	uv run ruff check .

dev-setup:
	UV_PROJECT_ENVIRONMENT=$(VENV) uv sync
