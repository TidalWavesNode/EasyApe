from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import portalocker


@dataclass
class PendingAction:
    created_ts: float
    expires_ts: float
    action: Dict[str, Any]  # serialized Action
    platform: str
    sender_id: str


class JsonStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"pending": {}, "daily": {}, "session": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"pending": {}, "daily": {}, "session": {}}

    def _save(self, data: Dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def with_lock(self):
        lock_path = str(self.path) + ".lock"
        return portalocker.Lock(lock_path, timeout=10)

    # Pending
    def get_pending(self, token: str) -> Optional[PendingAction]:
        data = self._load()
        item = data.get("pending", {}).get(token)
        if not item:
            return None
        return PendingAction(**item)

    def set_pending(self, token: str, pending: PendingAction) -> None:
        data = self._load()
        data.setdefault("pending", {})[token] = {
            "created_ts": pending.created_ts,
            "expires_ts": pending.expires_ts,
            "action": pending.action,
            "platform": pending.platform,
            "sender_id": pending.sender_id,
        }
        self._save(data)

    def del_pending(self, token: str) -> None:
        data = self._load()
        if token in data.get("pending", {}):
            del data["pending"][token]
            self._save(data)

    # Session settings
    def set_session(self, key: str, value: Any) -> None:
        data = self._load()
        data.setdefault("session", {})[key] = value
        self._save(data)

    def get_session(self, key: str, default: Any = None) -> Any:
        data = self._load()
        return data.get("session", {}).get(key, default)

    # Daily tracking
    def add_daily(self, day_key: str, sender_key: str, bucket: str, amount: float) -> float:
        data = self._load()
        data.setdefault("daily", {}).setdefault(day_key, {}).setdefault(sender_key, {}).setdefault(bucket, 0.0)
        data["daily"][day_key][sender_key][bucket] = float(data["daily"][day_key][sender_key][bucket]) + float(amount)
        self._save(data)
        return float(data["daily"][day_key][sender_key][bucket])

    def get_daily(self, day_key: str, sender_key: str, bucket: str) -> float:
        data = self._load()
        return float(data.get("daily", {}).get(day_key, {}).get(sender_key, {}).get(bucket, 0.0))
