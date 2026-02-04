# Tip: first-time setup: bash scripts/install_easyape.sh
#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

python -m stakechat_bot.main --config ./config.yaml
