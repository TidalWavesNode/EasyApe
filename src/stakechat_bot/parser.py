from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union
import re


@dataclass(frozen=True)
class ActionHelp:
    pass


@dataclass(frozen=True)
class ActionWhoAmI:
    pass


@dataclass(frozen=True)
class ActionMode:
    mode: str


@dataclass(frozen=True)
class ActionCancel:
    pass


@dataclass(frozen=True)
class ActionConfirm:
    token: str


@dataclass(frozen=True)
class ActionWallets:
    pass


@dataclass(frozen=True)
class ActionValidatorsRefresh:
    pass


@dataclass(frozen=True)
class ActionValidatorsSources:
    pass


@dataclass(frozen=True)
class ActionValidatorsSearch:
    term: str


@dataclass(frozen=True)
class ActionShowDefaults:
    pass


@dataclass(frozen=True)
class ActionSetDefaultValidator:
    value: str


@dataclass(frozen=True)
class ActionSetNetuidValidator:
    netuid: int
    value: str


@dataclass(frozen=True)
class ActionSetWalletDefaultValidator:
    wallet: str
    value: str


@dataclass(frozen=True)
class ActionSetWalletNetuidValidator:
    wallet: str
    netuid: int
    value: str


@dataclass(frozen=True)
class ActionSetWalletDefaultNetuid:
    wallet: str
    netuid: int


@dataclass(frozen=True)
class ActionInventory:
    wallet: Optional[str] = None


@dataclass(frozen=True)
class ActionBalance:
    wallet: Optional[str] = None

@dataclass(frozen=True)
class ActionBilling(Action):
    pass


@dataclass(frozen=True)
class ActionPrivacy(Action):
    pass


@dataclass(frozen=True)
class ActionDoctor(Action):
    pass


@dataclass(frozen=True)
class ActionStake:
    netuid: Optional[int]
    tao_amount: float
    validator: Optional[str] = None
    wallet: Optional[str] = None


@dataclass(frozen=True)
class ActionUnstake:
    netuid: Optional[int]
    alpha_amount: float
    validator: Optional[str] = None
    wallet: Optional[str] = None


Action = Union[
    ActionHelp,
    ActionWhoAmI,
    ActionMode,
    ActionCancel,
    ActionConfirm,
    ActionWallets,
    ActionValidatorsRefresh,
    ActionValidatorsSources,
    ActionValidatorsSearch,
    ActionShowDefaults,
    ActionSetDefaultValidator,
    ActionSetNetuidValidator,
    ActionSetWalletDefaultValidator,
    ActionSetWalletNetuidValidator,
    ActionSetWalletDefaultNetuid,
    ActionInventory,
    ActionBalance,
    ActionStake,
    ActionUnstake,
]


def _split(text: str):
    return [t.strip('"') for t in re.findall(r'"[^"]+"|\S+', text.strip())]


