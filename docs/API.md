# License Server API Contract (Recommended)

EasyApe calls a license server to determine whether `stake` / `unstake` are allowed and to retrieve a **payment link**
that can be sent to a user on a headless server (no email required).

Base URL is configured as:
- `licensing.server_url` in `config.yaml`, or
- `EASYAPE_LICENSE_SERVER_URL` env var

EasyApe will call:
- `{server_url}/v1/bootstrap`
- `{server_url}/v1/status`

## Identity fields

EasyApe identifies an install using:

- `install_id` — random UUID generated once per install, stored locally
- `fingerprint` — one-way SHA256 hash derived from machine identity (does not expose raw IDs)

## 1) POST /v1/bootstrap

Called once on startup.

### Request
```json
{
  "install_id": "9f4c... (uuid hex)",
  "fingerprint": "3b27... (sha256 hex)",
  "app": "easyape",
  "version": "unknown",
  "ts": 1700000000
}
```

### Response (200)
```json
{
  "paid": false,
  "trial": {
    "active": true,
    "started_at": "2026-02-04T18:00:00Z",
    "expires_at": "2026-02-07T18:00:00Z"
  },
  "billing_url": "https://pay.example.com/checkout?install=...",
  "manage_url": "https://pay.example.com/manage?install=...",
  "server_time": "2026-02-04T18:00:00Z"
}
```

Notes:
- `billing_url` should create a **Stripe Checkout** session (or equivalent) tied to this install.
- Time fields may be ISO8601 (`...Z`) or unix seconds (`*_ts`). EasyApe accepts either.

## 2) POST /v1/status

Called on every `stake` / `unstake` attempt.

### Request
```json
{
  "install_id": "9f4c... (uuid hex)",
  "fingerprint": "3b27... (sha256 hex)"
}
```

### Response (200)
Same schema as `/v1/bootstrap`.

If access should be locked:
```json
{
  "paid": false,
  "trial": { "active": false },
  "billing_url": "https://pay.example.com/checkout?install=...",
  "server_time": "2026-02-07T18:00:00Z"
}
```

## Minimal server-side storage (recommended)
To keep data minimal, store only:
- `install_id`, `fingerprint`
- `trial_started_at`, `trial_expires_at`
- `paid` status + Stripe customer/subscription IDs (server-side only)

Do **not** store usage (commands, amounts, messages). EasyApe does not send it.

## Security recommendations
- Rate limit `/v1/status`
- Return short-lived signed links for `billing_url` and `manage_url`
- Consider requiring HTTPS only
