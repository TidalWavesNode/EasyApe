from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import json
import re

from .config import RootConfig
from .utils.fmt import fmt_amount


@dataclass(frozen=True)
class BtcliResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str


def _stake_defaults_args(cfg: RootConfig) -> List[str]:
    args: List[str] = []
    if cfg.btcli.staking.safe:
        args += ["--safe", "--tolerance", str(cfg.btcli.staking.tolerance)]
        if cfg.btcli.staking.no_partial:
            args += ["--no-partial"]
    return args


def build_stake_add_cmd(cfg: RootConfig, wallet_name: str, netuid: int, tao_amount: float, validator_hotkey: str) -> List[str]:
    # stake add: amount is in TAO
    return [
        cfg.btcli.path,
        "stake", "add",
        "--wallet.name", wallet_name,
        "--netuid", str(netuid),
        "--amount", fmt_amount(tao_amount),
        "--include-hotkeys", validator_hotkey,
        "--no_prompt",
        "--json-out",
    ] + _stake_defaults_args(cfg) + list(cfg.btcli.common_args)


def build_stake_remove_cmd(cfg: RootConfig, wallet_name: str, netuid: int, alpha_amount: float, validator_hotkey: str) -> List[str]:
    # stake remove: amount is in Alpha
    return [
        cfg.btcli.path,
        "stake", "remove",
        "--wallet.name", wallet_name,
        "--netuid", str(netuid),
        "--amount", fmt_amount(alpha_amount),
        "--include-hotkeys", validator_hotkey,
        "--no_prompt",
        "--json-out",
    ] + _stake_defaults_args(cfg) + list(cfg.btcli.common_args)


def build_stake_list_cmd(cfg: RootConfig, wallet_name: str) -> List[str]:
    return [
        cfg.btcli.path,
        "stake", "list",
        "--wallet.name", wallet_name,
        "--no_prompt",
        "--json-out",
    ] + list(cfg.btcli.common_args)


def build_wallet_balance_cmd(cfg: RootConfig, wallet_name: str) -> List[str]:
    # Prefer short alias `w balance` (common), but engine will fallback to `wallet balance` if needed.
    return [
        cfg.btcli.path,
        "w", "balance",
        "--wallet.name", wallet_name,
        "--no_prompt",
        "--json-out",
    ] + list(cfg.btcli.common_args)


def build_wallet_balance_cmd_alt(cfg: RootConfig, wallet_name: str) -> List[str]:
    return [
        cfg.btcli.path,
        "wallet", "balance",
        "--wallet.name", wallet_name,
        "--no_prompt",
        "--json-out",
    ] + list(cfg.btcli.common_args)



async def run_btcli(cmd: List[str], timeout_sec: int = 180, stdin_text: Optional[str] = None) -> BtcliResult:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if stdin_text is not None:
            proc.stdin.write(stdin_text.encode("utf-8", errors="ignore"))
            await proc.stdin.drain()
            try:
                proc.stdin.close()
            except Exception:
                pass

        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        return BtcliResult(cmd=cmd, returncode=124, stdout="", stderr="Timed out")

    return BtcliResult(
        cmd=cmd,
        returncode=int(proc.returncode or 0),
        stdout=(stdout_b or b"").decode("utf-8", errors="replace"),
        stderr=(stderr_b or b"").decode("utf-8", errors="replace"),
    )


def try_parse_json(text: str) -> Optional[Any]:
    """Best-effort parse of btcli --json-out output even if logs precede it."""
    if not text:
        return None
    # Find first JSON object/array start
    m = re.search(r"[\[{]", text)
    if not m:
        return None
    start = m.start()
    candidate = text[start:].strip()
    try:
        return json.loads(candidate)
    except Exception:
        # sometimes btcli prints multiple lines, with JSON at the end
        # try last JSON block
        tail = candidate
        # crude: find last '{' or '['
        last = max(tail.rfind('{'), tail.rfind('['))
        if last >= 0:
            try:
                return json.loads(tail[last:].strip())
            except Exception:
                return None
        return None


