# test_elo.py  —  Run this BEFORE touching bot.py
# Tests the Brawlhalla v1 API with a real known player ID
# Usage: python test_elo.py

from leaderboard import fetch_ranked, build_leaderboard, generate_image
import json

# ── Test 1: Fetch one known player (Boomie — a real top player) ────────────────
print("=" * 50)
print("TEST 1 — Fetch single player")
print("=" * 50)
result = fetch_ranked("257670")   # Boomie's real ID
if result:
    print(f"✅  Got data: {json.dumps(result, indent=2)}")
else:
    print("❌  No data returned — check your internet connection")

# ── Test 2: Build leaderboard from your players.json ─────────────────────────
print("\n" + "=" * 50)
print("TEST 2 — Build leaderboard from players.json")
print("=" * 50)

with open("players.json") as f:
    players = json.load(f)

leaderboard = build_leaderboard(players)
for i, p in enumerate(leaderboard, 1):
    print(f"  {i}. {p['display_name']:20s}  ELO: {p['rating']:>4}  Tier: {p['tier']}")

# ── Test 3: Generate image ────────────────────────────────────────────────────
print("\n" + "=" * 50)
print("TEST 3 — Generate image")
print("=" * 50)
generate_image(leaderboard, "leaderboard_test.png")
print("Open leaderboard_test.png to check the design!")