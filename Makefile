.PHONY: install run daemon stop logs status clean test lint

PYTHON  := .venv/bin/python3
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

status:
	@echo "=== Daemon ==="
	@launchctl list | grep heimdall || echo "  not running"
	@echo ""
	@echo "=== Today's spend ==="
	@sqlite3 ~/.heimdall/dashboard.db \
		"SELECT provider, ROUND(SUM(cost_usd),4) as cost, \
		 SUM(tokens_in+tokens_out) as tokens \
		 FROM token_usage \
		 WHERE ts > strftime('%s','now','-1 day') \
		 GROUP BY provider;" 2>/dev/null || echo "  no data yet"

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "[heimdall] Cleaned"

test:
	@$(PYTHON) -m pytest tests/ -v

lint:
	@$(PYTHON) -m ruff check heimdall/ interceptor/
