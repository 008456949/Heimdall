.PHONY: install run run-no-interceptor daemon-only interceptor status watch daemon stop logs clean test lint

PYTHON  := $(shell [ -f .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
MITM    := mitmdump
PLIST   := $(HOME)/Library/LaunchAgents/com.heimdall.daemon.plist

install:
	@bash scripts/setup.sh

run:
	@echo "[heimdall] Starting Heimdall (Ctrl-C to stop)…"
	@$(PYTHON) run.py

run-no-interceptor:
	@echo "[heimdall] Starting without interceptor (Ctrl-C to stop)…"
	@$(PYTHON) run.py --no-interceptor

daemon-only:
	@$(PYTHON) run.py --daemon-only

interceptor:
	@echo "[heimdall] Starting mitmproxy interceptor standalone…"
	@$(MITM) --mode local --quiet -s interceptor/proxy.py

status:
	@$(PYTHON) status.py

watch:
	@$(PYTHON) status.py --watch

daemon:
	@launchctl load $(PLIST) 2>/dev/null || launchctl start com.heimdall.daemon
	@echo "[heimdall] Daemon started via launchd"

stop:
	@launchctl stop com.heimdall.daemon 2>/dev/null || true
	@echo "[heimdall] Daemon stopped"

logs:
	@tail -f ~/.heimdall/daemon.log

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "[heimdall] Cleaned"

test:
	@$(PYTHON) -m pytest tests/ -v

lint:
	@$(PYTHON) -m ruff check heimdall/ interceptor/
