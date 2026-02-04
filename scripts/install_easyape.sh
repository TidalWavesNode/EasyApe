\
#!/usr/bin/env bash
set -euo pipefail

# EasyApe 🦍 — text to stake
# One-shot installer for Ubuntu 22.04 headless (works on most Debian/Ubuntu).
# Installs deps, creates venv, installs btcli + EasyApe requirements, writes .env + config.yaml.

BOLD="$(printf '\033[1m')"
DIM="$(printf '\033[2m')"
RED="$(printf '\033[31m')"
GRN="$(printf '\033[32m')"
YLW="$(printf '\033[33m')"
RST="$(printf '\033[0m')"

say() { echo -e "${BOLD}$*${RST}"; }
info() { echo -e "${DIM}$*${RST}"; }
warn() { echo -e "${YLW}[WARN]${RST} $*"; }
err() { echo -e "${RED}[ERR]${RST} $*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

require_repo_root() {
  if [[ ! -f "requirements.txt" || ! -d "src" ]]; then
    err "Run this from the EasyApe repo root (same folder as requirements.txt)."
    exit 1
  fi
}

detect_os() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    echo "${ID:-unknown} ${VERSION_ID:-unknown}"
  else
    echo "unknown"
  fi
}

prompt_yn() {
  local prompt="$1"
  local default="${2:-y}"
  local ans
  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n]: " ans || true
    ans="${ans:-y}"
  else
    read -r -p "$prompt [y/N]: " ans || true
    ans="${ans:-n}"
  fi
  [[ "$ans" =~ ^[Yy]$ ]]
}

prompt_val() {
  local prompt="$1"
  local default="${2:-}"
  local out
  if [[ -n "$default" ]]; then
    read -r -p "$prompt ($default): " out || true
    echo "${out:-$default}"
  else
    read -r -p "$prompt: " out || true
    echo "$out"
  fi
}

prompt_secret() {
  local prompt="$1"
  local out
  read -r -s -p "$prompt: " out || true
  echo
  echo "$out"
}

write_env_kv() {
  local key="$1"
  local val="$2"
  # create .env if needed
  [[ -f .env ]] || cp .env.example .env
  # escape backslashes and quotes
  local esc="${val//\\/\\\\}"
  esc="${esc//\"/\\\"}"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=\"${esc}\"|g" .env
  else
    echo "${key}=\"${esc}\"" >> .env
  fi
}

set_yaml_kv() {
  # naive YAML edits for config.example.yaml structure
  # usage: set_yaml_kv "path.to.key" "value" (value is raw, e.g. true, false, 31, "dry")
  local keypath="$1"
  local value="$2"
  python3 - "$keypath" "$value" <<'PY'
import sys, re
keypath = sys.argv[1]
value = sys.argv[2]
cfg_path = "config.yaml"

# We avoid external YAML libs; apply targeted edits for our known file layout.
# Supports paths:
#   app.mode
#   app.require_confirmation
#   app.confirm_over_tao
#   app.confirm_over_alpha
#   btcli.wallets.main.wallet_name
#   btcli.wallets.main.password
#   btcli.wallets.main.default_netuid
#   channels.telegram.enabled
#   channels.discord.enabled
#   channels.telegram.token
#   channels.discord.token
#   btcli.path
#   btcli.common_args
#
# NOTE: This is intentionally minimal + predictable, not a general YAML editor.

text = open(cfg_path, "r", encoding="utf-8").read().splitlines()

def replace_line(prefix, new_line):
    for i, line in enumerate(text):
        if line.strip().startswith(prefix):
            text[i] = re.sub(r"^(\s*)"+re.escape(prefix)+r".*$", r"\1"+new_line, line)
            return True
    return False

def set_under_block(block_key, target_key, new_line):
    # find "block_key:" then within indent set "target_key:"
    for i, line in enumerate(text):
        if line.startswith(block_key + ":"):
            base_indent = len(line) - len(line.lstrip())
            for j in range(i+1, len(text)):
                if text[j].strip() == "" or text[j].lstrip().startswith("#"):
                    continue
                indent = len(text[j]) - len(text[j].lstrip())
                if indent <= base_indent:
                    break
                if text[j].strip().startswith(target_key + ":"):
                    # preserve indent of that line
                    pref = " " * indent + target_key + ": "
                    text[j] = pref + new_line
                    return True
            return False
    return False

def set_nested(block_keys, target_key, new_value):
    # block_keys is list like ["btcli","wallets","main"]
    # Navigate by indentation heuristics
    idx = 0
    base_indent = -1
    for k in block_keys:
        found = False
        for i in range(idx, len(text)):
            line = text[i]
            if line.strip() == f"{k}:":
                idx = i+1
                base_indent = len(line) - len(line.lstrip())
                found = True
                break
        if not found:
            return False
    # now set target_key within that indentation
    for j in range(idx, len(text)):
        line = text[j]
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        if line.strip().startswith(target_key + ":"):
            text[j] = " " * indent + target_key + ": " + new_value
            return True
    return False

def q(s):
    # quote if not already a yaml literal or boolean/number/null
    if s.lower() in ("true","false","null") or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    if s.startswith("[") or s.startswith("{"):
        return s
    # wrap in quotes
    return '"' + s.replace('"', '\\"') + '"'

# dispatch
kp = keypath.split(".")
v = value
if keypath in ("app.mode",):
    replace_line("mode:", f'mode: {q(v)}')
elif keypath in ("app.require_confirmation","app.confirm_over_tao","app.confirm_over_alpha"):
    replace_line(kp[-1]+":", f'{kp[-1]}: {q(v)}')
elif keypath == "btcli.path":
    set_nested(["btcli"], "path", q(v))
elif keypath == "btcli.wallets_path":
    set_nested(["btcli"], "wallets_path", q(v))
elif keypath == "btcli.common_args":
    set_nested(["btcli"], "common_args", v)
elif keypath == "btcli.wallets.main.wallet_name":
    set_nested(["btcli","wallets","main"], "wallet_name", q(v))
elif keypath == "btcli.wallets.main.password":
    set_nested(["btcli","wallets","main"], "password", q(v))
elif keypath == "btcli.wallets.main.default_netuid":
    set_nested(["btcli","wallets","main"], "default_netuid", q(v))
elif keypath.startswith("channels.telegram."):
    if kp[-1] == "enabled":
        set_nested(["channels","telegram"], "enabled", q(v))
    elif kp[-1] == "token":
        set_nested(["channels","telegram"], "token", q(v))
elif keypath.startswith("channels.discord."):
    if kp[-1] == "enabled":
        set_nested(["channels","discord"], "enabled", q(v))
    elif kp[-1] == "token":
        set_nested(["channels","discord"], "token", q(v))
else:
    # best-effort: simple top-level replace
    replace_line(kp[-1]+":", f'{kp[-1]}: {q(v)}')

open(cfg_path, "w", encoding="utf-8").write("\n".join(text) + "\n")
PY
}

