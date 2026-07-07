# daily_post.py — One-shot script for GitHub Actions

import sys
import os
import json
import asyncio
import traceback

print("🚀 daily_post.py started", flush=True)

try:
    import discord
    from dotenv import load_dotenv
    from leaderboard import build_leaderboard, generate_image
except ImportError as e:
    print(f"❌ Import error: {e}", flush=True)
    print(traceback.format_exc(), flush=True)
    sys.exit(1)

load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1515428743634616400

print(f"📌 TOKEN present: {bool(TOKEN)}", flush=True)
print(f"📌 CHANNEL_ID: {CHANNEL_ID}", flush=True)

if not TOKEN:
    print("❌  DISCORD_TOKEN is not set — check your GitHub secret", flush=True)
    sys.exit(1)

def load_players(filepath="players.json"):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    print("⏰  Running daily leaderboard post...", flush=True)

    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)
    success = False

    @client.event
    async def on_ready():
        nonlocal success
        try:
            print("✅ Bot connected, fetching channel...", flush=True)
            channel = await client.fetch_channel(CHANNEL_ID)
            print(f"✅ Channel found: {channel.name}", flush=True)

            # Delete old messages
            await channel.purge(limit=100)
            print("🗑️  Cleared old messages", flush=True)

            # Build full leaderboard
            players = load_players()
            print(f"📋 Loaded {len(players)} players", flush=True)

            ranked = await build_leaderboard(players)
            print(f"📊 Leaderboard built with {len(ranked)} players", flush=True)

            # Split into chunks of 12
            chunk1 = ranked[:12]
            chunk2 = ranked[12:]

            # Generate images and post
            print("🖼️  Generating image 1...", flush=True)
            image1 = generate_image(chunk1, "leaderboard1.png")
            if chunk2:
                print("🖼️  Generating image 2...", flush=True)
                image2 = generate_image(chunk2, "leaderboard2.png", start_rank=13)
                await channel.send(
                    content="🏆 **Brawlhalla Daily Leaderboard**",
                    files=[discord.File(image1), discord.File(image2)]
                )
                print(f"✅  Both images posted ({len(ranked)} players)", flush=True)
            else:
                await channel.send(
                    content="🏆 **Brawlhalla Daily Leaderboard**",
                    files=[discord.File(image1)]
                )
                print("✅  Image posted", flush=True)

            success = True

        except Exception as e:
            print(f"❌  Error: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
        finally:
            await client.close()

    await client.start(TOKEN)

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Unhandled exception in main: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
