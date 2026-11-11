#!/usr/bin/env bash
# Install Delve on Linux (DEL-379): the tools it needs, Claude Code for its DM, Delve itself with the OSRIC ruleset,
# the sample adventure, and then Delve running, now or as a service. Run it from the checkout, as the user who will
# run Delve (not root); it asks before every change, and says what it will run.
#
#   ./install.sh            ask at each step
#   ./install.sh --yes      take the recommended answer everywhere (it doesn't start Delve or log in to Claude)
#   ./install.sh --check    only report what is there and what is missing
#   ./install.sh --port N   Delve's port (default 7810)
set -euo pipefail

PORT=7810
YES=0
CHECK=0
NODE_MAJOR_MIN=20
NODE_VERSION=24
NVM_VERSION=v0.40.3
SAMPLE_TITLE="The Lady of the Weir"
DATA_DIR="${DELVE_DATA_DIR:-$HOME/.local/share/delve}"

while [ $# -gt 0 ]; do
  case "$1" in
    --yes | -y) YES=1 ;;
    --check) CHECK=1 ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
say() { printf '  %s\n' "$*"; }
ok() { printf '  \033[32mok\033[0m  %s\n' "$*"; }
missing() { printf '  \033[33m--\033[0m  %s\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ask "Question?" [default y|n]: yes or no; --yes takes the default.
ask() {
  local question="$1" default="${2:-y}" answer hint="[Y/n]"
  [ "$default" = n ] && hint="[y/N]"
  if [ "$YES" = 1 ]; then
    say "$question $hint ${default} (--yes)"
    [ "$default" = y ]
    return
  fi
  read -r -p "  $question $hint " answer </dev/tty || answer=""
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

# run COMMAND...: show it, then run it.
run() {
  printf '  \033[2m$ %s\033[0m\n' "$*"
  "$@"
}

[ "$(uname -s)" = Linux ] || fail "This script is for Linux. On macOS or Windows (WSL 2), follow INSTALL.md."
[ "$(id -u)" != 0 ] || fail "Run this as the user who will run Delve, not as root: it uses sudo only for system packages."
if [ ! -f pyproject.toml ] || [ ! -d src/delve ]; then
  fail "Run this from the Delve checkout (the folder with pyproject.toml)."
fi

export PATH="$HOME/.local/bin:$PATH"
load_nvm() {
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && return 0
  return 1
}
load_nvm || true

node_major() { have node && node --version | sed 's/^v\([0-9]*\).*/\1/' || echo 0; }

claude_logged_in() {
  have claude || return 1
  claude auth status 2>/dev/null | grep -q '"loggedIn": *true'
}

# ----- 1. what is there ------------------------------------------------------------------------------------------

bold "Delve's installer"
say "Checkout: $REPO"
say "Data folder: $DATA_DIR"
echo
bold "What you have"
for tool in git make curl; do
  if have "$tool"; then ok "$tool"; else missing "$tool"; fi
done
if have uv; then ok "uv $(uv --version | cut -d' ' -f2) (it brings Python 3.12+ itself)"; else missing "uv (and with it Python 3.12+)"; fi
if [ "$(node_major)" -ge "$NODE_MAJOR_MIN" ]; then ok "Node.js $(node --version)"; else
  missing "Node.js $NODE_MAJOR_MIN or newer$(have node && printf ' (found %s)' "$(node --version)")"
fi
if claude_logged_in; then ok "Claude Code, logged in"; elif have claude; then missing "Claude Code is installed but not logged in"; else
  missing "Claude Code (the DM)"
fi
if have tesseract; then ok "tesseract (optional: reads scanned PDFs)"; else say "    tesseract is optional: it reads scanned PDF pages"; fi
[ "$CHECK" = 1 ] && exit 0

# ----- 2. system packages ----------------------------------------------------------------------------------------

PM=""
for candidate in apt-get dnf pacman zypper; do
  if have "$candidate"; then PM="$candidate"; break; fi
done

install_packages() {
  [ $# -gt 0 ] || return 0
  case "$PM" in
    apt-get) run sudo apt-get update && run sudo apt-get install -y "$@" ;;
    dnf) run sudo dnf install -y "$@" ;;
    pacman) run sudo pacman -S --needed --noconfirm "$@" ;;
    zypper) run sudo zypper --non-interactive install "$@" ;;
    *) fail "No package manager I know (apt, dnf, pacman, zypper). Install these yourself, then run me again: $*" ;;
  esac
}

