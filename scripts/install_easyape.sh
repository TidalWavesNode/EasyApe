#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EasyApe Installer v2
# Supports: fresh install | upgrade | repair
# Uses Bittensor Python SDK (no btcli subprocess dependency)
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ✅ Dynamically resolve repo root (FIXES your error)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
CONFIG_FILE="${ROOT_DIR}/config.yaml"
SERVICE_FILE="/etc/systemd/system/easyape.service"

CYAN="\033[0;36m"
GREEN="\033[0;32m"
RED="\033[0;31m"
NC="\033[0m"

info()    { echo -e "${CYAN}➜${NC}  $1"; }
success() { echo -e "${GREEN}✅${NC}  $1"; }
warn()    { echo -e "${RED}⚠️${NC}   $1"; }

echo
echo -e "${CYAN}🦍 EasyApe Installer${NC}"
echo "──────────────────────────────────────────────────"

# ───────────────────────────────────────────────────
# Sanity check (NEW SAFETY)
# ───────────────────────────────────────────────────
if [[ ! -f "${ROOT_DIR}/requirements.txt" ]]; then
    warn "requirements.txt not found in ${ROOT_DIR}"
    exit 1
fi

# ───────────────────────────────────────────────────
# Python / venv setup
# ───────────────────────────────────────────────────
echo
info "Setting up Python virtual environment..."

python3 -m venv "$VENV_DIR" || true
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

success "venv ready"

# ───────────────────────────────────────────────────
# Wallet setup
# ───────────────────────────────────────────────────
echo
WALLET_NAME="${WALLET_NAME:-EasyApe}"

read -r -p "Wallet name [${WALLET_NAME}]: " wn || true
WALLET_NAME="${wn:-${WALLET_NAME}}"

WALLET_PATH="/root/.bittensor/wallets"
read -r -p "Wallet path [${WALLET_PATH}]: " wp || true
WALLET_PATH="${wp:-${WALLET_PATH}}"

echo
read -r -p "Create a new passwordless coldkey now? [Y/n]: " ans || true
ans="${ans:-Y}"

if [[ "$ans" =~ ^[Yy]$ ]]; then
    echo
    info "Creating coldkey '${WALLET_NAME}'…"

    "${VENV_DIR}/bin/python" <<PY
import bittensor as bt

wallet = bt.Wallet(name="${WALLET_NAME}", path="${WALLET_PATH}")

mnemonic = wallet.create_new_coldkey(
    use_password=False,
    overwrite=False
)

print()
print("🔐 NEW WALLET CREATED")
print("────────────────────────────────────")
print("Wallet Name :", wallet.name)
print("Address     :", wallet.coldkey.ss58_address)
print()
print("🚨 SAVE THIS MNEMONIC PHRASE 🚨")
print(mnemonic)
print()
print("Store this securely.")
print("This is the ONLY way to recover your wallet.")
print()
PY

    echo
    read -r -p "Press ENTER once you have safely stored your mnemonic phrase..."
fi

# ───────────────────────────────────────────────────
# Telegram setup
# ───────────────────────────────────────────────────
echo
ENABLE_TELEGRAM="true"
read -r -p "Enable Telegram bot? [Y/n]: " tg || true
[[ "$tg" =~ ^[Nn]$ ]] && ENABLE_TELEGRAM="false"

TELEGRAM_TOKEN=""
TELEGRAM_USER_IDS_BLOCK="    []"

if [[ "$ENABLE_TELEGRAM" == "true" ]]; then
    read -r -p "Telegram Bot Token: " TELEGRAM_TOKEN
    read -r -p "Your Telegram User ID: " TG_ID
    TELEGRAM_USER_IDS_BLOCK="    - ${TG_ID}"
fi

# ───────────────────────────────────────────────────
# Discord setup (optional)
# ───────────────────────────────────────────────────
echo
ENABLE_DISCORD="false"
read -r -p "Enable Discord bot? [y/N]: " dc || true
[[ "$dc" =~ ^[Yy]$ ]] && ENABLE_DISCORD="true"

DISCORD_TOKEN=""
DISCORD_USER_IDS_BLOCK="    []"

if [[ "$ENABLE_DISCORD" == "true" ]]; then
    read -r -p "Discord Bot Token: " DISCORD_TOKEN
    read -r -p "Your Discord User ID: " DC_ID
    DISCORD_USER_IDS_BLOCK="    - ${DC_ID}"
fi

# ───────────────────────────────────────────────────
# Write config.yaml
# ───────────────────────────────────────────────────
echo
info "Writing config.yaml…"

cat > "$CONFIG_FILE" <<YAML
app:
  mode: live
  require_confirmation: true
  confirm_over_tao: 0.5
  confirm_ttl_seconds: 120

telegram:
  enabled: ${ENABLE_TELEGRAM}
  bot_token: "${TELEGRAM_TOKEN}"

discord:
  enabled: ${ENABLE_DISCORD}
  bot_token: "${DISCORD_TOKEN}"

auth:
  telegram_user_ids:
${TELEGRAM_USER_IDS_BLOCK}
  discord_user_ids:
${DISCORD_USER_IDS_BLOCK}

btcli:
  path: btcli
  default_wallet: main
  common_args:
    - --subtensor.network
    - finney
  wallets:
    main:
      coldkey: "${WALLET_NAME}"
      wallets_dir: "${WALLET_PATH}"
      password: ""
      validator_all: tao.bot
YAML

success "config.yaml written"

# ───────────────────────────────────────────────────
# Install systemd service
# ───────────────────────────────────────────────────
echo
info "Installing systemd service…"

cp systemd/easyape.service "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable easyape

success "systemd service installed"

# ───────────────────────────────────────────────────
# Start EasyApe
# ───────────────────────────────────────────────────
echo
info "Starting EasyApe…"

systemctl restart easyape

echo
success "Installation complete!"
echo "View logs:"
echo "journalctl -u easyape -f"
echo
