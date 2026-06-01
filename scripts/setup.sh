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

# Python check
python3 --version | grep -qE "3\.(11|12|13)" || \
    error "Python 3.11+ required. Install via: brew install python@3.12"

# mitmproxy check
command -v mitmdump >/dev/null 2>&1 || {
    warn "mitmproxy not found — installing via brew"
    brew install mitmproxy
}

# Virtual environment
info "Creating virtual environment…"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_DIR/requirements.txt"
success "Dependencies installed"

# Generate mitmproxy cert
info "Generating mitmproxy certificate…"
mitmdump --version >/dev/null  # triggers cert generation if missing
CERT="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
if [[ ! -f "$CERT" ]]; then
    mitmdump &
    sleep 2
    kill %1 2>/dev/null || true
fi
[[ -f "$CERT" ]] || error "Certificate not generated at $CERT"
success "Certificate ready at $CERT"

# Install cert in system keychain
info "Installing root certificate in macOS system keychain (requires sudo)…"
sudo security add-trusted-cert -d -r trustRoot \
    -k /Library/Keychains/System.keychain "$CERT"
success "Certificate trusted in system keychain"

# Create config from template if missing
CONFIG="$REPO_DIR/heimdall/config.py"
if ! grep -q "ANTHROPIC_API_KEY" "$CONFIG"; then
    warn "Edit $CONFIG to add your API keys"
fi

# Install launchd plist
info "Installing launchd plist for auto-start on login…"
PYTHON_PATH="$VENV_DIR/bin/python3"
sed \
    -e "s|__REPO_DIR__|$REPO_DIR|g" \
    -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"
launchctl load "$PLIST_DST" 2>/dev/null || true
success "Launchd plist installed"

echo ""
success "Heimdall is installed!"
echo ""
echo "  Next steps:"
echo "  1. Edit heimdall/config.py — add your API keys"
echo "  2. Go to System Settings → Privacy & Security → Network Extensions"
echo "     and approve the mitmproxy extension"
echo "  3. Run:  make run"
echo ""
echo "  Logs:    ~/.heimdall/daemon.log"
echo "  DB:      ~/.heimdall/dashboard.db"
