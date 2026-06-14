# daily_post.py — One-shot script for GitHub Actions

import discord
import asyncio
import os
import json
from dotenv import load_dotenv
from leaderboard import build_leaderboard, generate_image

load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1515428743634616400

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

            # Build full leaderboard
            players = load_players()
            ranked  = build_leaderboard(players)

            # Split into chunks of 12
            chunk1 = ranked[:12]
            chunk2 = ranked[12:]

            # Generate images
            image1 = generate_image(chunk1, "leaderboard1.png")

            if chunk2:
                image2 = generate_image(chunk2, "leaderboard2.png", start_rank=13)
                await channel.send(
                    content="🏆 **Brawlhalla Daily Leaderboard**",
                    files=[discord.File(image1), discord.File(image2)]
                )
                print(f"✅  Both images posted ({len(ranked)} players)")
            else:
                await channel.send(
                    content="🏆 **Brawlhalla Daily Leaderboard**",
                    files=[discord.File(image1)]
                )
                print("✅  Image posted")

        except Exception as e:
            print(f"❌  Error: {e}")
        finally:
            await client.close()

    await client.start(TOKEN)

asyncio.run(main())
