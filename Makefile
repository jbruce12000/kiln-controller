VENV := venv
SYSTEM_PYTHON := /usr/bin/python3
PYTHON := $(VENV)/bin/python3
UV := uv
MIN_PYTHON := 10
MAX_PYTHON := 14
SWIG_MIN := 12
SHELL := /bin/bash

.PHONY: prerequisites venv install test lint dev-setup

prerequisites:
	@python_version=$$( $(SYSTEM_PYTHON) -c 'import sys; print(sys.version_info[1])' ); \
	if [ $$python_version -ge $(MIN_PYTHON) ] && [ $$python_version -le $(MAX_PYTHON) ]; then \
		if [ $$python_version -gt $(SWIG_MIN) ]; then \
			sudo apt update; \
			sudo apt install swig liblgpio-dev; \
		fi; \
	else \
		echo "Your python version is 3.$$python_version but we support >=3.$(MIN_PYTHON),<=3.$(MAX_PYTHON) only."; \
		exit 1; \
	fi

venv: prerequisites
	$(SYSTEM_PYTHON) -m venv $(VENV); \
	source $(VENV)/bin/activate; \

install: venv
	$(VENV)/bin/pip install -e .

test:
	$(UV) run pytest Test -q

lint:
	$(UV) run ruff check .

dev-setup: install
	@if ! command -v uv >/dev/null 2>&1; then \
		wget -qO- https://astral.sh/uv/install.sh | sh; \
	fi; \
	$(VENV)/bin/pip install --upgrade pip; \
	UV_PROJECT_ENVIRONMENT=$(VENV) $$HOME/.local/bin/uv sync --python $(VENV)/bin/python
	@echo -e "\n\nDevelopment environment is successfully installed!\nYou might have to restart your shell to use uv."
