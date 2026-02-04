<img width="1792" height="576" alt="generated-image (2)" src="https://github.com/user-attachments/assets/d0d2c2c1-6282-42ff-af68-619846279b04" />

## EasyApe 🦍 | text to stake (T2S)

A minimal **chat → btcli** bot for **staking / unstaking** on Bittensor from:

- Telegram (DM)
- Discord (slash commands)

✅ **Never transfers:** stake/unstake + read-only commands (**inventory**, **balance**) only  
✅ **Non-custodial:** no seed phrases, no private keys  
✅ **De-gen friendly:** “`stake 31 0.1 taostats`” from your couch  
✅ **Guardrails:** allow-lists, optional confirmations, per-tx + daily caps, rate limits  

---

## Table of Contents

- [What is EasyApe?](#what-is-easyape)
- [Safety first (read this)](#safety-first-read-this)
- [Privacy (minimal data)](#privacy-minimal-data)
- [Get it onto your server](#get-it-onto-your-server)
- [One-command install](#one-command-install)
- [First run onboarding](#first-run-onboarding)
- [Keep it running 24/7](#keep-it-running-247)
- [Commands](#commands)
- [Confirmations and modes](#confirmations-and-modes)
- [Validator names → hotkeys](#validator-names--hotkeys)
- [Billing and licensing](#billing-and-licensing)
- [Manual setup (advanced)](#manual-setup-advanced)
- [Repo license](#repo-license)

---

## What is EasyApe?

EasyApe lets you control Bittensor staking by messaging a bot.

Examples:
- `stake 31 0.1 taostats`
- `unstake 31 50 taostats`
- `inventory`
- `balance`

EasyApe runs **btcli locally** on your server. You host it. You control it.

---

## Safety first (read this)

This software is **not financial advice**. It is experimental software created for **testing, entertainment, and conceptual use only**.

You are solely responsible for:
- the wallet(s) you configure
- any staking/unstaking you trigger
- all gains/losses (including total loss)

**The EasyApe team is not liable** for anything related to how this software is used.

> Chat-controlled staking is inherently risky. Use a **dedicated wallet** with limited funds, strict allow-lists, and conservative limits.

### Hard guarantee: no transfers
EasyApe is designed to **never** run wallet transfer commands. It only supports:
- stake / unstake
- read-only: inventory / balance

---

## Privacy (minimal data)

EasyApe is self-hosted and **does not (and cannot) collect usage analytics** about what you do.

We do **not** receive:
- wallet names or addresses
- stake/unstake amounts
- validator choices
- message contents
- transaction history

The only external network calls (besides chat platforms) are **license checks** required for trial/subscription.

See **`docs/PRIVACY.md`** for the exact fields sent.

---

## Get it onto your server

Ubuntu 22.04 headless is the target. SSH into your server, then:

```bash
sudo apt update
sudo apt install -y git

mkdir -p ~/easyape
cd ~/easyape
git clone https://github.com/TidalWavesNode/EasyApe.git
cd EasyApe
```

---

## One-command install

From the repo root:

```bash
bash scripts/install_easyape.sh
```

This installer will:
- install system packages (Python/venv/git/curl/jq)
- create a venv and install EasyApe + btcli
- prompt you for:
  - coldkey name
  - wallet password (stored via env var)
  - confirmation + safety settings
  - Telegram + Discord tokens
- write `config.yaml` + `.env`
- **at the end:** ask if you want to install + start EasyApe as a **systemd service**

### Wallet password via env var (recommended)
The installer stores your wallet password in `.env` and references it from `config.yaml` using `env:...`.

Why this is safer:
- your password is **not** committed to git
- you can restrict access with file permissions
- it’s only loaded at runtime

Recommended perms:

```bash
chmod 600 .env
```

---

## First run onboarding

### 1) Start the bot (if you did NOT install the service)
```bash
source .venv/bin/activate
python -m stakechat_bot.main --config config.yaml
```

### 2) Identify yourself
DM the bot:

```
whoami
```

### 3) Allow-list your IDs
Paste your IDs into `config.yaml`:

```yaml
auth:
  allow:
    telegram_user_ids: [123456789]
    discord_user_ids: [123456789012345678]
```

Restart the bot/service after edits.

---

## Keep it running 24/7

If you chose **YES** to systemd during install, EasyApe should already be running.

Check status:
```bash
sudo systemctl status easyape --no-pager
```

Follow logs:
```bash
sudo journalctl -u easyape -f
```

Restart:
```bash
sudo systemctl restart easyape
```

If you skipped service install, you can install it later:
```bash
bash scripts/install_systemd.sh
```

---

## Commands

Type `help` in chat to see everything.

Core commands:
- `help`
- `whoami`
- `billing` (subscribe/manage links)
- `privacy`
- `doctor` (preflight checks)
- `inventory [wallet]`
- `balance [wallet]`
- `stake <netuid> <tao> [validator] [wallet]`
- `unstake <netuid> <alpha> [validator] [wallet]`
- `mode dry|live` or `dryrun on|off`
- `confirm <token>` (only used if confirmations are enabled)

---

## Confirmations and modes

- **Dry mode**: never runs btcli (safe testing)
- **Live mode**: runs btcli stake/unstake (real actions)

Confirmations:
- If `app.require_confirmation: false` → **no confirmations are required**
- If `app.require_confirmation: true` → in **LIVE** mode a confirmation token is required only when:
  - stake amount ≥ `app.confirm_over_tao`
  - unstake amount ≥ `app.confirm_over_alpha`

---

## Validator names → hotkeys

EasyApe uses a local validator registry so users can type a validator **name** (from taostats) instead of hotkeys.

- default source: taostats
- you can use your own validator API source + key in `config.yaml`
- you can set default validators globally, per subnet, or per wallet

See `docs/SETUP_CHANNELS.md` for validator commands and defaults.

---

## Billing and licensing

- **$19/month** operator license (one deployment)
- **3-day server-tracked trial**
- no license keys, no activation steps

On startup, EasyApe prints:
- a **Subscribe** link (headless friendly — forward it in chat)
- a **Manage** link (cancel/update payment)

After the trial expires, **stake/unstake lock** until subscribed.  
Read-only commands always work.

---

## Manual setup (advanced)

If you prefer not to use the installer:
- install deps + venv
- `pip install -r requirements.txt`
- copy templates:
  - `cp config.example.yaml config.yaml`
  - `cp .env.example .env`
- configure chat tokens + btcli paths

Most users should use the installer.

---

## Repo license

This repository is public for transparency and review, but it is **not open source**.  
See `LICENSE`.
