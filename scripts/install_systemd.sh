\
#!/usr/bin/env bash
set -euo pipefail

# Install a systemd service for EasyApe (Ubuntu 22.04).
# This keeps the bot running after logout/reboot.

SERVICE_NAME="easyape"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"

if [[ ! -f "${REPO_DIR}/config.yaml" ]]; then
  echo "Missing ${REPO_DIR}/config.yaml. Run scripts/install_easyape.sh first."
  exit 1
fi

if [[ ! -f "${REPO_DIR}/.env" ]]; then
  echo "Missing ${REPO_DIR}/.env. Run scripts/install_easyape.sh first."
  exit 1
fi

PY="${REPO_DIR}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing venv python at ${PY}. Run scripts/install_easyape.sh first."
  exit 1
fi

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=EasyApe - text to stake
After=network.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${REPO_DIR}/.env
ExecStart=${PY} -m stakechat_bot.main --config ${REPO_DIR}/config.yaml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "✅ Installed + started systemd service: ${SERVICE_NAME}"
echo "Logs:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
