from __future__ import annotations

import argparse
import asyncio
import os
import signal as os_signal

from .config import load_config
from .engine import Engine
from .adapters.telegram_adapter import run_telegram
from .adapters.discord_adapter import run_discord


async def amain() -> int:
    parser = argparse.ArgumentParser(description="EasyApe — text to stake (Telegram/Discord -> btcli)")
    parser.add_argument("--config", default=os.getenv("STAKECHAT_CONFIG", "config.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    engine = Engine(cfg)

    # Start / refresh server-tracked trial + license state
    await engine.licensing.bootstrap()

    # Startup banner (headless-friendly)
    try:
        links = engine.licensing.links()
        print("EasyApe 🦍 — text to stake")
        print(engine.licensing.trial_status_line())
        if links.get('billing_url'):
            print(f"Subscribe: {links['billing_url']}")
        if links.get('manage_url'):
            print(f"Manage:   {links['manage_url']}")
        print("\nPrivacy: EasyApe is self-hosted; no usage analytics are collected. Run 'privacy' in chat for details.")
        print("Tip: DM 'help' or 'whoami' to the bot from Telegram/Discord once connected.")
        print("—" * 60)
    except Exception:
        pass

    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    tasks = []

    if cfg.channels.telegram.enabled:
        tasks.append(asyncio.create_task(run_telegram(engine, cfg.channels.telegram.token, stop_event)))

    if cfg.channels.discord.enabled:
        tasks.append(asyncio.create_task(run_discord(engine, cfg.channels.discord.token, cfg.channels.discord.guild_ids, stop_event)))

    if not tasks:
        raise SystemExit("No channels enabled. Enable telegram/discord in config.yaml.")

    await stop_event.wait()

    # Allow adapters to shutdown
    await asyncio.gather(*tasks, return_exceptions=True)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