needed=()
for tool in git make curl; do have "$tool" || needed+=("$tool"); done
if [ ${#needed[@]} -gt 0 ]; then
  echo
  bold "System packages"
  if ask "Install ${needed[*]} with $PM (needs sudo)?"; then install_packages "${needed[@]}"; else
    fail "Delve needs ${needed[*]}. Install them and run me again."
  fi
fi
if ! have tesseract && [ -n "$PM" ]; then
  echo
  case "$PM" in apt-get | zypper) tess=tesseract-ocr ;; *) tess=tesseract ;; esac
  if ask "Install tesseract too, to read scanned PDFs (optional, needs sudo)?" n; then install_packages "$tess"; fi
fi

# ----- 3. uv and Python ------------------------------------------------------------------------------------------

if ! have uv; then
  echo
  bold "uv (Python and Delve's Python packages)"
  say "From https://astral.sh/uv, into ~/.local/bin; no sudo."
  if ask "Install uv?"; then
    run sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    have uv || fail "uv didn't land on the PATH: open a new terminal and run me again."
  else
    fail "Delve needs uv. See https://docs.astral.sh/uv/getting-started/installation/"
  fi
fi

# ----- 4. Node.js ------------------------------------------------------------------------------------------------

if [ "$(node_major)" -lt "$NODE_MAJOR_MIN" ]; then
  echo
  bold "Node.js (the web app's build, and Claude Code)"
  say "Distributions often ship an older Node. nvm installs Node $NODE_VERSION for you alone, in ~/.nvm; no sudo."
  if ask "Install nvm $NVM_VERSION and Node $NODE_VERSION?"; then
    run sh -c "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh | bash"
    load_nvm || fail "nvm didn't install; see https://github.com/nvm-sh/nvm"
    run nvm install "$NODE_VERSION"
    run nvm alias default "$NODE_VERSION"
  else
    fail "Delve needs Node.js $NODE_MAJOR_MIN or newer. See https://nodejs.org/"
  fi
fi

# ----- 5. Claude Code --------------------------------------------------------------------------------------------

if ! have claude; then
  echo
  bold "Claude Code (Delve's DM)"
  say "Delve's DM, translations and conversions run through the claude command, on your own Claude subscription."
  if ask "Install Claude Code with npm?"; then
    if [ -w "$(npm prefix -g)" ]; then run npm install -g @anthropic-ai/claude-code; else
      run sudo npm install -g @anthropic-ai/claude-code
    fi
  else
    say "Without it Delve starts, but has no DM. Install it later: npm install -g @anthropic-ai/claude-code"
  fi
fi
if have claude && ! claude_logged_in; then
  echo
  bold "Log in to Claude"
  if [ "$YES" = 1 ]; then
    say "Not logged in. Log in yourself later with: claude auth login"
  elif ask "Log in to Claude now (it opens a link to sign in)?"; then
    run claude auth login </dev/tty || say "The login didn't finish. Try again later with: claude auth login"
  fi
fi

# ----- 6. Delve --------------------------------------------------------------------------------------------------

echo
bold "Delve"
say "make install: Delve's Python packages, the OSRIC ruleset, and the web app's packages."
if ask "Install Delve?"; then
  run make install
else
  fail "Nothing more to do without Delve installed."
fi
if uv run delve pack list 2>/dev/null | grep -qi osric; then ok "OSRIC 3.0 is installed"; else
  if ask "The OSRIC ruleset isn't installed. Install it?"; then run uv run delve pack install packs/osric; fi
fi
say "Building the web app."
run make build

# ----- 7. the sample adventure -----------------------------------------------------------------------------------

api() {  # api METHOD PATH [curl args...]: Delve's API on $1 with the owner token
  local base="$1" method="$2" path="$3"
  shift 3
  curl -fsS -X "$method" "$base$path" -H "Authorization: Bearer $(cat "$DATA_DIR/token")" "$@"
}