def parse_action(text: str) -> Tuple[Optional[Action], Optional[str]]:
    raw = text.strip()
    if not raw:
        return None, "Empty message. Send 'help'."

    # Block transfer-like intents early (defense-in-depth; engine also blocks)
    if re.search(r"\b(transfer|send|withdraw|deposit|move)\b", raw, flags=re.I):
        return None, "Transfers are not supported. EasyApe only allows staking/unstaking plus balance/inventory."

    if raw.startswith("/"):
        raw = raw[1:]

    parts = _split(raw)
    if not parts:
        return None, "Empty message. Send 'help'."

    cmd = parts[0].lower()

    if cmd in ("help", "h", "?"):
        return ActionHelp(), None

    if cmd in ("whoami", "me", "id"):
        return ActionWhoAmI(), None

    if cmd == "mode":
        if len(parts) != 2:
            return None, "mode dry|live"
        mode = parts[1].lower()
        if mode not in ("dry", "live"):
            return None, "mode dry|live"
        return ActionMode(mode=mode), None

    if cmd in ("cancel", "stop"):
        return ActionCancel(), None

    if cmd == "confirm":
        if len(parts) != 2:
            return None, "confirm <token>"
        token = parts[1].strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{6}", token):
            return None, "confirm token must look like ABC123"
        return ActionConfirm(token=token), None

    if cmd in ("wallets", "wl"):
        return ActionWallets(), None

    # inventory + balance
    if cmd in ("inventory", "inv"):
        wallet = parts[1] if len(parts) >= 2 else None
        return ActionInventory(wallet=wallet), None

    if cmd in ("balance", "bal"):
        wallet = parts[1] if len(parts) >= 2 else None
        return ActionBalance(wallet=wallet), None

    # validators
    if cmd in ("validators", "vali", "v"):
        if len(parts) < 2:
            return None, "validators refresh|sources|search <term>"
        sub = parts[1].lower()
        if sub == "refresh":
            return ActionValidatorsRefresh(), None
        if sub == "sources":
            return ActionValidatorsSources(), None
        if sub == "search":
            if len(parts) < 3:
                return None, "validators search <term>"
            term = " ".join(parts[2:])
            return ActionValidatorsSearch(term=term), None
        return None, "validators refresh|sources|search <term>"

    if cmd == "show" and len(parts) >= 2 and parts[1].lower() == "defaults":
        return ActionShowDefaults(), None

    # set commands
    if cmd == "set":
        if len(parts) < 3:
            return None, "set default validator <v> | set netuid <n> validator <v> | set wallet <w> ..."
        if parts[1].lower() == "default" and len(parts) >= 4 and parts[2].lower() == "validator":
            return ActionSetDefaultValidator(value=" ".join(parts[3:])), None
        if parts[1].lower() == "netuid" and len(parts) >= 5 and parts[3].lower() == "validator":
            try:
                netuid = int(parts[2])
            except Exception:
                return None, "set netuid <netuid> validator <value>"
            return ActionSetNetuidValidator(netuid=netuid, value=" ".join(parts[4:])), None
        if parts[1].lower() == "wallet" and len(parts) >= 4:
            wallet = parts[2]
            if parts[3].lower() == "default" and len(parts) >= 6 and parts[4].lower() == "validator":
                return ActionSetWalletDefaultValidator(wallet=wallet, value=" ".join(parts[5:])), None
            if parts[3].lower() == "netuid" and len(parts) >= 7 and parts[5].lower() == "validator":
                try:
                    netuid = int(parts[4])
                except Exception:
                    return None, "set wallet <w> netuid <netuid> validator <value>"
                return ActionSetWalletNetuidValidator(wallet=wallet, netuid=netuid, value=" ".join(parts[6:])), None
            if parts[3].lower() == "default" and len(parts) >= 6 and parts[4].lower() == "netuid":
                try:
                    netuid = int(parts[5])
                except Exception:
                    return None, "set wallet <w> default netuid <netuid>"
                return ActionSetWalletDefaultNetuid(wallet=wallet, netuid=netuid), None
            return None, "set wallet <w> default validator <v> | set wallet <w> netuid <n> validator <v> | set wallet <w> default netuid <n>"
        return None, "Unknown set command."

    def _is_int(s: str) -> bool:
        try:
            int(s)
            return True
        except Exception:
            return False

    def _is_float(s: str) -> bool:
        try:
            float(s)
            return True
        except Exception:
            return False

    def parse_trade(kind: str):
        if len(parts) < 2:
            return None, f"{kind} [wallet] <netuid> <amount> [validator]"

        wallet = None
        idx = 1

        # wallet + turbo amount: stake <wallet> <amount> [validator]
        if len(parts) >= 3 and not _is_int(parts[1]) and _is_float(parts[2]) and ("." in parts[2]):
            wallet = parts[1]
            netuid = None
            amount = float(parts[2])
            validator = parts[3] if len(parts) >= 4 else None
            return (wallet, netuid, amount, validator), None

        # turbo without wallet: stake <amount> [validator] (amount must include decimal)
        if wallet is None and len(parts) in (2, 3) and _is_float(parts[1]) and ("." in parts[1]):
            netuid = None
            amount = float(parts[1])
            validator = parts[2] if len(parts) == 3 else None
            return (None, netuid, amount, validator), None

        # wallet standard: stake <wallet> <netuid> <amount> [validator]
        if len(parts) >= 4 and not _is_int(parts[1]) and _is_int(parts[2]) and _is_float(parts[3]):
            wallet = parts[1]
            idx = 2

        if len(parts) < idx + 2:
            return None, f"{kind} [wallet] <netuid> <amount> [validator]"

        try:
            netuid = int(parts[idx])
        except Exception:
            return None, f"{kind}: netuid must be an int"

        try:
            amount = float(parts[idx + 1])
        except Exception:
            return None, f"{kind}: amount must be a number"

        validator = parts[idx + 2] if len(parts) >= idx + 3 else None

        if amount <= 0:
            return None, f"{kind}: amount must be > 0"

        return (wallet, netuid, amount, validator), None

    if cmd in ("stake", "add"):
        parsed, err = parse_trade("stake")
        if err:
            return None, err
        wallet, netuid, tao_amount, validator = parsed
        return ActionStake(netuid=netuid, tao_amount=tao_amount, validator=validator, wallet=wallet), None

    if cmd in ("unstake", "remove"):
        parsed, err = parse_trade("unstake")
        if err:
            return None, err
        wallet, netuid, alpha_amount, validator = parsed
        return ActionUnstake(netuid=netuid, alpha_amount=alpha_amount, validator=validator, wallet=wallet), None

    return None, "Unknown command. Send 'help'."
