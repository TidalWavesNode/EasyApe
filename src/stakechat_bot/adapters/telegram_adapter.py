from __future__ import annotations

import asyncio
from dataclasses import dataclass

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from ..engine import Engine
from ..policy import Sender


@dataclass(frozen=True)
class TelegramAdapterConfig:
    token: str


async def run_telegram(engine: Engine, token: str, stop_event: asyncio.Event) -> None:
    if not token:
        raise ValueError("Telegram enabled but token is empty")

    app = ApplicationBuilder().token(token).build()

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_chat or not update.message:
            return
        user_id = str(update.effective_user.id)
        chat = update.effective_chat
        text = update.message.text or ""

        sender = Sender(
            platform="telegram",
            sender_id=user_id,
            chat_is_group=bool(chat.type in ("group", "supergroup")),
        )

        resp = await engine.handle(sender, text)
        await update.message.reply_text(resp)

    app.add_handler(MessageHandler(filters.TEXT & (~filters.StatusUpdate.ALL), on_text))

    await app.initialize()
    await app.start()
    # polling
    await app.updater.start_polling()

    try:
        await stop_event.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
