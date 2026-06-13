import discord
from discord.ext import commands
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os
import json

# ── Load environment variables ────────────────────────────────────────────────
load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1514834659358277713

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler(timezone="Asia/Karachi")

# ── Events ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅  Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"    Connected to {len(bot.guilds)} server(s)")
    try:
        guild = discord.Object(id=1509423625919529072)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"    Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"    Sync error: {e}")

    if not scheduler.running:
        scheduler.add_job(
            post_daily_leaderboard,
            CronTrigger(hour=12, minute=0, timezone="Asia/Karachi"),
        )
        scheduler.start()
        print("    ⏰  Scheduler started — daily post at 12:00 PM PKT")

# ── Daily auto-post function ───────────────────────────────────────────────────
async def post_daily_leaderboard():
    print("⏰  Running daily leaderboard post...")

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"❌  Channel {CHANNEL_ID} not found")
        return

    # Delete all previous messages in the channel
    try:
        deleted = await channel.purge(limit=100)
        print(f"🗑️  Deleted {len(deleted)} old message(s)")
    except Exception as e:
        print(f"⚠️  Could not delete old messages: {e}")

    from leaderboard import build_leaderboard, generate_image

    player_list = load_players()
    if not player_list:
        await channel.send("⚠️  No players in `players.json`.")
        return

    ranked = build_leaderboard(player_list)
    image_path = generate_image(ranked, "leaderboard.png")

    await channel.send(
        content="🏆 **Brawlhalla Pakistan Daily Leaderboard**",
        file=discord.File(image_path)
    )
    print("✅  Daily leaderboard posted!")

# ── /ping ─────────────────────────────────────────────────────────────────────
@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: **{latency_ms} ms**")

# ── /players ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="players", description="List all tracked players")
async def players(interaction: discord.Interaction):
    player_list = load_players()
    if not player_list:
        await interaction.response.send_message("⚠️  No players found in `players.json`.")
        return
    lines = ["**Pakistan Leaderboard — Tracked Players**\n"]
    for i, p in enumerate(player_list, start=1):
        lines.append(f"`{i:>2}.` {p['name']}  *(ID: {p['brawlhalla_id']})*")
    await interaction.response.send_message("\n".join(lines))

# ── /leaderboard ──────────────────────────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Show live ELO leaderboard image")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()

    from leaderboard import build_leaderboard, generate_image

    player_list = load_players()
    if not player_list:
        await interaction.followup.send("⚠️  No players in `players.json`.")
        return

    ranked = build_leaderboard(player_list)
    image_path = generate_image(ranked, "leaderboard.png")

    await interaction.followup.send(
        content="🏆 **Pakistan Brawlhalla Leaderboard**",
        file=discord.File(image_path)
    )

# ── Helper ────────────────────────────────────────────────────────────────────
def load_players(filepath: str = "players.json") -> list[dict]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️  {filepath} not found")
        return []
    except json.JSONDecodeError as e:
        print(f"❌  Failed to parse {filepath}: {e}")
        return []

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN missing — check your .env file")
    bot.run(TOKEN)