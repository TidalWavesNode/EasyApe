from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List, Optional, Union
import yaml

from .utils.secrets import resolve_env


def _deep_resolve_env(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve_env(v) for v in obj]
    if isinstance(obj, str):
        return resolve_env(obj)
    return obj


@dataclass(frozen=True)
class AppConfig:
    mode: str
    timezone: str
    data_dir: str
    log_file: str
    require_confirmation: bool
    confirmation_expires_minutes: int
    allow_groups: bool

    # Safety defaults
    confirm_over_tao: float
    confirm_over_alpha: float
    rate_limit_per_minute: int
    rate_limit_per_hour: int

    # Guardrails (stake is TAO; unstake is Alpha)
    max_tao_per_tx: float
    daily_max_tao: float
    max_alpha_per_tx: float
    daily_max_alpha: float


@dataclass(frozen=True)
class AuthAllow:
    telegram_user_ids: List[int]
    discord_user_ids: List[int]


@dataclass(frozen=True)
class BtcliWalletProfile:
    alias: str
    wallet_name: str
    password: str

    # Legacy fallback (kept for compatibility)
    default_validator: str

    # New: per-wallet defaults
    default_netuid: Optional[int]
    validator_all: str
    validator_by_netuid: Dict[int, str]


@dataclass(frozen=True)
class BtcliStakingDefaults:
    safe: bool
    tolerance: float
    no_partial: bool


@dataclass(frozen=True)
class BtcliConfig:
    path: str
    common_args: List[str]
    default_wallet: str
    wallets: Dict[str, BtcliWalletProfile]
    staking: BtcliStakingDefaults


@dataclass(frozen=True)
class ValidatorSourceTaostats:
    type: str  # "taostats"
    api_url: str
    api_key: str


@dataclass(frozen=True)
class ValidatorSourceHttpJson:
    type: str  # "http_json"
    url: str
    headers: Dict[str, str]
    data_path: str
    name_field: str
    hotkey_field: str


@dataclass(frozen=True)
class ValidatorSourceFileJson:
    type: str  # "file_json"
    path: str
    data_path: str
    name_field: str
    hotkey_field: str


ValidatorSource = Union[ValidatorSourceTaostats, ValidatorSourceHttpJson, ValidatorSourceFileJson]


@dataclass(frozen=True)
class ValidatorsConfig:
    cache_ttl_minutes: int
    delegates_fallback_url: str
    sources: List[ValidatorSource]


@dataclass(frozen=True)
class DefaultsConfig:
    validator_all: str
    validator_by_netuid: Dict[int, str]


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    token: str


@dataclass(frozen=True)
class DiscordConfig:
    enabled: bool
    token: str
    guild_ids: List[int]


@dataclass(frozen=True)
class ChannelsConfig:
    telegram: TelegramConfig
    discord: DiscordConfig



@dataclass(frozen=True)
class LicensingConfig:
    # Licensing is SERVER-tracked (server is the source of truth).
    # Customers should NOT need to configure anything for licensing.
    server_url: str
    grace_hours: int

    # Legacy (ignored; kept only so old configs don't break):
    verify_url: str
    license_key: str
    trial_days: int
    cache_ttl_hours: int

@dataclass(frozen=True)
class RootConfig:
    app: AppConfig
    allow: AuthAllow
    btcli: BtcliConfig
    validators: ValidatorsConfig
    defaults: DefaultsConfig
    channels: ChannelsConfig
    licensing: LicensingConfig


def _parse_int_keyed_map(d: Any) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        try:
            ik = int(k)
        except Exception:
            continue
        if v is None:
            continue
        out[ik] = str(v).strip()
    return out


