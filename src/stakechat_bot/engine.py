from __future__ import annotations

import asyncio
import logging
import os
import time
import json
from dataclasses import dataclass
from typing import List, Optional

from .bittensor_client import BittensorClient, StakeResult
from .config import RootConfig
from .parser import (
    Help, Privacy, Whoami, Confirm,
    ParsedStake, Unknown, parse_message,
)
from .utils.jsonlog import append_jsonl

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
HISTORY_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "trade_history.jsonl"))


# ──────────────────────────────────────────────────────────────────────────────
# Response types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Button:
    text: str
    action: str
    tx_id: str = "0"


@dataclass
class BotResponse:
    text: str
    buttons: Optional[List[List[Button]]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Pending confirmation store
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _PendingOp:
    action: str
    expires_at: float


class _PendingStore:
    def __init__(self):
        self._store: dict[str, _PendingOp] = {}

    def save(self, user_key: str, action: str, ttl: int) -> None:
        self._store[user_key] = _PendingOp(action, time.time() + ttl)

    def pop(self, user_key: str) -> Optional[str]:
        op = self._store.pop(user_key, None)
        if op and time.time() < op.expires_at:
            return op.action
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class Engine:
    def __init__(self, cfg: RootConfig):
        self.cfg = cfg
        self._pending = _PendingStore()

        self._btclient = BittensorClient(
            network=self._subtensor_network(),
            wallets_path=self._wallets_path(),
        )

        self._wallet = None  # lazy load

    # ── Config helpers ────────────────────────────────────────────────────────

    def _subtensor_network(self) -> str:
        """Return configured subtensor network."""
        args = list(getattr(self.cfg.btcli, "common_args", []) or [])

        for i, a in enumerate(args):
            if a == "--subtensor.network" and i + 1 < len(args):
                return str(args[i + 1]).strip()

        for v in args:
            if str(v).lower() in ("finney", "test", "local"):
                return str(v)

        return "finney"

    def _wallets_path(self) -> str:
        w = self.cfg.btcli.wallets.get(self.cfg.btcli.default_wallet)
        if w:
            return w.wallets_dir
        return os.path.expanduser("~/.bittensor/wallets")

    def _load_wallet(self):
        wallet_cfg = self.cfg.btcli.wallets.get(self.cfg.btcli.default_wallet)
        if not wallet_cfg:
            raise ValueError("Wallet missing from config")

        return self._btclient.load_wallet(
            coldkey_name=wallet_cfg.coldkey,
            password=wallet_cfg.password or "",
        )

    async def _get_wallet(self):
        if self._wallet is None:
            self._wallet = self._load_wallet()
        return self._wallet

    def _default_netuid(self) -> Optional[int]:
        w = self.cfg.btcli.wallets.get(self.cfg.btcli.default_wallet)
        if w and w.default_netuid is not None:
            return w.default_netuid
        return self.cfg.defaults.netuid

    def _default_hotkey(self) -> Optional[str]:
        if self.cfg.defaults.validator:
            from .validators import ValidatorResolver
            resolver = ValidatorResolver(self.cfg.validators)
            return resolver.resolve(self.cfg.defaults.validator)
        return None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _is_authorized(self, platform: str, user_id: int) -> bool:
        if platform == "telegram":
            allowed = self.cfg.auth.telegram_user_ids
            return not allowed or user_id in allowed
        return True

    def _user_key(self, platform: str, user_id: int) -> str:
        return f"{platform}:{user_id}"

    # ── Entry point ───────────────────────────────────────────────────────────

    async def handle_text_async(
        self, platform, user_id, user_name, chat_id, is_group, text
    ) -> BotResponse:

        if not self._is_authorized(platform, user_id):
            return BotResponse("🔒 Unauthorized.")

        action = parse_message(text)

        if isinstance(action, Help):
            return self._help()

        if isinstance(action, ParsedStake):
            return await self._stake(action.amount, action.netuid)

        if isinstance(action, Unknown):
            if text.lower() in ("balance", "portfolio"):
                return await self._balance()

        return BotResponse("❓ Unknown command")

    # ── Portfolio ─────────────────────────────────────────────────────────────

    async def _balance(self) -> BotResponse:
        wallet = await self._get_wallet()
        bal = await self._btclient.get_balance(wallet)
        history = self._load_history()

        total_cost = sum(t.get("tao_spent", 0) for t in history if t["type"] == "stake")
        realized = sum(t.get("tao_received", 0) for t in history if t["type"] == "unstake")

        lines = ["🦍 *Portfolio*\n"]
        lines.append(f"Free Balance: `{bal.free_tao:.4f} τ`\n")

        if total_cost:
            total_value = sum(s["tao_value"] for s in bal.stakes)
            unrealized = total_value - total_cost
            total_pnl = unrealized + realized
            roi = (total_pnl / total_cost) * 100

            color = "🟢" if total_pnl >= 0 else "🔴"

            lines.append(f"Portfolio PnL: {color} `{total_pnl:+.4f} τ`")
            lines.append(f"Portfolio ROI: {color} `{roi:+.2f}%`\n")

        return BotResponse("\n".join(lines))

    # ── History ───────────────────────────────────────────────────────────────

    def _load_history(self):
        if not os.path.exists(HISTORY_FILE):
            return []

        records = []
        with open(HISTORY_FILE) as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except:
                    pass
        return records

    # ── Info ──────────────────────────────────────────────────────────────────

    def _help(self):
        return BotResponse(
            "🦍 *Commands*\n"
            "`balance` — Portfolio\n"
            "`stake <amt> <netuid>`"
        )
