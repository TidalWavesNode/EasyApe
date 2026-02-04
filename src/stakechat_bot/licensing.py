from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from .config import RootConfig
from .storage import JsonStore


@dataclass(frozen=True)
class LicenseDecision:
    allowed: bool
    reason: str  # human-friendly message (empty if allowed)


def _read_machine_id() -> str:
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            if os.path.exists(p):
                v = open(p, "r", encoding="utf-8").read().strip()
                if v:
                    return v
        except Exception:
            pass
    return ""


def machine_fingerprint() -> str:
    """
    Returns a stable-but-anonymous fingerprint for licensing.
    This is a one-way SHA256 hash; it does NOT expose raw hardware IDs.
    """
    base = "|".join(
        [
            _read_machine_id(),
            platform.node(),
            platform.system(),
            platform.machine(),
            hex(uuid.getnode()),
        ]
    ).encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()


def _parse_ts(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        pass
    try:
        s = str(x).strip()
        if not s:
            return None
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


class LicenseManager:
    """
    Server-authoritative licensing (Option A, automatic).

    Contract (docs/API.md):
      - POST {server_url}/v1/bootstrap   (called on startup)
      - POST {server_url}/v1/status     (called on stake/unstake attempts; and periodically via bootstrap)

    Allowed if:
      paid == true OR trial.active == true

    Grace mode:
      If the license server is temporarily unreachable, and PAID was confirmed recently,
      allow stake/unstake for `grace_hours` (default 24h).
    """

    def __init__(self, cfg: RootConfig, store: JsonStore):
        self.cfg = cfg
        self.store = store

        self.server_url = (
            (getattr(cfg.licensing, "server_url", "") or "").strip()
            or os.getenv("EASYAPE_LICENSE_SERVER_URL", "").strip()
            or "https://license.easyape.io"
        ).rstrip("/")

        try:
            self.grace_hours = int(getattr(cfg.licensing, "grace_hours", 24))
        except Exception:
            self.grace_hours = 24

    # -------------------------
    # Identity
    # -------------------------
    def install_id(self) -> str:
        with self.store.with_lock():
            v = str(self.store.get_session("install_id", "") or "").strip()
            if v:
                return v
            v = uuid.uuid4().hex
            self.store.set_session("install_id", v)
            return v

    def fingerprint(self) -> str:
        with self.store.with_lock():
            v = str(self.store.get_session("fingerprint", "") or "").strip()
            if v:
                return v
            v = machine_fingerprint()
            self.store.set_session("fingerprint", v)
            return v

    def _payload(self) -> Dict[str, Any]:
        return {
            "install_id": self.install_id(),
            "fingerprint": self.fingerprint(),
            "app": "easyape",
            "version": os.getenv("EASYAPE_VERSION", "unknown"),
            "ts": int(time.time()),
        }

    # -------------------------
    # Cache
    # -------------------------
    def _cache_from_server(self, obj: Dict[str, Any]) -> None:
        paid = bool(obj.get("paid", False))
        trial = obj.get("trial") if isinstance(obj.get("trial"), dict) else {}
        trial_active = bool(trial.get("active", False))
        trial_started = _parse_ts(trial.get("started_at")) or _parse_ts(trial.get("started_ts"))
        trial_expires = _parse_ts(trial.get("expires_at")) or _parse_ts(trial.get("expires_ts"))

        billing_url = str(obj.get("billing_url", "") or "").strip()
        manage_url = str(obj.get("manage_url", "") or "").strip()

        server_time = str(obj.get("server_time", "") or "").strip()
        server_ts = _parse_ts(server_time) if server_time else None

        now = time.time()
        with self.store.with_lock():
            self.store.set_session("license_paid", paid)
            self.store.set_session("trial_active", trial_active)
            if trial_started is not None:
                self.store.set_session("trial_started_ts", float(trial_started))
            if trial_expires is not None:
                self.store.set_session("trial_expires_ts", float(trial_expires))
            if billing_url:
                self.store.set_session("billing_url", billing_url)
            if manage_url:
                self.store.set_session("manage_url", manage_url)
            if server_ts is not None:
                self.store.set_session("server_time_ts", float(server_ts))
                self.store.set_session("server_time_iso", server_time)

            self.store.set_session("license_last_ok_ts", float(now))
            if paid:
                self.store.set_session("license_last_paid_ok_ts", float(now))
            self.store.set_session("license_last_error", "")

    def cached(self) -> Dict[str, Any]:
        with self.store.with_lock():
            return {
                "paid": bool(self.store.get_session("license_paid", False)),
                "trial_active": bool(self.store.get_session("trial_active", False)),
                "trial_started_ts": self.store.get_session("trial_started_ts", None),
                "trial_expires_ts": self.store.get_session("trial_expires_ts", None),
                "billing_url": str(self.store.get_session("billing_url", "") or ""),
                "manage_url": str(self.store.get_session("manage_url", "") or ""),
                "license_last_ok_ts": self.store.get_session("license_last_ok_ts", None),
                "license_last_paid_ok_ts": self.store.get_session("license_last_paid_ok_ts", None),
                "license_last_error": str(self.store.get_session("license_last_error", "") or ""),
                "server_time_iso": str(self.store.get_session("server_time_iso", "") or ""),
            }

    def links(self) -> Dict[str, str]:
        c = self.cached()
        return {"billing_url": c["billing_url"], "manage_url": c["manage_url"]}

    def trial_status_line(self) -> str:
        c = self.cached()
        if c["paid"]:
            return "✅ License: PAID (full access)"
        if c["trial_active"]:
            exp = c.get("trial_expires_ts")
            if exp:
                try:
                    exp_s = datetime.fromtimestamp(float(exp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    return f"🕒 Trial: ACTIVE (ends {exp_s})"
                except Exception:
                    pass
            return "🕒 Trial: ACTIVE"
        return "🔒 Trial: INACTIVE (stake/unstake locked)"

    # -------------------------
    # Server calls
    # -------------------------
    def _post_json(self, url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        r = requests.post(url, json=payload, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"message": (r.text or "").strip()}
        if not isinstance(data, dict):
            data = {"message": str(data)}
        if r.status_code >= 400:
            data.setdefault("message", f"HTTP {r.status_code}")
        return data

    async def bootstrap(self) -> None:
        url = f"{self.server_url}/v1/bootstrap"
        try:
            obj = await asyncio.to_thread(self._post_json, url, self._payload(), 10)
            if isinstance(obj, dict):
                self._cache_from_server(obj)
        except Exception as e:
            with self.store.with_lock():
                self.store.set_session("license_last_error", f"bootstrap: {e}")

    async def refresh_status(self) -> Optional[Dict[str, Any]]:
        url = f"{self.server_url}/v1/status"
        payload = {"install_id": self.install_id(), "fingerprint": self.fingerprint()}
        try:
            obj = await asyncio.to_thread(self._post_json, url, payload, 10)
            if isinstance(obj, dict):
                self._cache_from_server(obj)
                return obj
        except Exception as e:
            with self.store.with_lock():
                self.store.set_session("license_last_error", f"status: {e}")
        return None

    # -------------------------
    # Enforcement gate
    # -------------------------
    async def can_trade(self) -> LicenseDecision:
        obj = await self.refresh_status()
        c = self.cached()
        if c["paid"] or c["trial_active"]:
            return LicenseDecision(True, "")

        # Grace mode ONLY for paid installs and ONLY if server is down.
        if obj is None:
            last_paid_ok = c.get("license_last_paid_ok_ts")
            if last_paid_ok:
                try:
                    age = time.time() - float(last_paid_ok)
                    if age <= self.grace_hours * 3600:
                        return LicenseDecision(
                            True,
                            "⚠️ License server unreachable. Grace mode active (paid was confirmed recently).",
                        )
                except Exception:
                    pass

        links = self.links()
        msg = "🔒 Stake/unstake locked."
        if links.get("billing_url"):
            msg += f" Subscribe: {links['billing_url']}"
        err = c.get("license_last_error", "")
        if err:
            msg += f" (debug: {err})"
        return LicenseDecision(False, msg)
