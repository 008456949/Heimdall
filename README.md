# Heimdall

> Like the Norse god who watches the Bifrost, Heimdall sits silently between your machine and every AI endpoint — intercepting, measuring, routing, and alerting before the bill arrives.

A god-mode macOS developer dashboard. AI token interceptor + system intelligence + developer context awareness — all in one menubar utility.

---

## What it does

```
┌─────────────────────────────────────────────────────────────┐
│  menubar:  ⬡ $0.043  CPU 34%  RAM 71%                      │
│            click → today / week / month / by app / by model │
└─────────────────────────────────────────────────────────────┘
         ↑ reads from SQLite

┌─────────────────────────────────────────────────────────────┐
│  interceptor  (mitmproxy local mode)                        │
│  every AI call on this machine passes through here          │
│  → Anthropic · OpenAI · Ollama · Cursor · Claude Desktop   │
└─────────────────────────────────────────────────────────────┘
         ↑ writes token_usage rows

┌─────────────────────────────────────────────────────────────┐
│  daemon  (launchd, always-on)                               │
│  collectors: cpu · memory · token_api · alerts              │
└─────────────────────────────────────────────────────────────┘
         ↑ writes system_snapshots + alerts rows

┌─────────────────────────────────────────────────────────────┐
│  dashboard.db  (SQLite, ~/.heimdall/dashboard.db)           │
│  system_snapshots · token_usage · alerts                    │
└─────────────────────────────────────────────────────────────┘
```

## Features

- **Live AI token tracking** — every Anthropic, OpenAI, and Ollama call intercepted at the network layer
- **Git-attributed cost** — spend broken down by repo and branch, not just by app
- **Cloud-to-local routing** — short prompts silently rerouted to local Ollama, saving cost
- **System pulse** — CPU and RAM as context for AI spend, not as a full Activity Monitor replacement
- **Spend alerts** — configurable daily/monthly thresholds with macOS notifications
- **Full history** — 90 days of queryable SQLite data, no cloud sync required

## Requirements

- macOS 13+ (Ventura or later)
- Python 3.11+
- [mitmproxy](https://mitmproxy.org/) for traffic interception
- [Ollama](https://ollama.ai/) (optional, for local model routing)

## Installation

```bash
git clone https://github.com/008456949/Heimdall.git
cd Heimdall
make install
```

`make install` will:
1. Create a Python virtual environment
2. Install all dependencies
3. Generate the mitmproxy root certificate
4. Install the cert in your macOS system keychain (requires one `sudo` prompt)
5. Prompt you to approve the Network Extension in System Settings
6. Install the launchd plist for auto-start on login

## Usage

```bash
make run       # start daemon + menubar (foreground, for development)
make daemon    # start daemon in background via launchd
make stop      # stop the launchd daemon
make logs      # tail the daemon log
make status    # show daemon status + today's spend
```

## Configuration

Edit `heimdall/config.py`:

```python
ANTHROPIC_API_KEY = "sk-ant-..."   # for usage API polling
OPENAI_API_KEY    = "sk-..."       # for usage API polling

ALERT_CPU_PCT       = 85.0         # CPU spike threshold
ALERT_MONTHLY_SPEND = 20.00        # USD monthly spend alert

OLLAMA_ROUTING_THRESHOLD = 2000    # tokens — route below this to local Ollama
```

## Querying your data

```bash
sqlite3 ~/.heimdall/dashboard.db

-- Spend this month by provider
SELECT provider, ROUND(SUM(cost_usd), 4) as cost
FROM token_usage
WHERE ts > strftime('%s','now','start of month')
GROUP BY provider;

-- Top 10 most expensive sessions
SELECT app, model, SUM(tokens_in + tokens_out) as tokens,
       ROUND(SUM(cost_usd), 4) as cost
FROM token_usage
GROUP BY app, model
ORDER BY cost DESC LIMIT 10;

-- CPU spikes last 24h
SELECT datetime(ts,'unixepoch','localtime'), value, message
FROM alerts WHERE kind='cpu_spike'
AND ts > strftime('%s','now','-1 day');
```

## Project structure

```
Heimdall/
├── heimdall/
│   ├── config.py          # all tunables — edit this first
│   ├── daemon.py          # scheduler, runs all collectors
│   ├── db/
│   │   └── database.py    # SQLite schema + read/write helpers
│   ├── collectors/
│   │   ├── base.py        # abstract collector interface
│   │   ├── system.py      # CPU + memory snapshots
│   │   └── tokens_api.py  # Anthropic + OpenAI usage API polling
│   └── ui/
│       └── menubar.py     # PyObjC menubar app
├── interceptor/
│   ├── proxy.py           # mitmproxy addon — the core interceptor
│   └── parsers/
│       ├── anthropic.py   # parse Anthropic SSE + JSON responses
│       ├── openai.py      # parse OpenAI responses
│       └── ollama.py      # parse Ollama streaming responses
├── scripts/
│   └── setup.sh           # one-command installation
├── Makefile
└── com.heimdall.daemon.plist
```

## Roadmap

- [x] Core daemon + SQLite schema
- [x] System collector (CPU + RAM)
- [x] mitmproxy interceptor (Anthropic + OpenAI + Ollama)
- [x] Menubar UI with spend display
- [ ] Git branch attribution
- [ ] Cloud-to-local Ollama routing
- [ ] Per-model cost breakdown
- [ ] Spend threshold alerts (macOS notifications)
- [ ] Weekly email digest
- [ ] Zombie port whisperer panel
- [ ] Freeze-dried environment manager

## License

MIT — see [LICENSE](LICENSE)
