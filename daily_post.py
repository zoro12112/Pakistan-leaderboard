# daily_post.py — One-shot script for GitHub Actions
# Fetches ELO, generates image, posts to Discord, then exits.

import discord
import asyncio
import os
import json
from dotenv import load_dotenv
from leaderboard import build_leaderboard, generate_image

load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1514834659358277713

def load_players(filepath="players.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    print("⏰  Running daily leaderboard post...")

    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            channel = client.get_channel(CHANNEL_ID)
            if not channel:
                print(f"❌  Channel {CHANNEL_ID} not found")
                await client.close()
                return

            # Delete old messages
            await channel.purge(limit=100)
            print("🗑️  Cleared old messages")

            # Build and post
            players    = load_players()
            ranked     = build_leaderboard(players)
            image_path = generate_image(ranked, "leaderboard.png")

            await channel.send(
                content="🏆 **Pakistan Brawlhalla Daily Leaderboard**",
                file=discord.File(image_path)
            )
            print("✅  Leaderboard posted!")

        except Exception as e:
            print(f"❌  Error: {e}")
        finally:
            await client.close()  # exit after posting

    await client.start(TOKEN)

asyncio.run(main())
