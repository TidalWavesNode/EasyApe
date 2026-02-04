# Privacy & Data Sent to the License Server

EasyApe is self-hosted and never uploads wallet keys, seed phrases, wallet names, or your wallet password.

## When EasyApe contacts the license server
- On startup (to bootstrap/refresh trial + license state)
- When a user attempts `stake` or `unstake` (to authorize access)

Read-only commands (`help`, `whoami`, `inventory`, `balance`) do not require a license check.

## What is sent (minimal)
EasyApe sends a small JSON payload containing:
- `install_id` (random UUID generated once per install)
- `fingerprint` (a one-way SHA256 hash; not raw hardware IDs)
- `app` (string, e.g. `easyape`)
- `version` (optional app version string)
- `ts` (timestamp)

## What is NOT sent
- No private keys / seed phrases
- No wallet password
- No wallet names or addresses (licensing is not tied to your chain identity)
- No stake/unstake commands, amounts, validator choices, or message contents
- No telemetry / analytics

## Stripe / payments
Payments are processed by Stripe. EasyApe does not store card data.
Stripe may collect billing details per Stripe’s policies.

## Server-side source of truth
Trial start and expiry are determined by the license server. The server may store:
- trial start/expiry per `fingerprint` + `install_id`
- subscription status for that install

See `docs/API.md` for the minimal API contract.
