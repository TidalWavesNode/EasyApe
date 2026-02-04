This guide explains how to connect EasyApe to each chat platform.

## Prereqs (all platforms)
1. Install Python 3.10+ and create a venv.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy config templates:
   ```bash
   cp config.example.yaml config.yaml
   cp .env.example .env
   ```
4. Get your platform IDs by DMing the bot: `whoami` (works even before you're allow-listed).

5. Add **your IDs** to the allow-lists in `config.yaml`:
   ```yaml
   auth:
     allow:
       telegram_user_ids: [123456789]
       discord_user_ids: [123456789012345678]
   ```

## Licensing / Trial

EasyApe licensing is **automatic** (no activation steps).
- On first run, EasyApe calls the license server and starts your **3-day server-tracked trial**
- After the trial expires, `stake/unstake` lock until subscribed
- Use `billing` to get a subscribe/manage link that you can forward in chat (headless-friendly)

## Telegram

### Create a bot token
1. In Telegram, talk to **BotFather**
2. Create a bot and copy the token.

### Configure
In `.env`:
```bash
TELEGRAM_BOT_TOKEN="123:ABC..."
```
In `config.yaml`:
```yaml
channels:
  telegram:
    enabled: true
    token: "env:TELEGRAM_BOT_TOKEN"
```

### Run + test
Start EasyApe and DM your bot:
- `help`
- `validators refresh`
- `stake 31 0.10 taostats` (DRY mode)
- `stake 0.10` (Turbo, if you set `default_netuid`)

## Discord
### Create a Discord application + bot
1. Go to Discord Developer Portal
2. Create an application, add a **bot**
3. Copy the bot token
4. Invite the bot to your server with `applications.commands` scope.

### Configure
In `.env`:
```bash
DISCORD_BOT_TOKEN="..."
```
In `config.yaml`:
```yaml
channels:
  discord:
    enabled: true
    token: "env:DISCORD_BOT_TOKEN"
    guild_ids: []   # optional; add your server ID for faster slash-sync
```

### Run + test
Use slash commands in your server/DM:
- `/help`
- `/validators_refresh`
- `/validators_search term:tao`
- `/stake tao_amount:0.10 netuid:31 validator:taostats`
- `/defaults`


### Option A (recommended): Docker daemon
Use the included compose:
```bash
```


### Configure
In `.env`:
```bash
```
In `config.yaml`:
```yaml
channels:
    enabled: true
    connection: "tcp://127.0.0.1:7583"
```

### Run + test
- `help`
- `validators sources`
- `stake 31 0.10 taostats`

## Validator registry commands (all platforms)
- `validators sources` — show configured sources
- `validators refresh` — refresh local cache
- `validators search <term>` — find validators by name

## Defaults + “no-typing” stake routing
Configure defaults in `config.yaml`:
- global defaults: `defaults.validator_all`, `defaults.validator_by_netuid`
- per-wallet defaults: `btcli.wallets.<alias>.validator_all`, `validator_by_netuid`, `default_netuid`

Runtime overrides (persisted in `data/state.json`):
- `set default validator taostats`
- `set netuid 31 validator taostats`
- `set wallet main default validator taostats`
- `set wallet main netuid 31 validator taostats`
- `set wallet main default netuid 31`
- `show defaults`


## Read-only commands
- `inventory` — show stake inventory
- `balance` — show TAO wallet balance