def extract_inventory(stake_json: Any) -> List[Tuple[int, str, float]]:
    """Extract a list of (netuid, validator_hotkey, alpha_amount) from stake list JSON.

    Best-effort parser: btcli JSON structure can vary by version.
    """
    out: Dict[Tuple[int, str], float] = {}

    def scan(obj: Any):
        if isinstance(obj, dict):
            n = obj.get("netuid", None)
            hk = (
                obj.get("hotkey")
                or obj.get("delegate")
                or obj.get("hotkey_ss58")
                or obj.get("hotkey_ss58_address")
                or obj.get("delegate_ss58")
                or obj.get("ss58")
            )

            alpha_val: Optional[float] = None
            if n is not None and hk is not None:
                try:
                    netuid = int(n)
                    hotkey = str(hk).strip()
                    # pick alpha-like numeric fields
                    for k, v in obj.items():
                        lk = str(k).lower()
                        if isinstance(v, (int, float)) and ("alpha" in lk or lk in ("stake", "staked", "alpha_stake")):
                            alpha_val = float(v)
                            break
                        if isinstance(v, str) and ("alpha" in lk or lk in ("stake", "staked", "alpha_stake")):
                            try:
                                alpha_val = float(v)
                                break
                            except Exception:
                                pass

                    if alpha_val is not None and hotkey:
                        key = (netuid, hotkey)
                        if key not in out or alpha_val > out[key]:
                            out[key] = alpha_val
                except Exception:
                    pass

            for v in obj.values():
                scan(v)

        elif isinstance(obj, list):
            for it in obj:
                scan(it)

    scan(stake_json)
    items = [(k[0], k[1], v) for k, v in out.items()]
    items.sort(key=lambda x: (x[0], x[1]))
    return items


def extract_free_tao(balance_json: Any) -> Optional[float]:
    """Extract free TAO from `btcli w balance --json-out` output (best-effort)."""
    # common patterns: {"coldkey":{"free":...}} or {"free":...}
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if isinstance(v, (int, float)) and ("free" in lk) and ("tao" in lk or "balance" in lk or "cold" in lk):
                    yield float(v)
                # sometimes: {"free": {"tao": 12.3}}
                if lk == "free" and isinstance(v, dict):
                    for kk, vv in v.items():
                        if isinstance(vv, (int, float)) and str(kk).lower() in ("tao", "balance", "free", "value"):
                            yield float(vv)
                yield from walk(v)
        elif isinstance(obj, list):
            for it in obj:
                yield from walk(it)

    vals = list(walk(balance_json))
    if not vals:
        # fallback: any 'free' numeric
        def walk2(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lk = str(k).lower()
                    if isinstance(v, (int, float)) and lk == "free":
                        yield float(v)
                    yield from walk2(v)
            elif isinstance(obj, list):
                for it in obj:
                    yield from walk2(it)
        vals = list(walk2(balance_json))

    if not vals:
        return None
    # choose the largest free-like value (usually total free tao)
    return max(vals)


def extract_alpha_for(stake_json: Any, netuid: int, validator_hotkey: str) -> Optional[float]:
    """Extract alpha stake for a specific (netuid, validator_hotkey) from stake list JSON."""
    target = validator_hotkey.strip()

    best: Optional[float] = None

    def scan(obj):
        nonlocal best
        if isinstance(obj, dict):
            # Look for records that mention netuid and the target hotkey/delegate.
            n = obj.get("netuid", None)
            hk = (
                obj.get("hotkey")
                or obj.get("delegate")
                or obj.get("hotkey_ss58")
                or obj.get("hotkey_ss58_address")
                or obj.get("delegate_ss58")
                or obj.get("ss58")
            )
            if n is not None and hk is not None:
                try:
                    if int(n) == int(netuid) and str(hk).strip() == target:
                        # pick alpha-like numeric
                        for k, v in obj.items():
                            lk = str(k).lower()
                            if isinstance(v, (int, float)) and ("alpha" in lk or lk in ("stake", "staked")):
                                val = float(v)
                                if best is None or val > best:
                                    best = val
                except Exception:
                    pass

            for v in obj.values():
                scan(v)

        elif isinstance(obj, list):
            for it in obj:
                scan(it)

    scan(stake_json)

    if best is not None:
        return best

    # fallback: the stake JSON might be keyed by hotkey, then netuid entries
    def scan2(obj):
        nonlocal best
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).strip() == target:
                    # within this branch, look for netuid match and alpha
                    scan(v)
                else:
                    scan2(v)
        elif isinstance(obj, list):
            for it in obj:
                scan2(it)

    scan2(stake_json)
    return best
