from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands

from ..engine import Engine
from ..policy import Sender


@dataclass(frozen=True)
class DiscordAdapterConfig:
    token: str
    guild_ids: List[int]


def _sender_from_interaction(interaction: discord.Interaction) -> Sender:
    user_id = str(interaction.user.id) if interaction.user else "0"
    chat_is_group = interaction.guild is not None
    return Sender(platform="discord", sender_id=user_id, chat_is_group=chat_is_group)


async def run_discord(engine: Engine, token: str, guild_ids: List[int], stop_event: asyncio.Event) -> None:
    if not token:
        raise ValueError("Discord enabled but token is empty")

    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        if guild_ids:
            for gid in guild_ids:
                guild = discord.Object(id=gid)
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
        print(f"[discord] logged in as {bot.user}")

    @bot.tree.command(name="help", description="Show EasyApe commands")
    async def help_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "help")
        await interaction.response.send_message(resp, ephemeral=True)

    
    @bot.tree.command(name="whoami", description="Show your platform ID for onboarding")
    async def whoami_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "whoami")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="wallets", description="List allowed wallets")
    async def wallets_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "wallets")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="inventory", description="Show stake inventory (stake list)")
    @app_commands.describe(wallet="Wallet alias/name (optional)")
    async def inventory_cmd(interaction: discord.Interaction, wallet: Optional[str] = None):
        sender = _sender_from_interaction(interaction)
        cmd = "inventory" + (f" {wallet}" if wallet else "")
        resp = await engine.handle(sender, cmd)
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="balance", description="Show TAO balance for wallet")
    @app_commands.describe(wallet="Wallet alias/name (optional)")
    async def balance_cmd(interaction: discord.Interaction, wallet: Optional[str] = None):
        sender = _sender_from_interaction(interaction)
        cmd = "balance" + (f" {wallet}" if wallet else "")
        resp = await engine.handle(sender, cmd)
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="mode", description="Set mode (dry or live)")
    @app_commands.describe(mode="dry or live")
    async def mode_cmd(interaction: discord.Interaction, mode: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"mode {mode}")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="stake", description="Stake TAO (validator can be name or SS58; omit to use defaults)")
    @app_commands.describe(wallet="Wallet alias/name (optional)", netuid="Subnet netuid (optional if wallet default_netuid set)", tao_amount="Amount to stake (TAO)", validator="Validator name or SS58 (optional)")
    async def stake_cmd(interaction: discord.Interaction, tao_amount: float, netuid: Optional[int] = None, validator: Optional[str] = None, wallet: Optional[str] = None):
        sender = _sender_from_interaction(interaction)
        parts = ["stake"]
        if wallet:
            parts.append(wallet)
        if netuid is not None:
            parts += [str(netuid), str(tao_amount)]
        else:
            parts += [f"{tao_amount:.6f}"]
        if validator:
            parts.append(validator)
        resp = await engine.handle(sender, " ".join(parts))
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="unstake", description="Unstake Alpha (validator can be name or SS58; omit to use defaults)")
    @app_commands.describe(wallet="Wallet alias/name (optional)", netuid="Subnet netuid (optional if wallet default_netuid set)", alpha_amount="Amount to unstake (Alpha)", validator="Validator name or SS58 (optional)")
    async def unstake_cmd(interaction: discord.Interaction, alpha_amount: float, netuid: Optional[int] = None, validator: Optional[str] = None, wallet: Optional[str] = None):
        sender = _sender_from_interaction(interaction)
        parts = ["unstake"]
        if wallet:
            parts.append(wallet)
        if netuid is not None:
            parts += [str(netuid), str(alpha_amount)]
        else:
            parts += [f"{alpha_amount:.6f}"]
        if validator:
            parts.append(validator)
        resp = await engine.handle(sender, " ".join(parts))
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="confirm", description="Confirm a pending live action")
    @app_commands.describe(token="Confirmation token, e.g. ABC123")
    async def confirm_cmd(interaction: discord.Interaction, token: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"confirm {token}")
        await interaction.response.send_message(resp, ephemeral=True)

    # Validator registry commands
    @bot.tree.command(name="validators_sources", description="Show validator registry sources")
    async def validators_sources_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "validators sources")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="validators_refresh", description="Refresh local validator registry cache")
    async def validators_refresh_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "validators refresh")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="validators_search", description="Search validators by name")
    @app_commands.describe(term="Search term, e.g. tao")
    async def validators_search_cmd(interaction: discord.Interaction, term: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"validators search {term}")
        await interaction.response.send_message(resp, ephemeral=True)

    # Defaults / routing commands
    @bot.tree.command(name="defaults", description="Show current defaults and runtime overrides")
    async def defaults_cmd(interaction: discord.Interaction):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, "show defaults")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="set_default_validator", description="Set runtime default validator for all subnets")
    @app_commands.describe(value="Validator name or SS58")
    async def set_default_validator_cmd(interaction: discord.Interaction, value: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"set default validator {value}")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="set_netuid_validator", description="Set runtime validator for a specific netuid (global)")
    @app_commands.describe(netuid="Subnet netuid", value="Validator name or SS58")
    async def set_netuid_validator_cmd(interaction: discord.Interaction, netuid: int, value: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"set netuid {netuid} validator {value}")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="set_wallet_default_validator", description="Set runtime default validator for a wallet")
    @app_commands.describe(wallet="Wallet alias/name", value="Validator name or SS58")
    async def set_wallet_default_validator_cmd(interaction: discord.Interaction, wallet: str, value: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"set wallet {wallet} default validator {value}")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="set_wallet_netuid_validator", description="Set runtime validator for a wallet+netuid")
    @app_commands.describe(wallet="Wallet alias/name", netuid="Subnet netuid", value="Validator name or SS58")
    async def set_wallet_netuid_validator_cmd(interaction: discord.Interaction, wallet: str, netuid: int, value: str):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"set wallet {wallet} netuid {netuid} validator {value}")
        await interaction.response.send_message(resp, ephemeral=True)

    @bot.tree.command(name="set_wallet_default_netuid", description="Set runtime default netuid for a wallet (enables turbo)")
    @app_commands.describe(wallet="Wallet alias/name", netuid="Subnet netuid")
    async def set_wallet_default_netuid_cmd(interaction: discord.Interaction, wallet: str, netuid: int):
        sender = _sender_from_interaction(interaction)
        resp = await engine.handle(sender, f"set wallet {wallet} default netuid {netuid}")
        await interaction.response.send_message(resp, ephemeral=True)

    task = asyncio.create_task(bot.start(token))
    try:
        await stop_event.wait()
    finally:
        await bot.close()
        task.cancel()
