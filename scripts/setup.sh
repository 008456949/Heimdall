#!/usr/bin/env bash
# scripts/setup.sh — one-command Heimdall installation
# Run: bash scripts/setup.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[heimdall]${NC} $*"; }
success() { echo -e "${GREEN}[heimdall]${NC} $*"; }
warn()    { echo -e "${YELLOW}[heimdall]${NC} $*"; }
error()   { echo -e "${RED}[heimdall]${NC} $*"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
PLIST_SRC="$REPO_DIR/com.heimdall.daemon.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.heimdall.daemon.plist"

info "Setting up Heimdall in $REPO_DIR"

# ── Python check ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "python3 not found.\n\
  Install Homebrew first:\n\
    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n\
  Then install Python:\n\
    brew install python@3.12"
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJ=$(python3 -c "import sys; print(sys.version_info.major)")
PYMIN=$(python3 -c "import sys; print(sys.version_info.minor)")

if [[ "$PYMAJ" -lt 3 ]] || [[ "$PYMAJ" -eq 3 && "$PYMIN" -lt 11 ]]; then
    error "Python 3.11+ required. You have Python $PYVER.\n\
  Install a newer version:\n\
    brew install python@3.12\n\
  Then re-run:  bash scripts/setup.sh"
fi
success "Python $PYVER"

# ── Homebrew check ────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    warn "Homebrew not found — installing…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ── mitmproxy check ───────────────────────────────────────────────────────────
if ! command -v mitmdump &>/dev/null; then
    info "mitmproxy not found — installing via brew…"
    brew install mitmproxy
fi
success "mitmproxy $(mitmdump --version | head -1)"

# ── Virtual environment ───────────────────────────────────────────────────────
info "Creating virtual environment…"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_DIR/requirements.txt"
success "Dependencies installed in .venv"

# ── Generate mitmproxy cert ───────────────────────────────────────────────────
CERT="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
if [[ ! -f "$CERT" ]]; then
    info "Generating mitmproxy certificate…"
    mitmdump --version >/dev/null 2>&1 || true
    # Run briefly to trigger cert generation
    timeout 3 mitmdump 2>/dev/null || true
fi

if [[ ! -f "$CERT" ]]; then
    warn "Certificate not auto-generated — generating manually…"
    mkdir -p "$HOME/.mitmproxy"
    python3 -c "
from mitmproxy.certs import CertStore
from pathlib import Path
store = CertStore.from_store(Path.home() / '.mitmproxy', 'mitmproxy', 2048, 'RSA')
" 2>/dev/null || true
fi
[[ -f "$CERT" ]] || error "Certificate not generated. Run: mitmdump  (then Ctrl-C), then re-run setup."
success "Certificate at $CERT"

# ── Trust cert in macOS keychain ──────────────────────────────────────────────
info "Trusting certificate in macOS keychain (sudo required)…"
sudo security add-trusted-cert -d -r trustRoot \
    -k /Library/Keychains/System.keychain "$CERT"
success "Certificate trusted in system keychain"

# ── Install launchd plist ─────────────────────────────────────────────────────
info "Installing launchd plist for auto-start on login…"
PYTHON_PATH="$VENV_DIR/bin/python3"
mkdir -p "$HOME/Library/LaunchAgents"
sed \
    -e "s|__REPO_DIR__|$REPO_DIR|g" \
    -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"
launchctl load "$PLIST_DST" 2>/dev/null || true
success "Launchd plist installed"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
success "Heimdall is ready!"
echo ""
echo "  Next steps:"
echo "  1. System Settings → Privacy & Security → Network Extensions"
echo "     → approve the mitmproxy Network Extension"
echo "  2. Edit heimdall/config.py and add your API keys (optional)"
echo "  3. Launch:"
echo ""
echo "     python3 run.py --no-interceptor   # test first (no mitmproxy)"
echo "     python3 run.py                    # full app"
echo ""
echo "  Logs:  ~/.heimdall/daemon.log"
echo "  DB:    ~/.heimdall/dashboard.db"
