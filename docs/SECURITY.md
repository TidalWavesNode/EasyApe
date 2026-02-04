# Security notes (read this)

Chat-triggered staking is dangerous because:
- messaging accounts can be compromised
- tokens can leak
- group chats amplify risk
- social engineering + prompt injection can trick you into approving actions

## Strongly recommended
1) Use a **dedicated wallet** with limited funds for this bot
2) Keep **require_confirmation=true**
3) Keep strict **allow-lists** (per platform)
4) Keep **caps** low:
   - max_amount_per_tx
   - daily_max_amount
5) Avoid group chats; run in DMs only (default)
6) Monitor logs and add alerting

## What this bot DOES NOT do
- It does not execute arbitrary shell commands.
- It only runs an allow-listed subset of btcli actions (stake add/remove/list).
- It defaults to dry-run.

If you deploy this for others later, isolate each customer:
- separate wallet keys
- separate process/container
- per-customer allow-lists and limits

## Passwords

If you use encrypted wallets, store passwords in environment variables (not in git).
This MVP supports feeding the password to `btcli` via stdin (best-effort). Consider:
- using a dedicated low-funds wallet
- running on a hardened host
- keeping confirmations ON