main() {
  require_repo_root

  say "EasyApe 🦍 — text to stake"
  info "This installer will:"
  info "  • install system packages (python/venv/git/curl/jq)"
  info "  • create a venv and install EasyApe + btcli"
  info "  • prompt for wallet + safety settings + chat tokens"
  echo

  os="$(detect_os)"
  info "Detected OS: ${os}"
  if [[ "$os" != "ubuntu 22.04" ]]; then
    warn "This is optimized for Ubuntu 22.04. It will likely still work on Debian/Ubuntu variants."
  fi

  # Packages
  say "1) Installing prerequisites"
  if prompt_yn "Install apt packages with sudo?" "y"; then
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip git curl jq unzip tmux
  else
    warn "Skipping apt installs. If something fails later, rerun and allow installs."
  fi

  # Venv
  say "2) Creating Python venv + installing deps"
  if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
  fi
  . .venv/bin/activate
  python -m pip install -U pip wheel setuptools

  # Install EasyApe requirements
  pip install -r requirements.txt

  # Install btcli (official package: bittensor-cli)
  # Ref: https://docs.learnbittensor.org/getting-started/install-btcli
  pip install -U bittensor-cli

  # Create config + env if needed
  say "3) Creating config.yaml + .env"
  [[ -f config.yaml ]] || cp config.example.yaml config.yaml
  [[ -f .env ]] || cp .env.example .env
  chmod 600 .env config.yaml || true

  # Point to venv btcli
  BTCLI_VENV_PATH="$(pwd)/.venv/bin/btcli"
  write_env_kv "BTCLI_PATH" "$BTCLI_VENV_PATH"
  write_env_kv "BT_WALLETS_DIR" "${HOME}/.bittensor/wallets"
  set_yaml_kv "btcli.path" "env:BTCLI_PATH"
  set_yaml_kv "btcli.wallets_path" "env:BT_WALLETS_DIR"

  # Wallet prompts
  say "4) Wallet setup (coldkey)"
  coldkey="$(prompt_val "Coldkey name (wallet name)" "mycoldkey")"
  set_yaml_kv "btcli.wallets.main.wallet_name" "$coldkey"

  # Use EASYAPE_WALLET_PASSWORD by default
  set_yaml_kv "btcli.wallets.main.password" "env:EASYAPE_WALLET_PASSWORD"

  # Optional turbo mode
  netuid="$(prompt_val "Default netuid for turbo mode (blank = none)" "31")"
  if [[ -z "$netuid" || "$netuid" == "none" || "$netuid" == "null" ]]; then
    set_yaml_kv "btcli.wallets.main.default_netuid" "null"
  else
    set_yaml_kv "btcli.wallets.main.default_netuid" "$netuid"
  fi

  # Wallet password
  warn "Wallet password is required for stake/unstake. We'll store it in .env (chmod 600)."
  pass="$(prompt_secret "Enter wallet password (will not echo)")"
  write_env_kv "EASYAPE_WALLET_PASSWORD" "$pass"

  # Check wallet exists; offer to create
  wallets_dir="${HOME}/.bittensor/wallets"
  if [[ -d "${wallets_dir}/${coldkey}" ]]; then
    info "Found existing wallet folder: ${wallets_dir}/${coldkey}"
  else
    warn "No wallet folder found at: ${wallets_dir}/${coldkey}"
    if prompt_yn "Create a new coldkey now with btcli? (recommended)" "y"; then
      warn "IMPORTANT: btcli will print a mnemonic (seed phrase). Save it OFFLINE. Anyone with it can steal your funds."
      echo
      "$BTCLI_VENV_PATH" wallet new_coldkey --wallet.name "$coldkey"
      echo
      info "Wallet creation complete."
    else
      warn "Skipping wallet creation. You must create/import a wallet before staking."
      warn "Docs: https://docs.learnbittensor.org/keys/working-with-keys"
    fi
  fi

  # Safety settings
  say "5) Safety settings"
  if prompt_yn "Enable confirmations in LIVE mode?" "y"; then
    set_yaml_kv "app.require_confirmation" "true"
    ctao="$(prompt_val "Confirm stake when TAO >= (confirm_over_tao)" "1.0")"
    calpha="$(prompt_val "Confirm unstake when Alpha >= (confirm_over_alpha)" "200.0")"
    set_yaml_kv "app.confirm_over_tao" "$ctao"
    set_yaml_kv "app.confirm_over_alpha" "$calpha"
  else
    set_yaml_kv "app.require_confirmation" "false"
  fi

  mode="dry"
  if prompt_yn "Start in LIVE mode now? (recommended: start dry first)" "n"; then
    mode="live"
  fi
  set_yaml_kv "app.mode" "$mode"

  # Chat platforms
  say "6) Chat platforms (enable the ones you want)"
  # Telegram
  if prompt_yn "Enable Telegram?" "y"; then
    tok="$(prompt_val "Paste TELEGRAM_BOT_TOKEN" "")"
    write_env_kv "TELEGRAM_BOT_TOKEN" "$tok"
    set_yaml_kv "channels.telegram.enabled" "true"
    set_yaml_kv "channels.telegram.token" "env:TELEGRAM_BOT_TOKEN"
  else
    set_yaml_kv "channels.telegram.enabled" "false"
  fi

  # Discord
  if prompt_yn "Enable Discord?" "y"; then
    tok="$(prompt_val "Paste DISCORD_BOT_TOKEN" "")"
    write_env_kv "DISCORD_BOT_TOKEN" "$tok"
    set_yaml_kv "channels.discord.enabled" "true"
    set_yaml_kv "channels.discord.token" "env:DISCORD_BOT_TOKEN"
  else
    set_yaml_kv "channels.discord.enabled" "false"
  fi

  # Verify btcli
  say "7) Quick checks"
  if "$BTCLI_VENV_PATH" --version >/dev/null 2>&1; then
    info "btcli installed OK: $("$BTCLI_VENV_PATH" --version 2>/dev/null | head -n 1 || true)"
  else
    warn "btcli did not run successfully. Try: .venv/bin/btcli --version"
  fi

  info "Config written: $(pwd)/config.yaml"
  info "Env written:    $(pwd)/.env"

  echo
  say "8) Start EasyApe"
  echo "Next steps:"
  echo "  1) Start the bot:"
  echo "     source .venv/bin/activate"
  echo "     python -m stakechat_bot.main --config config.yaml"
  echo
  echo "  2) DM the bot: whoami"
  echo "  3) Put your IDs into config.yaml under auth.allow.*"
  echo
  echo "Optional: run as a service (recommended)."
  if prompt_yn "Install + start EasyApe as a systemd service now?" "y"; then
    if [[ -f "scripts/install_systemd.sh" ]]; then
      bash scripts/install_systemd.sh
      info "Service installed. Logs: sudo journalctl -u easyape -f"
    else
      warn "Missing scripts/install_systemd.sh"
    fi
  else
    info "Skipped service install. You can run later: bash scripts/install_systemd.sh"
  fi
  echo
  say "Done. 🦍"
}

main "$@"
