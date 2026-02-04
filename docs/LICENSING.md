# EasyApe Licensing (Operator Notes)

EasyApe uses **Option A** licensing: the bot calls a **license server** that is the **source of truth** for:
- trial start/end
- subscription status

The bot is designed so customers do **not** need to configure licensing or enter keys.

## Source of truth
- Trial start/end is **server-tracked** (keyed by `install_id` + `fingerprint`)
- On **startup**, the bot calls the server to bootstrap trial state
- On every **stake/unstake** attempt, the bot calls the server again to authorize access

Read-only commands (`help`, `whoami`, `inventory`, `balance`) always work.

## API overview

EasyApe expects **two endpoints** on the license server:

1) **POST** `/v1/bootstrap`  
   Called on startup. Server should create the install record (if new), start trial if needed, and return links.

2) **POST** `/v1/status`  
   Called on stake/unstake attempts (and occasionally by operators). Returns paid/trial state + links.

Full schemas are in `docs/API.md`.

## Grace mode (paid installs only)
If the license server becomes temporarily unreachable, EasyApe can allow stake/unstake for a short window
(default **24 hours**) **only if** the install was confirmed paid recently.

This prevents accidental downtime for paid operators while still making the server the source of truth.
