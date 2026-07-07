# daily_post.py — One-shot script for GitHub Actions
import discord
import asyncio
import os
import json
import sys
from dotenv import load_dotenv
from leaderboard import build_leaderboard, generate_image

load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1515428743634616400

# Fail early if token is missing
if not TOKEN:
    print("❌  DISCORD_TOKEN is not set — check your GitHub secret")
    sys.exit(1)

def load_players(filepath="players.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    print("⏰  Running daily leaderboard post...")

    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)
    success = False

    @client.event
    async def on_ready():
        nonlocal success
        try:
            # fetch_channel makes an API call — more reliable than get_channel
            # which depends on the cache and can silently return None
            channel = await client.fetch_channel(CHANNEL_ID)

            # Delete old messages
            await channel.purge(limit=100)
            print("🗑️  Cleared old messages")

            # Build full leaderboard
            players = load_players()
            ranked  = await build_leaderboard(players)

            # Split into chunks of 12
            chunk1 = ranked[:12]
            chunk2 = ranked[12:]

            # Generate images and post
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

            success = True

        except Exception as e:
            print(f"❌  Error: {e}")
        finally:
            await client.close()

    await client.start(TOKEN)

    # Exit with code 1 so GitHub Actions marks the run as FAILED, not green
    if not success:
        sys.exit(1)

asyncio.run(main())
