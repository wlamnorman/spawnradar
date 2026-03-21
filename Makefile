.PHONY: install check lint test typecheck run help deploy set-fly-secrets-production grant-comp-production

PYTHON  := .venv/bin/python
UVICORN := .venv/bin/uvicorn
PYTEST  := .venv/bin/pytest
RUFF    := .venv/bin/ruff
BASEDPYRIGHT := .venv/bin/basedpyright

HOST := 0.0.0.0
PORT := 8000
URL  := http://localhost:$(PORT)
START_URL := $(URL)/auth/dev-login

install:
	pip3 install -r dev-requirements.txt
	pip3 install -r requirements.txt

check: lint typecheck test


lint:
	$(RUFF) check app tests --fix

test:
	$(PYTEST)

typecheck:
	$(BASEDPYRIGHT)

deploy:
	@set -e; \
	if ! command -v flyctl >/dev/null 2>&1; then \
		echo "flyctl is not installed. Install it first: brew install flyctl"; \
		exit 1; \
	fi; \
	exec flyctl deploy --ha=false --strategy immediate

## Import secrets from .env.production into Fly app spawnradar
set-fly-secrets-production:
	@set -e; \
	if ! command -v flyctl >/dev/null 2>&1; then \
		echo "flyctl is not installed. Install it first: brew install flyctl"; \
		exit 1; \
	fi; \
	if [ ! -f ".env.production" ]; then \
		echo "Env file not found: .env.production"; \
		exit 1; \
	fi; \
	flyctl secrets import -a spawnradar < .env.production

## Grant complimentary production access. Usage: make grant-comp-production EMAILS="you@example.com friend@example.com" [SEND_RESET=1]
grant-comp-production:
	@set -e; \
	if ! command -v flyctl >/dev/null 2>&1; then \
		echo "flyctl is not installed. Install it first: brew install flyctl"; \
		exit 1; \
	fi; \
	if [ -z "$(EMAILS)" ]; then \
		echo 'Usage: make grant-comp-production EMAILS="you@example.com friend@example.com" [SEND_RESET=1]'; \
		exit 1; \
	fi; \
	RESET_FLAG=""; \
	if [ "$(SEND_RESET)" = "1" ]; then \
		RESET_FLAG="--send-reset"; \
	fi; \
	flyctl ssh console -a spawnradar -C "sh -lc 'cd /app && python -m app.devtools.cli --db-path /data/spawnradar.sqlite3 grant-comp --create-missing $$RESET_FLAG $(EMAILS)'"

define OPEN_BROWSER_DELAYED
	( sleep 1; \
	  if command -v open >/dev/null 2>&1; then open $(START_URL); \
	  elif command -v xdg-open >/dev/null 2>&1; then xdg-open $(START_URL); \
	  fi ) &
endef

define STOP_PORT
	@PIDS=$$(lsof -ti tcp:$(PORT) 2>/dev/null || true); \
	if [ -n "$$PIDS" ]; then \
		echo "Stopping existing server on port $(PORT) (pid: $$PIDS)"; \
		kill $$PIDS; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			lsof -ti tcp:$(PORT) >/dev/null 2>&1 || break; \
			sleep 0.1; \
		done; \
	fi
endef

## Start local server, keep existing DB, open browser, run with reload
run:
	$(STOP_PORT)
	@$(PYTHON) -m app.devtools.seed_dev data/spawnradar.sqlite3
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 wikiquests
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 strife-of-stars
	@echo "Starting server at $(URL)"
	$(OPEN_BROWSER_DELAYED)
	exec env DEV_AUTO_LOGIN=1 $(UVICORN) app.main:app --reload --host $(HOST) --port $(PORT)


## Show this help
help:
	@grep -E '^##' Makefile | sed 's/## /  /'
