.PHONY: install check run reset-db help deploy

PYTHON  := .venv/bin/python
UVICORN := .venv/bin/uvicorn
PYTEST  := .venv/bin/pytest

HOST := 0.0.0.0
PORT := 8000
URL  := http://localhost:$(PORT)
START_URL := $(URL)/auth/dev-login

install:
	pip3 install -r dev-requirements.txt
	pip3 install -r requirements.txt

check:
	$(PYTHON) -m pytest #--durations=0 --durations-min=0
	$(RUFF) check wikiquests

deploy:
	@set -e; \
	if ! command -v flyctl >/dev/null 2>&1; then \
		echo "flyctl is not installed. Install it first: brew install flyctl"; \
		exit 1; \
	fi; \
	exec flyctl deploy --ha=false --strategy immediate


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

## Start fresh: wipe DB, kill any existing server, open browser, run with reload
dev:
	$(STOP_PORT)
	@rm -f data/spawnradar.sqlite3
	@$(PYTHON) -c "from app.database import initialize_database; initialize_database('data/spawnradar.sqlite3')"
	@$(PYTHON) -m app.devtools.seed_dev data/spawnradar.sqlite3
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 wikiquests
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 strife-of-stars
	@echo "Database reset. Starting server at $(URL)"
	$(OPEN_BROWSER_DELAYED)
	exec env DEV_AUTO_LOGIN=1 $(UVICORN) app.main:app --reload --host $(HOST) --port $(PORT)

## Start fresh: wipe DB, kill any existing server, open browser, run with reload
run:
	$(STOP_PORT)
	@rm -f data/spawnradar.sqlite3
	@$(PYTHON) -c "from app.database import initialize_database; initialize_database('data/spawnradar.sqlite3')"
	@$(PYTHON) -m app.devtools.seed_dev data/spawnradar.sqlite3
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 wikiquests
	@$(PYTHON) -m app.devtools.cli --db-path data/spawnradar.sqlite3 strife-of-stars
	@echo "Database reset. Starting server at $(URL)"
	$(OPEN_BROWSER_DELAYED)
	exec env DEV_AUTO_LOGIN=1 $(UVICORN) app.main:app --reload --host $(HOST) --port $(PORT)


## Drop and recreate the local SQLite database
reset-db:
	rm -f data/spawnradar.sqlite3
	$(PYTHON) -c "from app.database import initialize_database; initialize_database('data/spawnradar.sqlite3')"
	@echo "Database reset at data/spawnradar.sqlite3"


## Show this help
help:
	@grep -E '^##' Makefile | sed 's/## /  /'