def load_config(path: str) -> RootConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    raw = _deep_resolve_env(raw)

    app = raw.get("app", {}) or {}
    auth = (raw.get("auth", {}) or {}).get("allow", {}) or {}
    bt = raw.get("btcli", {}) or {}
    validators_raw = raw.get("validators", {}) or {}
    defaults_raw = raw.get("defaults", {}) or {}
    channels = raw.get("channels", {}) or {}
    licensing_raw = raw.get("licensing", {}) or {}

    # Licensing
    try:
        trial_days = int(licensing_raw.get("trial_days", 3))
    except Exception:
        trial_days = 3
    try:
        cache_ttl_hourss = int(licensing_raw.get("cache_ttl_hourss", 24))
    except Exception:
        cache_ttl_hourss = 24

    # Wallets
    wallets_raw: Dict[str, Any] = bt.get("wallets", {}) or {}
    wallets: Dict[str, BtcliWalletProfile] = {}
    for alias, w in wallets_raw.items():
        if not isinstance(w, dict):
            continue
        a = str(alias).strip()
        if not a:
            continue

        wallet_name = str(w.get("wallet_name", "")).strip() or str(w.get("coldkey_name", "")).strip()
        default_validator = str(w.get("default_validator", "")).strip() or str(w.get("default_target_hotkey", "")).strip()

        default_netuid = w.get("default_netuid", None)
        if default_netuid is not None:
            try:
                default_netuid = int(default_netuid)
            except Exception:
                default_netuid = None

        validator_all = str(w.get("validator_all", "")).strip()
        validator_by_netuid = _parse_int_keyed_map(w.get("validator_by_netuid", {}))

        wallets[a] = BtcliWalletProfile(
            alias=a,
            wallet_name=wallet_name,
            password=str(w.get("password", "")).strip(),
            default_validator=default_validator,
            default_netuid=default_netuid,
            validator_all=validator_all,
            validator_by_netuid=validator_by_netuid,
        )

    # Back-compat single wallet
    if not wallets:
        old_wallet = bt.get("wallet", {}) or {}
        old_name = str(old_wallet.get("coldkey_name", "")).strip()
        old_default_hotkey = str(old_wallet.get("default_target_hotkey", "")).strip()
        if old_name:
            wallets["default"] = BtcliWalletProfile(
                alias="default",
                wallet_name=old_name,
                password=str(old_wallet.get("password", "")).strip(),
                default_validator=old_default_hotkey,
                default_netuid=None,
                validator_all="",
                validator_by_netuid={},
            )

    if not wallets:
        raise ValueError("btcli.wallets must have at least one wallet profile")

    default_wallet = str(bt.get("default_wallet", "")).strip() or (list(wallets.keys())[0])

    # Validators sources
    sources_list: List[ValidatorSource] = []
    sources_raw = validators_raw.get("sources", None)

    # Back-compat: taostats_api_* fields
    legacy_key = str(validators_raw.get("taostats_api_key", "")).strip()
    legacy_url = str(validators_raw.get("taostats_api_url", "")).strip()
    if sources_raw is None:
        sources_raw = []
        if legacy_url or legacy_key:
            sources_raw.append({
                "type": "taostats",
                "api_url": legacy_url or "https://api.taostats.io/api/dtao/validator/latest/v1",
                "api_key": legacy_key,
            })

    if isinstance(sources_raw, list):
        for s in sources_raw:
            if not isinstance(s, dict):
                continue
            typ = str(s.get("type", "")).strip().lower()
            if typ == "taostats":
                sources_list.append(ValidatorSourceTaostats(
                    type="taostats",
                    api_url=str(s.get("api_url", "https://api.taostats.io/api/dtao/validator/latest/v1")).strip(),
                    api_key=str(s.get("api_key", "")).strip(),
                ))
            elif typ == "http_json":
                hdrs = s.get("headers", {}) or {}
                sources_list.append(ValidatorSourceHttpJson(
                    type="http_json",
                    url=str(s.get("url", "")).strip(),
                    headers={str(k): str(v) for k, v in hdrs.items()} if isinstance(hdrs, dict) else {},
                    data_path=str(s.get("data_path", "")).strip(),
                    name_field=str(s.get("name_field", "name")).strip() or "name",
                    hotkey_field=str(s.get("hotkey_field", "hotkey")).strip() or "hotkey",
                ))
            elif typ == "file_json":
                sources_list.append(ValidatorSourceFileJson(
                    type="file_json",
                    path=str(s.get("path", "")).strip(),
                    data_path=str(s.get("data_path", "")).strip(),
                    name_field=str(s.get("name_field", "name")).strip() or "name",
                    hotkey_field=str(s.get("hotkey_field", "hotkey")).strip() or "hotkey",
                ))

    cfg = RootConfig(
        app=AppConfig(
            mode=str(app.get("mode", "dry")).lower(),
            timezone=str(app.get("timezone", "UTC")),
            data_dir=str(app.get("data_dir", "./data")),
            log_file=str(app.get("log_file", "./data/bot.log.jsonl")),
            require_confirmation=bool(app.get("require_confirmation", True)),
            confirmation_expires_minutes=int(app.get("confirmation_expires_minutes", 5)),
            allow_groups=bool(app.get("allow_groups", False)),
            confirm_over_tao=float(app.get("confirm_over_tao", 1.0)),
            confirm_over_alpha=float(app.get("confirm_over_alpha", 200.0)),
            rate_limit_per_minute=int(app.get("rate_limit_per_minute", 3)),
            rate_limit_per_hour=int(app.get("rate_limit_per_hour", 30)),
            max_tao_per_tx=float(app.get("max_tao_per_tx", 5.0)),
            daily_max_tao=float(app.get("daily_max_tao", 20.0)),
            max_alpha_per_tx=float(app.get("max_alpha_per_tx", 500.0)),
            daily_max_alpha=float(app.get("daily_max_alpha", 2000.0)),
        ),
        allow=AuthAllow(
            telegram_user_ids=[int(x) for x in (auth.get("telegram_user_ids", []) or [])],
            discord_user_ids=[int(x) for x in (auth.get("discord_user_ids", []) or [])],
        ),
        btcli=BtcliConfig(
            path=str(bt.get("path", "btcli")) or "btcli",
            wallets_path=(str(bt.get("wallets_path", "")).strip() or os.path.expanduser("~/.bittensor/wallets")),
            common_args=[str(x) for x in (bt.get("common_args", []) or [])],
            default_wallet=default_wallet,
            wallets=wallets,
            staking=BtcliStakingDefaults(
                safe=bool((bt.get("staking", {}) or {}).get("safe", True)),
                tolerance=float((bt.get("staking", {}) or {}).get("tolerance", 0.10)),
                no_partial=bool((bt.get("staking", {}) or {}).get("no_partial", True)),
            ),
        ),
        validators=ValidatorsConfig(
            cache_ttl_minutes=int(validators_raw.get("cache_ttl_minutes", 360)),
            delegates_fallback_url=str(
                validators_raw.get(
                    "delegates_fallback_url",
                    "https://raw.githubusercontent.com/opentensor/bittensor-delegates/main/public/delegates.json",
                )
            ),
            sources=sources_list,
        ),
        defaults=DefaultsConfig(
            validator_all=str(defaults_raw.get("validator_all", "")).strip(),
            validator_by_netuid=_parse_int_keyed_map(defaults_raw.get("validator_by_netuid", {})),
        ),
        channels=ChannelsConfig(
            telegram=TelegramConfig(
                enabled=bool((channels.get("telegram", {}) or {}).get("enabled", False)),
                token=str((channels.get("telegram", {}) or {}).get("token", "")),
            ),
            discord=DiscordConfig(
                enabled=bool((channels.get("discord", {}) or {}).get("enabled", False)),
                token=str((channels.get("discord", {}) or {}).get("token", "")),
                guild_ids=[int(x) for x in ((channels.get("discord", {}) or {}).get("guild_ids", []) or [])],
            ),
        ),
        licensing=LicensingConfig(
            server_url=str(licensing_raw.get("server_url", "https://license.easyape.io")).strip() or "https://license.easyape.io",
            grace_hours=int(licensing_raw.get("grace_hours", 24)),
        ),
    )


    if cfg.app.mode not in ("dry", "live"):
        raise ValueError("app.mode must be 'dry' or 'live'")

    if cfg.btcli.default_wallet not in cfg.btcli.wallets:
        raise ValueError("btcli.default_wallet must be a key in btcli.wallets")

    for alias, w in cfg.btcli.wallets.items():
        if not w.wallet_name:
            raise ValueError(f"btcli.wallets.{alias}.wallet_name is required")

    return cfg
