VENV := venv
PYTHON := $(VENV)/bin/python3
UV := uv

.PHONY: test lint dev-setup

test:
	$(UV) run pytest Test -q

lint:
	$(UV) run ruff check .

dev-setup:
	UV_PROJECT_ENVIRONMENT=$(VENV) $(UV) sync