import_sample() {
  local bundle base temp_pid="" temp_port
  bundle="$REPO/samples/lady-of-the-weir.dscn"
  if [ ! -f "$bundle" ]; then
    bundle="$(mktemp --suffix=.dscn)"
    rm -f "$bundle"
    (cd "$REPO/samples/lady-of-the-weir" && uv run python -I -m zipfile -c "$bundle" ./*)
  fi
  base="http://127.0.0.1:$PORT"
  if ! curl -fsS "$base/api/health" >/dev/null 2>&1; then
    temp_port=$((PORT + 89))
    base="http://127.0.0.1:$temp_port"
    say "Starting Delve for a moment on $base to import it."
    uv run delve serve --host 127.0.0.1 --port "$temp_port" >/dev/null 2>&1 &
    temp_pid=$!
    for _ in $(seq 1 60); do curl -fsS "$base/api/health" >/dev/null 2>&1 && break; sleep 1; done
  fi
  if api "$base" GET /api/modules | grep -q "\"title\": *\"$SAMPLE_TITLE\""; then
    ok "$SAMPLE_TITLE is already in Delve"
  elif api "$base" POST /api/modules/import -H 'Content-Type: application/vnd.dscn+zip' --data-binary "@$bundle" >/dev/null; then
    ok "Imported $SAMPLE_TITLE: find it under Modules"
  else
    say "The import didn't work; import samples/lady-of-the-weir.dscn yourself under Modules → New module."
  fi
  if [ -n "$temp_pid" ]; then kill "$temp_pid" 2>/dev/null || true; wait "$temp_pid" 2>/dev/null || true; fi
}

echo
bold "The sample adventure"
say "$SAMPLE_TITLE: an evening's adventure for OSRIC, for four to six 1st-2nd level characters."
if ask "Add it to Delve?"; then import_sample; fi

# ----- 8. running Delve ------------------------------------------------------------------------------------------

install_service() {
  local units="$HOME/.config/systemd/user" uv_bin node_bin claude_bin path_line
  uv_bin="$(command -v uv)"
  node_bin="$(dirname "$(command -v node)")"
  claude_bin="$(have claude && dirname "$(command -v claude)" || echo "$node_bin")"
  path_line="$(dirname "$uv_bin"):$node_bin:$claude_bin:/usr/local/bin:/usr/bin:/bin"
  if ! have systemctl || ! systemctl --user show-environment >/dev/null 2>&1; then
    say "systemd user services aren't available here. Start Delve with: make run"
    return
  fi
  mkdir -p "$units"
  for unit in delve.socket delve.service; do
    if [ -f "$units/$unit" ] && ! ask "$units/$unit exists. Replace it?" n; then
      say "Kept your $unit."
      continue
    fi
    if [ "$unit" = delve.socket ]; then
      cat >"$units/$unit" <<EOF
[Unit]
Description=Delve's port, held across restarts

[Socket]
ListenStream=0.0.0.0:$PORT

[Install]
WantedBy=sockets.target
EOF
    else
      cat >"$units/$unit" <<EOF
[Unit]
Description=Delve
Requires=delve.socket
After=delve.socket

[Service]
Type=simple
WorkingDirectory=$REPO
ExecStart=$uv_bin run delve serve --port $PORT
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
Environment=PATH=$path_line
Environment=DELVE_DATA_DIR=$DATA_DIR

[Install]
WantedBy=default.target
EOF
    fi
    ok "wrote $units/$unit"
  done
  run systemctl --user daemon-reload
  run systemctl --user enable --now delve.socket
  run systemctl --user enable delve.service
  run systemctl --user start delve.service
  if ! loginctl enable-linger "$USER" 2>/dev/null; then
    say "To keep Delve running when you log out: sudo loginctl enable-linger $USER"
  fi
}

echo
bold "Running Delve"
choice=3
if [ "$YES" = 0 ]; then
  say "1) Start it now, in this terminal (Ctrl-C stops it)"
  say "2) Run it as a service: it starts with your computer and keeps running when you log out (systemd)"
  say "3) Not now"
  read -r -p "  Your choice [1]: " choice </dev/tty || choice=3
  choice="${choice:-1}"
fi
echo
say "Open http://localhost:$PORT/ in a browser on this machine. The first time, it offers to make the owner account."
say "Playing with friends on your network or the internet: see INSTALL.md, sections 5 and 6."
case "$choice" in
  1) echo; run uv run delve serve --port "$PORT" ;;
  2) install_service; ok "Delve is running as a service: systemctl --user status delve" ;;
  *) say "Start it later with: make run   (or ./install.sh again for the service)" ;;
esac
