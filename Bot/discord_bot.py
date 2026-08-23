
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


def parse_flags(text: str) -> tuple[list[str], dict]:
    """'"polo ralph lauren" --max-price 15 --size M,L' ->
    (['polo ralph lauren'], {'max-price': '15', 'size': 'M,L'})"""
    tokens = shlex.split(text)
    positional, flags = [], {}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("--"):
            key = t[2:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                flags[key] = tokens[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positional.append(t)
            i += 1
    return positional, flags


def build_bot(config: dict) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True  # requis pour lire les commandes texte
    bot = commands.Bot(command_prefix=config.get("command_prefix", "!"), intents=intents)
    channel_names = config.get("channels", {})

    # ── !watch ────────────────────────────────────────────────────────
    @bot.group(name="watch", invoke_without_command=True)
    async def watch_group(ctx):
        await ctx.send("Sous-commandes : `add`, `list`, `remove <id>`, `enable <id>`, `disable <id>`")

    @watch_group.command(name="add")
    async def watch_add(ctx, *, args: str):
        """!watch add "polo ralph lauren" --max-price 15 --category homme --rotation 7 --margin 120"""
        positional, flags = parse_flags(args)
        if not positional:
            await ctx.send("Il faut au moins un nom/mot-clé entre guillemets. "
                            "Exemple : `!watch add \"polo ralph lauren\" --max-price 15`")
            return

        name = positional[0]
        keywords = name.split()
        max_price = float(flags["max-price"]) if "max-price" in flags else None
        category = flags.get("category")
        rotation = int(flags.get("rotation", 10))
        margin = float(flags.get("margin", 120))

        watch_id = db.add_watch(
            name=name,
            keywords=keywords,
            max_price=max_price,
            category=category,
            target_rotation_days=rotation,
            min_margin_pct=margin,
        )
        note = ""
        if "size" in flags or "color" in flags or "brand" in flags:
            note = ("\n⚠️ Les filtres `--size`/`--color`/`--brand` sont enregistrés mais "
                    "pas encore appliqués à la recherche Vinted elle-même (il manque le "
                    "mapping texte→ID Vinted). Pour l'instant seuls les mots-clés, la "
                    "catégorie et le prix max filtrent réellement.")
        await ctx.send(f"✅ Watch **#{watch_id} — {name}** créée "
                        f"(max {max_price or '∅'}€, rotation {rotation}j, marge min {margin}%).{note}")

    @watch_group.command(name="list")
    async def watch_list(ctx):
        watches = db.list_watches()
        if not watches:
            await ctx.send("Aucune watch configurée.")
            return
        lines = []
        for w in watches:
            status = "🟢" if w["is_active"] else "⚪"
            mp = f"{w['market_price']:.2f}€" if w["market_price"] else "?"
            lines.append(f"{status} `#{w['id']}` **{w['name']}** — "
                          f"max {w['max_price'] or '∅'}€ · marché {mp} · rotation {w['target_rotation_days']}j")
        embed = discord.Embed(title="📋 Watches configurées", description="\n".join(lines),
                               color=0x1DBF73)
        await ctx.send(embed=embed)

    @watch_group.command(name="remove")
    async def watch_remove(ctx, watch_id: int):
        ok = db.remove_watch(watch_id)
        await ctx.send(f"🗑️ Watch #{watch_id} supprimée." if ok else f"Watch #{watch_id} introuvable.")

    @watch_group.command(name="enable")
    async def watch_enable(ctx, watch_id: int):
        ok = db.set_watch_active(watch_id, True)
        await ctx.send(f"🟢 Watch #{watch_id} activée." if ok else f"Watch #{watch_id} introuvable.")

    @watch_group.command(name="disable")
    async def watch_disable(ctx, watch_id: int):
        ok = db.set_watch_active(watch_id, False)
        await ctx.send(f"⚪ Watch #{watch_id} désactivée." if ok else f"Watch #{watch_id} introuvable.")

    # ── !stats ────────────────────────────────────────────────────────
    @bot.group(name="stats", invoke_without_command=True)
    async def stats_group(ctx):
        await stats_today(ctx)

    async def _send_stats(ctx, days: int, label: str):
        rows = db.get_stats_range(days)
        revenue = sum(r["revenue"] for r in rows)
        profit = sum(r["profit"] for r in rows)
        sold = sum(r["items_sold"] for r in rows)
        listed = sum(r["items_listed"] for r in rows)
        opps = sum(r["opportunities_found"] for r in rows)
        embed = discord.Embed(title=f"📊 Stats — {label}", color=0x1DBF73)
        embed.add_field(name="CA", value=f"{revenue:.2f}€", inline=True)
        embed.add_field(name="Bénéfice net", value=f"{profit:.2f}€", inline=True)
        embed.add_field(name="Articles vendus", value=str(sold), inline=True)
        embed.add_field(name="Articles listés", value=str(listed), inline=True)
        embed.add_field(name="Opportunités trouvées", value=str(opps), inline=True)
        embed.set_footer(text="CA/bénéfice/ventes se remplissent quand tu enregistres tes "
                               "ventes (F5, pas encore branché) — les opportunités sont "
                               "déjà comptées automatiquement par le scanner.")
        await ctx.send(embed=embed)

    @stats_group.command(name="today")
    async def stats_today(ctx):
        await _send_stats(ctx, 1, "aujourd'hui")

    @stats_group.command(name="week")
    async def stats_week(ctx):
        await _send_stats(ctx, 7, "7 derniers jours")

    @stats_group.command(name="month")
    async def stats_month(ctx):
        await _send_stats(ctx, 30, "30 derniers jours")

    # ── !pricing ──────────────────────────────────────────────────────
    @bot.group(name="pricing", invoke_without_command=True)
    async def pricing_group(ctx):
        await ctx.send("Sous-commande : `check <url_ou_id_vinted>`")

    @pricing_group.command(name="check")
    async def pricing_check(ctx, url_or_id: str):
        client: VintedClient = ctx.bot.vinted_client
        item_id = extract_item_id(url_or_id)
        item = await ctx.bot.loop.run_in_executor(None, client.get_item, item_id)
        if not item:
            await ctx.send("Annonce introuvable (ID/URL invalide, ou article supprimé).")
            return

        from .vinted_client import item_price
        price = item_price(item)
        if price is None:
            await ctx.send("Impossible de lire le prix de cette annonce.")
            return

        from .scanner import compute_market_price
        params = {"search_text": item.get("title", ""), "status_ids": [2, 3, 4]}
        market_price = await ctx.bot.loop.run_in_executor(
            None, compute_market_price, client, params
        )
        if not market_price:
            await ctx.send("Pas assez de données pour estimer le prix marché de cet article.")
            return

        result = pricing.compute_rentability(price, market_price)
        embed = discord.Embed(
            title=item.get("title", "Annonce Vinted"),
            url=f"{client.base_url}/items/{item_id}",
            color=0x1DBF73 if result["recommendation"] == "ACHETER" else 0xE74C3C,
        )
        embed.add_field(name="Prix", value=f"{price:.2f}€", inline=True)
        embed.add_field(name="Prix médian estimé", value=f"{market_price:.2f}€", inline=True)
        embed.add_field(name="Marge brute", value=f"{result['marge_brute_pct']:.0f}%", inline=True)
        embed.add_field(name="Score", value=f"{result['score']}/100", inline=True)
        embed.add_field(name="Recommandation", value=result["recommendation"], inline=True)
        await ctx.send(embed=embed)

    # ── !config ───────────────────────────────────────────────────────
    @bot.group(name="config", invoke_without_command=True)
    async def config_group(ctx):
        await ctx.send("Sous-commande : `set <clé> <valeur>` (ex: `!config set min-margin 120`)")

    @config_group.command(name="set")
    async def config_set(ctx, key: str, value: str):
        db.set_setting(key, value)
        await ctx.send(f"⚙️ `{key}` = `{value}`")

    @bot.event
    async def on_ready():
        log.info("Bot Discord connecté en tant que %s", bot.user)

    @bot.event
    async def on_command_error(ctx, error):
        log.warning("Erreur commande: %s", error)
        await ctx.send(f"❌ {error}")

    return bot


async def send_opportunity_embed(bot: commands.Bot, channel_name: str, watch, item, price, url, result):
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return
    channel = get_channel(guild, channel_name)
    if not channel:
        log.warning("Salon '%s' introuvable sur le serveur.", channel_name)
        return

    photo = (item.get("photo") or {}).get("url")
    embed = discord.Embed(
        title=f"🎯 OPPORTUNITÉ — {item.get('title', 'Annonce Vinted')}",
        url=url,
        color=0x1DBF73,
    )
    embed.add_field(name="Prix", value=f"{price:.2f}€", inline=True)
    embed.add_field(name="Prix médian marché", value=f"{result['prix_vente_estime']:.2f}€", inline=True)
    embed.add_field(name="Marge estimée", value=f"+{result['marge_brute_pct']:.0f}%", inline=True)
    embed.add_field(name="Score", value=f"{result['score']}/100", inline=True)
    embed.add_field(name="Rotation cible", value=f"{watch['target_rotation_days']}j", inline=True)
    embed.add_field(name="Watch", value=watch["name"], inline=True)
    if photo:
        embed.set_thumbnail(url=photo)
    await channel.send(embed=embed)


async def send_error(bot: commands.Bot, channel_name: str, message: str):
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return
    channel = get_channel(guild, channel_name)
    if channel:
        await channel.send(f"⚠️ {message}")
      
