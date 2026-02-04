from __future__ import annotations

import datetime as dt
import os
import secrets
import time
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple, List

from .btcli import (
    BtcliResult,
    build_stake_add_cmd,
    build_stake_list_cmd,
    build_stake_remove_cmd,
    build_wallet_balance_cmd,
    build_wallet_balance_cmd_alt,
    extract_alpha_for,
    extract_free_tao,
    run_btcli,
    try_parse_json,
)
from .config import RootConfig, BtcliWalletProfile
from .parser import (
    Action,
    ActionCancel,
    ActionConfirm,
    ActionHelp,
    ActionWhoAmI,
    ActionMode,
    ActionStake,
    ActionUnstake,
    ActionWallets,
    ActionValidatorsRefresh,
    ActionValidatorsSearch,
    ActionValidatorsSources,
    ActionShowDefaults,
    ActionSetDefaultValidator,
    ActionSetNetuidValidator,
    ActionSetWalletDefaultValidator,
    ActionSetWalletNetuidValidator,
    ActionSetWalletDefaultNetuid,
    ActionInventory,
    ActionBalance,
    ActionBilling,
    ActionPrivacy,
    ActionDoctor,
    parse_action,
)
from .policy import Sender, is_allowed
from .storage import JsonStore, PendingAction
from .licensing import LicenseManager
from .validators import ValidatorResolver, ValidatorEntry, looks_like_ss58


HELP_TEXT = """EasyApe — Text to stake 🦍

Core commands:
- help
- whoami                  # shows your platform ID (for onboarding)
- mode dry|live
- wallets
- inventory [wallet]        # stake inventory (uses default wallet if omitted)
- balance [wallet]          # TAO balance (uses default wallet if omitted)

Validator registry:
- validators sources
- validators refresh
- validators search <term>

Defaults & routing:
- show defaults
- set default validator <name|ss58>
- set netuid <netuid> validator <name|ss58>
- set wallet <wallet> default validator <name|ss58>
- set wallet <wallet> netuid <netuid> validator <name|ss58>
- set wallet <wallet> default netuid <netuid>

Staking:
- stake [wallet] <netuid> <tao_amount> [validator]
- unstake [wallet] <netuid> <alpha_amount> [validator]

Turbo (optional):
- stake [wallet] <amount> [validator]
- unstake [wallet] <amount> [validator]
Works only if that wallet has a default_netuid configured.
To avoid ambiguity, amount-only requires a decimal (e.g. 0.10 not 1).

Validator routing when omitted:
1) runtime overrides (set ...)
2) wallet.validator_by_netuid[netuid]
3) wallet.validator_all
4) defaults.validator_by_netuid[netuid]
5) defaults.validator_all
6) wallet.default_validator (legacy fallback)

Licensing:
- 3-day free trial (stake/unstake enabled)
- After trial, stake/unstake require EASYAPE_LICENSE_KEY

Safety:
- DRY mode never runs btcli.
- LIVE mode requires confirm <token> by default.
- Transfers are NEVER supported (stake/unstake only).
"""


