"""
stakechat_bot.engine
~~~~~~~~~~~~~~~~~~~~
Core logic layer — handles all commands and produces BotResponse objects.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
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
# Pending-confirmation store
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _PendingOp:
    action: str
    expires_at: float


class _PendingStore:
    def __init__(self):
        self._store: dict[str, _PendingOp] = {}

    def save(self, user_key: str, action: str, ttl: int) -> None:
        self._store[user_key] = _PendingOp(action=action, expires_at=time.time() + ttl)

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
        self._wallet = None

    # ── Config helpers ────────────────────────────────────────────────────────

    def _subtensor_network(self) -> str:
        args = list(getattr(self.cfg.btcli, "common_args", []) or [])
        for i, a in enumerate(args):
            if a == "--subtensor.network" and i + 1 < len(args):
                v = str(args[i + 1]).strip()
                if v:
                    return v
        return "finney"

    def _wallets_path(self) -> str:
        w = self.cfg.btcli.wallets.get(self.cfg.btcli.default_wallet)
        return w.wallets_dir if w else os.path.expanduser("~/.bittensor/wallets")

    def _load_wallet(self):
        wallet_cfg = self.cfg.btcli.wallets.get(self.cfg.btcli.default_wallet)
        if not wallet_cfg:
            raise ValueError(f"Wallet '{self.cfg.btcli.default_wallet}' not in config")
        return self._btclient.load_wallet(
            coldkey_name=wallet_cfg.coldkey,
            password=wallet_cfg.password or "",
        )

    async def _get_wallet(self):
        if self._wallet is None:
            self._wallet = self._load_wallet()
        return self._wallet

    def _default_netuid(self) -> Optional[int]:
        return self.cfg.defaults.netuid

    def _default_hotkey(self) -> Optional[str]:
        from .validators import ValidatorResolver
        resolver = ValidatorResolver(self.cfg.validators)
        return resolver.resolve(self.cfg.defaults.validator)

    # ── Command normalization ─────────────────────────────────────────────────

    _TRAILING_JUNK_RE = re.compile(r"[^\w/]+$")

    def _normalize_cmd(self, raw_text: str) -> str:
        t = (raw_text or "").strip()
        if not t:
            return ""
        token = t.split()[0].strip()
        token = self._TRAILING_JUNK_RE.sub("", token)
        if token.startswith("/"):
            token = token[1:]
        return token.lower()

    # ── Public async entry ────────────────────────────────────────────────────

    async def handle_text_async(self, platform, user_id, user_name, chat_id, is_group, text):
        cmd = self._normalize_cmd(text)

        if cmd in ("help", "start", "?"):
            return self._help()
        if cmd in ("balance", "portfolio"):
            return await self._balance()
        if cmd == "confirm":
            return await self._handle_confirm(f"{platform}:{user_id}")

        action = parse_message(text)

        if isinstance(action, ParsedStake):
            return await self._handle_stake_action(action, f"{platform}:{user_id}")

        return BotResponse("❓ Unknown command.\nType `help`")

    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_stake_action(self, action: ParsedStake, user_key: str):
        netuid = action.netuid or self._default_netuid()

        if action.op == "add":
            return await self._confirm_stake(action.amount, netuid, user_key)

        is_all = action.amount == 0 or str(action.amount).lower() == "all"
        if is_all:
            self._pending.save(user_key, f"unstake_all_confirm:{netuid}", 30)
            return BotResponse("🚨 Confirm unstake ALL")

        self._pending.save(user_key, f"unstake_confirm:{action.amount}:{netuid}", 30)
        return BotResponse("⚠️ Confirm unstake")

    # ─────────────────────────────────────────────────────────────────────────
    # ✅ UPDATED Stake Confirm Dialog
    # ─────────────────────────────────────────────────────────────────────────

    async def _confirm_stake(self, amount: float, netuid: int, user_key: str):

        wallet = await self._get_wallet()
        bal = await self._btclient.get_balance(wallet)
        rate = await self._btclient.get_exchange_rate(netuid)

        est_alpha = amount / rate if rate > 0 else 0.0

        self._pending.save(user_key, f"stake_confirm:{amount}:{netuid}", 30)

        return BotResponse(
            text=(
                f"⚠️ *Confirm Stake*\n\n"
                f"Subnet: `{netuid}`\n"
                f"Amount: `{amount:.4f} τ`\n"
                f"Available: `{bal.free_tao:.4f} τ`\n"
                f"Rate: `{rate:.6f} τ/α`\n"
                f"Est. Received: `{est_alpha:.6f} α`\n\n"
                f"ℹ️ Final execution price may vary slightly\n"
                f"due to subnet price impact / slippage."
            ),
            buttons=[[Button("✅ Confirm", f"stake_confirm:{amount}:{netuid}"),
                      Button("❌ Cancel", "cancel")]],
        )

    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_confirm(self, user_key: str):
        pending = self._pending.pop(user_key)
        if not pending:
            return BotResponse("⏰ No pending action")
        return await self._dispatch_action(pending)

    async def _dispatch_action(self, action: str):

        wallet = await self._get_wallet()

        if action.startswith("stake_confirm:"):
            _, amount, netuid = action.split(":")
            return await self._stake(float(amount), int(netuid))

        return BotResponse("❌ Unknown action")

    # ─────────────────────────────────────────────────────────────────────────
    # ✅ UPDATED Stake Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def _stake(self, amount: float, netuid: int):

        wallet = await self._get_wallet()
        bal = await self._btclient.get_balance(wallet)

        if bal.free_tao < amount:
            return BotResponse(
                "❌ Not enough balance\n\n"
                f"Available: `{bal.free_tao:.6f} τ`\n"
                f"Required: `{amount:.6f} τ`"
            )

        hotkey = self._default_hotkey()

        result: StakeResult = await self._btclient.add_stake(
            wallet=wallet,
            tao=amount,
            netuid=netuid,
            hotkey_ss58=hotkey,
        )

        if not result.ok:
            return BotResponse(f"❌ Stake failed\n\n`{result.message}`")

        append_jsonl(HISTORY_FILE, {
            "type": "stake",
            "netuid": netuid,
            "tao_spent": result.tao_amount,
            "alpha_bought": result.alpha_amount,
            "rate": result.rate,
        })

        return BotResponse(
            f"✅ *Stake Confirmed*\n\n"
            f"Subnet: `{netuid}`\n"
            f"Spent: `{result.tao_amount:.4f} τ`\n"
            f"Received: `{result.alpha_amount:.6f} α`\n"
            f"Entry Price: `{result.rate:.6f} τ/α`\n"
            f"Cost Basis: `{result.tao_amount:.4f} τ`"
        )

    # ─────────────────────────────────────────────────────────────────────────

    async def _balance(self):

        wallet = await self._get_wallet()
        bal = await self._btclient.get_balance(wallet)

        return BotResponse(
            f"🦍 *Portfolio*\n\n"
            f"Free Balance: `{bal.free_tao:.4f} τ`"
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _help(self):
        return BotResponse(
            "🦍 *EasyApe Commands*\n\n"
            "`balance`\n"
            "`stake <amount> <netuid>`\n"
            "`confirm`"
        )

    def _privacy(self):
        return BotResponse("🔒 Privacy")

    def _whoami(self, user_id, user_name):
        return BotResponse(f"👤 `{user_name}`")
