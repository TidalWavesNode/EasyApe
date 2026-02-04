from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import RootConfig


@dataclass(frozen=True)
class Sender:
    platform: str           # telegram|discord
    sender_id: str          # normalized string id
    chat_is_group: bool     # for group protection


def is_allowed(cfg: RootConfig, sender: Sender) -> bool:
    if sender.chat_is_group and not cfg.app.allow_groups:
        return False

    if sender.platform == "telegram":
        try:
            uid = int(sender.sender_id)
        except Exception:
            return False
        return uid in cfg.allow.telegram_user_ids

    if sender.platform == "discord":
        try:
            uid = int(sender.sender_id)
        except Exception:
            return False
        return uid in cfg.allow.discord_user_ids

    return False