def _day_key(tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
        now = dt.datetime.now(tz=tz)
    except Exception:
        now = dt.datetime.utcnow()
    return now.strftime("%Y-%m-%d")


def _sender_key(sender: Sender) -> str:
    return f"{sender.platform}:{sender.sender_id}"


def _truncate(s: str, n: int = 1200) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "\n…(truncated)"


class Engine:
    def __init__(self, cfg: RootConfig):
        self.cfg = cfg
        os.makedirs(cfg.app.data_dir, exist_ok=True)
        self.store = JsonStore(os.path.join(cfg.app.data_dir, "state.json"))
        self.licensing = LicenseManager(cfg, self.store)
        self.log_file = cfg.app.log_file
        self.validators = ValidatorResolver(cfg)

    def _new_token(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(6))

    def _effective_mode(self) -> str:
        mode = self.cfg.app.mode
        try:
            mode2 = str(self.store.get_session("mode", mode)).lower()
            if mode2 in ("dry", "live"):
                return mode2
        except Exception:
            pass
        return mode

def _rate_bucket(self, sender: Sender) -> str:
    return f"{sender.platform}:{sender.sender_id}"

def _rate_limit_ok(self, sender: Sender) -> Optional[str]:
    now = time.time()
    bucket = self._rate_bucket(sender)
    key_m = f"rlm:{bucket}:{int(now // 60)}"
    key_h = f"rlh:{bucket}:{int(now // 3600)}"

    with self.store.with_lock():
        mcount = int(self.store.get_session(key_m, 0) or 0)
        hcount = int(self.store.get_session(key_h, 0) or 0)

        if mcount >= int(self.cfg.app.rate_limit_per_minute):
            return f"⏳ Rate limit hit: {self.cfg.app.rate_limit_per_minute}/min. Try again soon."
        if hcount >= int(self.cfg.app.rate_limit_per_hour):
            return f"⏳ Rate limit hit: {self.cfg.app.rate_limit_per_hour}/hr. Try again later."

        self.store.set_session(key_m, mcount + 1)
        self.store.set_session(key_h, hcount + 1)

    return None

    def _stdin_for(self, wallet: BtcliWalletProfile) -> Optional[str]:
        pw = (wallet.password or "").strip()
        if not pw:
            return None
        # Support env var references: password: "env:MY_WALLET_PW"
        if pw.startswith("env:"):
            pw = os.getenv(pw.split("env:", 1)[1], "").strip()
        if not pw:
            return None
        return (pw + "\n") * 3

    def _get_routing(self) -> Dict[str, Any]:
        val = self.store.get_session("routing", None)
        if isinstance(val, dict):
            return val
        return {}

    def _set_routing(self, routing: Dict[str, Any]) -> None:
        self.store.set_session("routing", routing)

    # -------------------------
    # Wallet / defaults routing
    # -------------------------
    def _resolve_wallet(self, wallet_raw: Optional[str]) -> BtcliWalletProfile:
        if wallet_raw:
            if wallet_raw in self.cfg.btcli.wallets:
                return self.cfg.btcli.wallets[wallet_raw]
            for w in self.cfg.btcli.wallets.values():
                if w.wallet_name == wallet_raw:
                    return w
            raise ValueError(f"Unknown wallet '{wallet_raw}'. Send 'wallets' to see allowed wallets.")
        return self.cfg.btcli.wallets[self.cfg.btcli.default_wallet]

    def _routing_wallet_overrides(self, wallet_alias: str) -> Dict[str, Any]:
        routing = self._get_routing()
        wallets = routing.get("wallets", {})
        if isinstance(wallets, dict) and wallet_alias in wallets and isinstance(wallets[wallet_alias], dict):
            return wallets[wallet_alias]
        return {}

    def _get_default_netuid(self, wallet: BtcliWalletProfile) -> Optional[int]:
        wovr = self._routing_wallet_overrides(wallet.alias)
        v = wovr.get("default_netuid", None)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
        return wallet.default_netuid

    def _get_default_validator_raw(self, wallet: BtcliWalletProfile, netuid: int) -> str:
        routing = self._get_routing()
        wovr = self._routing_wallet_overrides(wallet.alias)

        # 1) runtime overrides (wallet netuid)
        wbn = wovr.get("validator_by_netuid", {})
        if isinstance(wbn, dict):
            if str(netuid) in wbn and str(wbn[str(netuid)]).strip():
                return str(wbn[str(netuid)]).strip()
            if netuid in wbn and str(wbn[netuid]).strip():
                return str(wbn[netuid]).strip()

        # 2) runtime overrides (wallet all)
        if str(wovr.get("validator_all", "")).strip():
            return str(wovr.get("validator_all")).strip()

        # 3) runtime overrides (global netuid)
        gbn = routing.get("validator_by_netuid", {})
        if isinstance(gbn, dict):
            if str(netuid) in gbn and str(gbn[str(netuid)]).strip():
                return str(gbn[str(netuid)]).strip()
            if netuid in gbn and str(gbn[netuid]).strip():
                return str(gbn[netuid]).strip()

        # 4) runtime overrides (global all)
        if str(routing.get("validator_all", "")).strip():
            return str(routing.get("validator_all")).strip()

        # 5) wallet config per-netuid
        if netuid in wallet.validator_by_netuid and str(wallet.validator_by_netuid[netuid]).strip():
            return str(wallet.validator_by_netuid[netuid]).strip()

        # 6) wallet config all
        if str(wallet.validator_all or "").strip():
            return str(wallet.validator_all).strip()

        # 7) global config per-netuid
        if netuid in self.cfg.defaults.validator_by_netuid and str(self.cfg.defaults.validator_by_netuid[netuid]).strip():
            return str(self.cfg.defaults.validator_by_netuid[netuid]).strip()

        # 8) global config all
        if str(self.cfg.defaults.validator_all or "").strip():
            return str(self.cfg.defaults.validator_all).strip()

        # 9) legacy wallet default
        if str(wallet.default_validator or "").strip():
            return str(wallet.default_validator).strip()

        return ""

    def _resolve_validator(self, raw: Optional[str], wallet: BtcliWalletProfile, netuid: int) -> ValidatorEntry:
        raw2 = (raw or "").strip()
        if raw2 and looks_like_ss58(raw2):
            return ValidatorEntry(name=raw2, hotkey=raw2, source="ss58")

        if not raw2:
            raw2 = self._get_default_validator_raw(wallet, netuid)

        if not raw2:
            raise ValueError("No validator provided and no default validator is configured (wallet/defaults).")

        match, cands = self.validators.resolve(raw2)
        if match:
            return match
        if cands:
            opts = "\n".join([f"- {c.name} -> {c.hotkey}" for c in cands])
            raise ValueError(
                "Validator name is ambiguous. Try a more specific name or paste the hotkey SS58. Top matches:\n" + opts
            )
        raise ValueError("Validator not found. Try a different name or paste the hotkey SS58.")

    async def _snapshot(self, wallet: BtcliWalletProfile, netuid: int, validator_hotkey: str) -> Tuple[Optional[float], Optional[float]]:
        bal_cmd = build_wallet_balance_cmd(self.cfg, wallet.wallet_name)
        stake_cmd = build_stake_list_cmd(self.cfg, wallet.wallet_name)

        bal_res = await run_btcli(bal_cmd, stdin_text=self._stdin_for(wallet))
        if bal_res.returncode != 0:
            bal_cmd2 = build_wallet_balance_cmd_alt(self.cfg, wallet.wallet_name)
            bal_res = await run_btcli(bal_cmd2, stdin_text=self._stdin_for(wallet))

        stake_res = await run_btcli(stake_cmd, stdin_text=self._stdin_for(wallet))

        bal_j = try_parse_json(bal_res.stdout) or try_parse_json(bal_res.stderr)
        stake_j = try_parse_json(stake_res.stdout) or try_parse_json(stake_res.stderr)

        free = extract_free_tao(bal_j) if bal_j is not None else None
        alpha = extract_alpha_for(stake_j, netuid=netuid, validator_hotkey=validator_hotkey) if stake_j is not None else None
        return free, alpha

    async def handle(self, sender: Sender, text: str) -> str:

        # Defense in depth: hard block any transfer-like intents (we never allow transfers).
        low = (text or "").lower()
        if any(w in low for w in [
            "transfer", "send", "withdraw", "deposit", "move",
            "cashout", "cash out", "payout", "pay out", "bridge", "tip",
            "wallet address", "to address", "address",
        ]):
            return "🚫 Transfers are not supported. EasyApe only does stake/unstake + read-only commands (inventory/balance)."

        action, err = parse_action(text)
        if err:
            return err
        assert action is not None

        # Allow onboarding commands without authorization
        if isinstance(action, ActionHelp):
            return self._help_text(sender)

        if isinstance(action, ActionWhoAmI):
            return self._handle_whoami(sender)

        if isinstance(action, ActionBilling):
            return await self._handle_billing(sender)

        if isinstance(action, ActionPrivacy):
            return self._handle_privacy()

        if not is_allowed(self.cfg, sender):
            # Keep this useful on headless servers: include a billing link if available.
            links = self.licensing.links()
            sub = links.get('billing_url') or ''
            msg = "Not authorized. Send 'whoami' to get your ID, then add it to config.yaml allow-lists."
            if sub:
                msg += f"\n\nSubscribe: {sub}"
            return msg


        if isinstance(action, ActionWallets):
            lines = ["Allowed wallets:"] + [f"- {w.alias} (wallet_name={w.wallet_name})" for w in self.cfg.btcli.wallets.values()]
            lines.append(f"Default wallet: {self.cfg.btcli.default_wallet}")
            return "\n".join(lines)

        if isinstance(action, ActionMode):
            self.store.set_session("mode", action.mode)
            return f"Mode set to: {action.mode.upper()} (config default is {self.cfg.app.mode.upper()})."

        if isinstance(action, ActionDoctor):
            return await self._handle_doctor()

        if isinstance(action, ActionCancel):
            return "Canceled (no pending action executed).\nIf you have a pending token, just let it expire."

        if isinstance(action, ActionConfirm):
            return await self._handle_confirm(sender, action.token)

        if isinstance(action, ActionValidatorsSources):
            return "Validator sources (priority order):\n" + "\n".join(self.validators.sources_summary())

        if isinstance(action, ActionValidatorsRefresh):
            cnt, meta = self.validators.refresh(force=True)
            lines = [f"✅ Refreshed validator registry: {cnt} entries"]
            srcs = meta.get("sources", [])
            if isinstance(srcs, list) and srcs:
                lines.append("Sources:")
                for s in srcs:
                    if isinstance(s, dict):
                        lines.append(f"- {s.get('type')}: {s.get('count')}")
            errs = meta.get("errors", [])
            if isinstance(errs, list) and errs:
                lines.append("Errors:")
                for e in errs:
                    if isinstance(e, dict):
                        lines.append(f"- {e.get('type')}: {e.get('error')}")
            return "\n".join(lines)

        if isinstance(action, ActionValidatorsSearch):
            hits = self.validators.search(action.term, limit=10)
            if not hits:
                return "No matches. Try a different term or paste the hotkey SS58."
            lines = [f"Top matches for '{action.term}':"]
            for h in hits:
                lines.append(f"- {h.name} -> {h.hotkey} ({h.source})")
            return "\n".join(lines)

        if isinstance(action, ActionShowDefaults):
            return self._format_defaults()

        if isinstance(action, (ActionSetDefaultValidator, ActionSetNetuidValidator, ActionSetWalletDefaultValidator, ActionSetWalletNetuidValidator, ActionSetWalletDefaultNetuid)):
            return self._handle_set(action)

        if isinstance(action, ActionInventory):
            return await self._handle_inventory(action.wallet)

        if isinstance(action, ActionBalance):
            return await self._handle_balance(action.wallet)

        if isinstance(action, (ActionStake, ActionUnstake)):
            return await self._handle_trade(sender, action)

        return "Unhandled action."

    def _handle_whoami(self, sender: Sender) -> str:
        # Show the exact identifier the operator should allow-list.
        allowed = is_allowed(self.cfg, sender)
        status = "✅ Authorized" if allowed else "❌ Not authorized"
        lines = [
            "EasyApe 🦍",
            f"Platform: {sender.platform}",
            f"Your ID: {sender.sender_id}",
            f"Chat type: {'group' if sender.chat_is_group else 'dm'}",
            status,
            "",
            "Operator onboarding:",
            "Add this identifier to config.yaml under:",
            "- auth.allow.telegram_user_ids (Telegram)",
            "- auth.allow.discord_user_ids (Discord)",
        ]
        # Licensing trial info (useful during setup)
        lines.append("")
        lines.append(self.licensing.trial_status_line())
        links = self.licensing.links()
        if links.get('billing_url'):
            lines.append(f"Subscribe: {links['billing_url']}")
        if links.get('manage_url'):
            lines.append(f"Manage:   {links['manage_url']}")
        return "\n".join(lines)

def _help_text(self, sender: Sender) -> str:
    links = self.licensing.links()
    license_line = self.licensing.trial_status_line()
    mode = self._effective_mode()
    wallet_default = self.cfg.btcli.default_wallet or "(none)"

    confirm_on = bool(self.cfg.app.require_confirmation)
    lines = [
        "EasyApe 🦍 — text to stake",
        "",
        "Core commands:",
        "- help",
        "- whoami                  # onboarding ID + status",
        "- billing                 # subscribe/manage links",
        "- privacy                 # what data is collected (minimal)",
        "- doctor                  # preflight checks",
        "- inventory [wallet]",
        "- balance [wallet]",
        "- stake <netuid> <tao> [validator] [wallet]",
        "- unstake <netuid> <alpha> [validator] [wallet]",
        "- mode dry|live",
        "- dryrun on|off",
        "",
        f"Mode: {mode.upper()}",
        f"Default wallet: {wallet_default}",
        "",
        "Licensing:",
        f"- {license_line}",
    ]
    if links.get("billing_url"):
        lines.append(f"- Subscribe: {links['billing_url']}")
    if links.get("manage_url"):
        lines.append(f"- Manage:   {links['manage_url']}")
    lines += [
        "",
        "Safety:",
        f"- Confirmations: {'ON' if confirm_on else 'OFF'} (app.require_confirmation)",
    ]
    if confirm_on:
        lines.append(
            f"- Confirm thresholds (LIVE): stake ≥ {self.cfg.app.confirm_over_tao:g} TAO, "
            f"unstake ≥ {self.cfg.app.confirm_over_alpha:g} Alpha"
        )
    lines.append(f"- Rate limits (stake/unstake): {self.cfg.app.rate_limit_per_minute}/min, {self.cfg.app.rate_limit_per_hour}/hr")
    lines.append("- Transfers are NEVER supported (stake/unstake only).")
    return "\n".join(lines)

async def _handle_billing(self, sender: Sender) -> str:
    try:
        await self.licensing.refresh_status()
    except Exception:
        pass
    links = self.licensing.links()
    license_line = self.licensing.trial_status_line()
    lines = ["EasyApe 🦍 — billing", "", license_line]
    if links.get("billing_url"):
        lines.append(f"Subscribe: {links['billing_url']}")
    else:
        lines.append("Subscribe: (not available — license server unreachable)")
    if links.get("manage_url"):
        lines.append(f"Manage:   {links['manage_url']}")
    return "\n".join(lines)

def _handle_privacy(self) -> str:
    links = self.licensing.links()
    lines = [
        "EasyApe 🦍 — privacy (minimal data)",
        "",
        "EasyApe is self-hosted and does NOT (and cannot) collect usage analytics about what you do.",
        "We do NOT receive: wallet names, wallet addresses, amounts, validator choices, message contents, or transaction history.",
        "",
        "What IS sent to the license server (for trial/subscription gating only):",
        "- install_id (random UUID generated once per install)",
        "- fingerprint (one-way SHA256 hash; not raw hardware IDs)",
        "- app + version",
        "- timestamp",
        "",
        "Payments are handled by Stripe. EasyApe does not store card data.",
    ]
    if links.get("billing_url"):
        lines.append("")
        lines.append(f"Subscribe: {links['billing_url']}")
    return "\n".join(lines)

async def _handle_doctor(self) -> str:
    import os
    from pathlib import Path

    out = ["EasyApe 🦍 — doctor (preflight)", ""]

    # btcli exists + responds
    btcli = (self.cfg.btcli.path or "").strip()
    if btcli.startswith("env:"):
        btcli = os.getenv(btcli.split("env:", 1)[1], "").strip()

    ok_btcli = False
    if btcli and Path(btcli).exists():
        try:
            res = await run_btcli([btcli, "--help"], timeout_sec=6)
            ok_btcli = (res.returncode == 0)
        except Exception:
            ok_btcli = False
    out.append(f"BTCLI: {'✅' if ok_btcli else '❌'} ({btcli or 'not set'})")

    wallets_dir = (getattr(self.cfg.btcli, "wallets_path", "") or "").strip()
    out.append(f"Wallets dir: {'✅' if wallets_dir and Path(wallets_dir).exists() else '❌'} ({wallets_dir or 'not set'})")

    meta = self.validators.last_refresh_meta() or {}
    if meta:
        src = meta.get("source") or meta.get("sources") or "unknown"
        out.append(f"Validator registry: ✅ ({src})")
    else:
        out.append("Validator registry: ⚠️ (not refreshed yet)")

    try:
        await self.licensing.refresh_status()
        out.append(f"Licensing: ✅ ({self.licensing.trial_status_line()})")
    except Exception as e:
        out.append(f"Licensing: ⚠️ (unreachable: {e})")

    links = self.licensing.links()
    if links.get("billing_url"):
        out.append(f"Subscribe: {links['billing_url']}")
    if links.get("manage_url"):
        out.append(f"Manage:   {links['manage_url']}")

    out.append("")
    out.append("Security tip: run as non-root, and chmod 600 your config/.env files.")
    return "\n".join(out)

    async def _handle_inventory(self, wallet_raw: Optional[str]) -> str:
        try:
            wallet = self._resolve_wallet(wallet_raw)
        except Exception as e:
            return str(e)

        cmd = build_stake_list_cmd(self.cfg, wallet.wallet_name)
        res = await run_btcli(cmd, stdin_text=self._stdin_for(wallet))
        # Try to parse and summarize; fall back to raw output
        stake_j = try_parse_json(res.stdout) or try_parse_json(res.stderr)
        if res.returncode != 0 or stake_j is None:
            return self._format_btcli_result(res)

        return self._format_inventory(wallet, stake_j)

    async def _handle_balance(self, wallet_raw: Optional[str]) -> str:
        try:
            wallet = self._resolve_wallet(wallet_raw)
        except Exception as e:
            return str(e)

        cmd = build_wallet_balance_cmd(self.cfg, wallet.wallet_name)
        res = await run_btcli(cmd, stdin_text=self._stdin_for(wallet))
        if res.returncode != 0:
            cmd2 = build_wallet_balance_cmd_alt(self.cfg, wallet.wallet_name)
            res = await run_btcli(cmd2, stdin_text=self._stdin_for(wallet))

        bal_j = try_parse_json(res.stdout) or try_parse_json(res.stderr)
        if res.returncode == 0 and bal_j is not None:
            free = extract_free_tao(bal_j)
            if free is not None:
                return (
                    "✅ EasyApe — Balance\n"
                    f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})\n"
                    f"Free TAO: {free:.6f}"
                )

        return self._format_btcli_result(res)

    def _format_inventory(self, wallet: BtcliWalletProfile, stake_j: Any) -> str:
        # Best-effort parse of common structures.
        # We search for numeric alpha amounts, grouped by netuid where possible.
        # If structure unknown, return truncated JSON.
        def _is_num(x):
            try:
                float(x)
                return True
            except Exception:
                return False

        netuid_map: Dict[str, List[Tuple[str, float]]] = {}

        # Common case: dict with "stakes" list, or nested in "data"
        candidates = []
        if isinstance(stake_j, dict):
            for key in ["stakes", "data", "result", "stake", "delegations", "items"]:
                v = stake_j.get(key)
                if isinstance(v, list):
                    candidates.append(v)
            # Sometimes dict itself is keyed by netuid
            for k, v in stake_j.items():
                if isinstance(v, list) and str(k).isdigit():
                    candidates.append(v)

        if not candidates and isinstance(stake_j, list):
            candidates.append(stake_j)

        def add_entry(netuid: Optional[str], hotkey: str, alpha: float):
            n = str(netuid) if netuid is not None else "?"
            netuid_map.setdefault(n, []).append((hotkey, alpha))

        for lst in candidates:
            for it in lst:
                if not isinstance(it, dict):
                    continue
                netuid = it.get("netuid") or it.get("subnet") or it.get("uid") or it.get("network") or it.get("net") 
                if netuid is not None and not str(netuid).isdigit():
                    # some schemas store netuid under 'netuid' but as string
                    try:
                        int(str(netuid))
                    except Exception:
                        netuid = None

                hotkey = (
                    str(it.get("hotkey") or it.get("delegate") or it.get("validator") or it.get("hotkey_ss58") or it.get("hotkey_ss58_address") or "").strip()
                )
                if not hotkey:
                    continue

                alpha_val = None
                for k in ["alpha", "amount", "stake", "stake_alpha", "staked", "delegated_alpha"]:
                    if k in it and _is_num(it[k]):
                        alpha_val = float(it[k])
                        break
                if alpha_val is None:
                    continue

                add_entry(str(netuid) if netuid is not None else None, hotkey, alpha_val)

        # If we got nothing, fall back to raw JSON
        if not netuid_map:
            js = str(stake_j)
            return "✅ EasyApe — Inventory\n" + f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})\n\n" + _truncate(js)

        lines = ["✅ EasyApe — Inventory", f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})", ""]
        meta = self.validators.last_refresh_meta() or {}
        if meta.get("ts"):
            try:
                when = dt.datetime.fromtimestamp(float(meta["ts"]), tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                lines.append(f"Validator registry last refreshed: {when}")
                lines.append("")
            except Exception:
                pass
        for netuid in sorted(netuid_map.keys(), key=lambda x: (x != "?", int(x) if x.isdigit() else 999999)):
            entries = netuid_map[netuid]
            total = sum(a for _, a in entries)
            lines.append(f"netuid {netuid}: total_alpha={total:.6f}")
            # show top 10 by amount
            for hk, amt in sorted(entries, key=lambda t: t[1], reverse=True)[:10]:
                nm = self.validators.name_for_hotkey(hk) or ''
                label = f"{nm} ({hk})" if nm else hk
                lines.append(f"  - {label}: {amt:.6f}")
            lines.append("")
        return "\n".join(lines).rstrip()

    # -------------------------
    # Defaults & routing display
    # -------------------------
    def _format_defaults(self) -> str:
        routing = self._get_routing()
        lines = ["Defaults (config + runtime overrides):"]
        lines.append(f"- config defaults.validator_all: {self.cfg.defaults.validator_all or '(unset)'}")
        if self.cfg.defaults.validator_by_netuid:
            lines.append("- config defaults.validator_by_netuid:")
            for k in sorted(self.cfg.defaults.validator_by_netuid.keys()):
                lines.append(f"  - {k}: {self.cfg.defaults.validator_by_netuid[k]}")
        else:
            lines.append("- config defaults.validator_by_netuid: (empty)")

        lines.append("")
        lines.append(f"- runtime validator_all: {routing.get('validator_all', '(unset)')}")
        gbn = routing.get("validator_by_netuid", {})
        if isinstance(gbn, dict) and gbn:
            lines.append("- runtime validator_by_netuid:")
            for k, v in gbn.items():
                lines.append(f"  - {k}: {v}")
        else:
            lines.append("- runtime validator_by_netuid: (empty)")

        lines.append("")
        lines.append("Wallet profiles:")
        for w in self.cfg.btcli.wallets.values():
            wovr = self._routing_wallet_overrides(w.alias)
            lines.append(f"- {w.alias}: wallet_name={w.wallet_name}")
            lines.append(f"  - config default_netuid: {w.default_netuid}")
            lines.append(f"  - runtime default_netuid: {wovr.get('default_netuid', '(unset)')}")
            lines.append(f"  - config validator_all: {w.validator_all or '(unset)'}")
            lines.append(f"  - runtime validator_all: {wovr.get('validator_all', '(unset)')}")
            if w.validator_by_netuid:
                lines.append("  - config validator_by_netuid:")
                for k in sorted(w.validator_by_netuid.keys()):
                    lines.append(f"    - {k}: {w.validator_by_netuid[k]}")
            else:
                lines.append("  - config validator_by_netuid: (empty)")
            wbn = wovr.get("validator_by_netuid", {})
            if isinstance(wbn, dict) and wbn:
                lines.append("  - runtime validator_by_netuid:")
                for k, v in wbn.items():
                    lines.append(f"    - {k}: {v}")
            else:
                lines.append("  - runtime validator_by_netuid: (empty)")
        return "\n".join(lines)

    def _handle_set(self, action: Action) -> str:
        with self.store.with_lock():
            routing = self._get_routing()
            routing.setdefault("validator_by_netuid", {})
            routing.setdefault("wallets", {})

            if isinstance(action, ActionSetDefaultValidator):
                routing["validator_all"] = action.value.strip()
                self._set_routing(routing)
                return f"✅ Set runtime default validator_all = {action.value.strip()}"

            if isinstance(action, ActionSetNetuidValidator):
                routing["validator_by_netuid"][str(action.netuid)] = action.value.strip()
                self._set_routing(routing)
                return f"✅ Set runtime netuid {action.netuid} validator = {action.value.strip()}"

            if isinstance(action, ActionSetWalletDefaultValidator):
                wal = action.wallet
                routing["wallets"].setdefault(wal, {})
                routing["wallets"][wal]["validator_all"] = action.value.strip()
                self._set_routing(routing)
                return f"✅ Set runtime wallet {wal} validator_all = {action.value.strip()}"

            if isinstance(action, ActionSetWalletNetuidValidator):
                wal = action.wallet
                routing["wallets"].setdefault(wal, {})
                routing["wallets"][wal].setdefault("validator_by_netuid", {})
                routing["wallets"][wal]["validator_by_netuid"][str(action.netuid)] = action.value.strip()
                self._set_routing(routing)
                return f"✅ Set runtime wallet {wal} netuid {action.netuid} validator = {action.value.strip()}"

            if isinstance(action, ActionSetWalletDefaultNetuid):
                wal = action.wallet
                routing["wallets"].setdefault(wal, {})
                routing["wallets"][wal]["default_netuid"] = int(action.netuid)
                self._set_routing(routing)
                return f"✅ Set runtime wallet {wal} default_netuid = {action.netuid}"

        return "Unknown set action."

    # -------------------------
    # Stake / unstake
    # -------------------------
async def _handle_trade(self, sender: Sender, action: Action) -> str:
    # Licensing gate (trial -> ok; otherwise require valid license)
    decision = await self.licensing.can_trade()
    if not decision.allowed:
        return decision.reason

    # Rate limiting (stake/unstake only)
    rl = self._rate_limit_ok(sender)
    if rl:
        return rl

    try:
        wallet = self._resolve_wallet(getattr(action, "wallet", None))
    except Exception as e:
        return str(e)

    netuid = getattr(action, "netuid", None)
    if netuid is None:
        netuid = self._get_default_netuid(wallet)
        if netuid is None:
            return "Turbo stake/unstake requires wallet.default_netuid. Set it in config.yaml or: set wallet <wallet> default netuid <n>"

    try:
        validator = self._resolve_validator(getattr(action, "validator", None), wallet, int(netuid))
    except Exception as e:
        return str(e)

    mode = self._effective_mode()
    day = _day_key(self.cfg.app.timezone)
    skey = _sender_key(sender)

    # Build command + enforce per-tx and daily caps
    if isinstance(action, ActionStake):
        tao_amt = float(action.tao_amount)
        if tao_amt > float(self.cfg.app.max_tao_per_tx):
            return f"Amount exceeds max_tao_per_tx ({self.cfg.app.max_tao_per_tx})."
        used = self.store.get_daily(day, skey, "stake_tao")
        if used + tao_amt > float(self.cfg.app.daily_max_tao):
            return f"Daily TAO cap exceeded. Used today: {used:.4f} / {self.cfg.app.daily_max_tao:.4f}"
        cmd = build_stake_add_cmd(self.cfg, wallet.wallet_name, int(netuid), tao_amt, validator.hotkey)
        summary_units = f"stake {tao_amt} TAO"
    else:
        alpha_amt = float(action.alpha_amount)
        if alpha_amt > float(self.cfg.app.max_alpha_per_tx):
            return f"Amount exceeds max_alpha_per_tx ({self.cfg.app.max_alpha_per_tx})."
        used = self.store.get_daily(day, skey, "unstake_alpha")
        if used + alpha_amt > float(self.cfg.app.daily_max_alpha):
            return f"Daily Alpha cap exceeded. Used today: {used:.4f} / {self.cfg.app.daily_max_alpha:.4f}"
        cmd = build_stake_remove_cmd(self.cfg, wallet.wallet_name, int(netuid), alpha_amt, validator.hotkey)
        summary_units = f"unstake {alpha_amt} Alpha"

    # DRY mode: never executes btcli stake add/remove
    if mode == "dry":
        return (
            "DRY-RUN\n"
            f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})\n"
            f"Validator: {validator.name} -> {validator.hotkey}\n"
            f"Subnet: netuid={netuid}\n"
            f"Action: {summary_units}\n\n"
            "Would run:\n" + " ".join(cmd)
        )

    # Confirmations (only if enabled). If enabled, confirmation is required only above thresholds.
    if self.cfg.app.require_confirmation:
        need = False
        if isinstance(action, ActionStake):
            need = float(action.tao_amount) >= float(self.cfg.app.confirm_over_tao)
        else:
            need = float(action.alpha_amount) >= float(self.cfg.app.confirm_over_alpha)

        if need:
            token = self._new_token()
            now = time.time()
            expires = now + (self.cfg.app.confirmation_expires_minutes * 60)

            pending = PendingAction(
                created_ts=now,
                expires_ts=expires,
                action={
                    "type": action.__class__.__name__,
                    **asdict(action),
                    "netuid": int(netuid),
                    "_wallet_alias": wallet.alias,
                    "_wallet_name": wallet.wallet_name,
                    "_validator_name": validator.name,
                    "_validator_hotkey": validator.hotkey,
                },
                platform=sender.platform,
                sender_id=sender.sender_id,
            )

            with self.store.with_lock():
                self.store.set_pending(token, pending)

            return (
                "LIVE mode: pending confirmation.\n"
                f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})\n"
                f"Validator: {validator.name} -> {validator.hotkey}\n"
                f"Subnet: netuid={netuid}\n"
                f"Action: {summary_units}\n\n"
                f"Confirm within {self.cfg.app.confirmation_expires_minutes} min: confirm {token}\n"
                f"(Will run: {' '.join(cmd)})"
            )

    return await self._execute_and_report(sender, wallet, validator, action, int(netuid))

    async def _handle_confirm(self, sender: Sender, token: str) -> str:
        with self.store.with_lock():
            pending = self.store.get_pending(token)
            if not pending:
                return "No pending action for that token."
            if pending.platform != sender.platform or pending.sender_id != sender.sender_id:
                return "Token does not belong to you."
            if time.time() > pending.expires_ts:
                self.store.del_pending(token)
                return "Token expired."
            self.store.del_pending(token)

        typ = pending.action.get("type")
        wallet_alias = str(pending.action.get("_wallet_alias", ""))
        wallet = self.cfg.btcli.wallets.get(wallet_alias, None)
        if wallet is None:
            wname = str(pending.action.get("_wallet_name", ""))
            for w in self.cfg.btcli.wallets.values():
                if w.wallet_name == wname:
                    wallet = w
                    break
        if wallet is None:
            return "Wallet for this token is no longer configured."

        netuid = int(pending.action.get("netuid"))

        validator = ValidatorEntry(
            name=str(pending.action.get("_validator_name", "")) or "validator",
            hotkey=str(pending.action.get("_validator_hotkey", "")),
            source="pending",
        )

        if typ == "ActionStake":
            action = ActionStake(
                netuid=netuid,
                tao_amount=float(pending.action["tao_amount"]),
                validator=str(pending.action.get("validator") or ""),
                wallet=str(pending.action.get("wallet") or ""),
            )
        elif typ == "ActionUnstake":
            action = ActionUnstake(
                netuid=netuid,
                alpha_amount=float(pending.action["alpha_amount"]),
                validator=str(pending.action.get("validator") or ""),
                wallet=str(pending.action.get("wallet") or ""),
            )
        else:
            return "Unknown pending action type."

        return await self._execute_and_report(sender, wallet, validator, action, netuid)

    async def _execute_and_report(self, sender: Sender, wallet: BtcliWalletProfile, validator: ValidatorEntry, action: Action, netuid: int) -> str:
        pre_free, pre_alpha = await self._snapshot(wallet, netuid, validator.hotkey)

        if isinstance(action, ActionStake):
            cmd = build_stake_add_cmd(self.cfg, wallet.wallet_name, netuid, action.tao_amount, validator.hotkey)
        else:
            cmd = build_stake_remove_cmd(self.cfg, wallet.wallet_name, netuid, action.alpha_amount, validator.hotkey)

        res = await run_btcli(cmd, stdin_text=self._stdin_for(wallet))
        post_free, post_alpha = await self._snapshot(wallet, netuid, validator.hotkey) if res.returncode == 0 else (None, None)

        day = _day_key(self.cfg.app.timezone)
        skey = _sender_key(sender)
        if res.returncode == 0:
            with self.store.with_lock():
                if isinstance(action, ActionStake):
                    self.store.add_daily(day, skey, "stake_tao", float(action.tao_amount))
                else:
                    self.store.add_daily(day, skey, "unstake_alpha", float(action.alpha_amount))

        lines = []
        lines.append("✅ EasyApe — Text to stake")
        lines.append(f"Wallet: {wallet.alias} (wallet_name={wallet.wallet_name})")
        lines.append(f"Validator: {validator.name} -> {validator.hotkey}")
        lines.append(f"Subnet: netuid={netuid}")
        lines.append(f"Exit: {res.returncode}")
        lines.append("")

        if res.returncode == 0:
            if isinstance(action, ActionStake):
                tao_in = float(action.tao_amount)
                tao_spent = (pre_free - post_free) if (pre_free is not None and post_free is not None) else None
                alpha_got = (post_alpha - pre_alpha) if (pre_alpha is not None and post_alpha is not None) else None

                lines.append("🦍✅ Stake complete")
                lines.append(f"Requested: {tao_in:.6f} TAO")
                if tao_spent is not None:
                    lines.append(f"TAO delta (free): {-tao_spent:+.6f} (spent ~{tao_spent:.6f} incl fees)")
                if alpha_got is not None:
                    lines.append(f"Alpha received (delta): {alpha_got:+.6f}")
                    if tao_spent is not None and alpha_got != 0:
                        lines.append(f"Effective price: {(tao_spent/alpha_got):.6f} TAO/Alpha")

            else:
                alpha_out = float(action.alpha_amount)
                tao_received = (post_free - pre_free) if (pre_free is not None and post_free is not None) else None
                alpha_sold = (pre_alpha - post_alpha) if (pre_alpha is not None and post_alpha is not None) else None

                lines.append("🦍✅ Unstake complete")
                lines.append(f"Requested: {alpha_out:.6f} Alpha")
                if alpha_sold is not None:
                    lines.append(f"Alpha delta: {-alpha_sold:+.6f} (sold ~{alpha_sold:.6f} incl fees)")
                if tao_received is not None:
                    lines.append(f"TAO received (free delta): {tao_received:+.6f}")
                    if alpha_sold is not None and alpha_sold != 0:
                        lines.append(f"Effective price: {(tao_received/alpha_sold):.6f} TAO/Alpha")

            lines.append("")
            if res.stdout.strip():
                lines.append("STDOUT (truncated):\n" + _truncate(res.stdout))
            if res.stderr.strip():
                lines.append("STDERR (truncated):\n" + _truncate(res.stderr))
        else:
            lines.append("❌ Transaction failed")
            lines.append("Ran:\n" + " ".join(res.cmd))
            if res.stdout.strip():
                lines.append("STDOUT:\n" + _truncate(res.stdout))
            if res.stderr.strip():
                lines.append("STDERR:\n" + _truncate(res.stderr))

        return "\n".join(lines)

    def _format_btcli_result(self, res: BtcliResult) -> str:
        out = res.stdout.strip()
        err = res.stderr.strip()
        msg = [f"Ran: {' '.join(res.cmd)}", f"Exit: {res.returncode}"]
        if out:
            msg.append("\nSTDOUT:\n" + _truncate(out))
        if err:
            msg.append("\nSTDERR:\n" + _truncate(err))
        return "\n".join(msg)
