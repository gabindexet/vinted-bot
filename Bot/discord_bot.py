from __future__ import annotations

import logging
import shlex
from datetime import date

import discord
from discord.ext import commands

from . import db, pricing
from .vinted_client import VintedClient, extract_item_id

log = logging.getLogger("vinted-bot")


def get_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=name)


def parse_flag
