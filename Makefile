PYTHON ?= venv/bin/python3

.PHONY: test lint dev-setup

test:
	$(PYTHON) -m pytest Test -q

lint:
	$(PYTHON) -m ruff check .

dev-setup:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt
