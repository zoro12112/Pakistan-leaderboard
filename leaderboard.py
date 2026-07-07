import requests
import os
import json
import asyncio
from PIL import Image, ImageDraw, ImageFont

BH_API    = "https://api.brawlhalla.com/v1"
ASSETS    = "assets"
HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TIER_COLORS = {
    "Valhallan": (220,  80,  80),
    "Diamond":   ( 80, 210, 255),
    "Platinum":  ( 80, 200, 175),
    "Gold":      (255, 195,  50),
    "Silver":    (175, 185, 205),
    "Bronze":    (195, 130,  70),
    "Tin":       (140, 145, 155),
    "Unranked":  ( 90,  90, 110),
}

def tier_color(tier: str):
    for key in TIER_COLORS:
        if tier.startswith(key):
            return TIER_COLORS[key]
    return TIER_COLORS["Unranked"]

def ensure_assets_dir():
    os.makedirs(f"{ASSETS}/legends", exist_ok=True)

def download_image(url: str, save_path: str) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"⚠️  Could not download {url}: {e}")
        return False

def get_legend_image(legend_name: str):
    safe_name = legend_name.lower().replace(" ", "_").replace("'", "")
    path      = f"{ASSETS}/legends/{safe_name}.png"
    if not os.path.exists(path):
        sources = [
            f"https://corehalla.com/images/legends/{legend_name}.png",
            f"https://corehalla.com/images/legends/{legend_name.lower()}.png",
            f"https://static.wikia.nocookie.net/brawlhalla/images/legends/{legend_name}_Portrait.png",
        ]
        for url in sources:
            if download_image(url, path):
                break
    if os.path.exists(path):
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            pass
    return None

LEGEND_CACHE_PATH = f"{ASSETS}/legends_map.json"

def load_legend_map() -> dict:
    ensure_assets_dir()
    if os.path.exists(LEGEND_CACHE_PATH):
        with open(LEGEND_CACHE_PATH) as f:
            return json.load(f)
    print("⬇️   Fetching legend list...")
    try:
        r = requests.get(f"{BH_API}/legends", timeout=10)
        r.raise_for_status()
        data = r.json()
        legend_map = {str(l["legend_id"]): l["legend_name_key"].title() for l in data}
        with open(LEGEND_CACHE_PATH, "w") as f:
            json.dump(legend_map, f)
        print(f"✅  Cached {len(legend_map)} legends")
        return legend_map
    except Exception as e:
        print(f"⚠️  Could not fetch legends: {e}")
        return {}

# ── Fetch 1v1 stats with flexible retries ─────────────────────────────

async def fetch_stats_with_retry(brawlhalla_id: str, mode: str = "ranked_1v1", retries=3, delay=1.0) -> dict | None:
    """
    Fetch stats for a specific mode, retrying on failure.
    Returns a dict with rating, tier, etc. if successful, else None.
    """
    url = f"{BH_API}/player/stats"
    params = {"brawlhalla_id": brawlhalla_id, "mode": mode}
    for attempt in range(retries + 1):
        try:
            resp = await asyncio.to_thread(requests.get, url, params=params, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # Only return if there’s actual rating data and at least 1 game
                if data.get("rating") is not None and data.get("games", 0) > 0:
                    top_legend_id = None
                    legends = data.get("legends", [])
                    if legends:
                        top = max(legends, key=lambda x: x.get("games", 0))
                        top_legend_id = str(top.get("legend_id"))
                    return {
                        "brawlhalla_id": brawlhalla_id,   # keep ID for verification
                        "rating":        data["rating"],
                        "peak_rating":   data.get("peak_rating", 0),
                        "tier":          data.get("tier", "Unranked"),
                        "wins":          data.get("wins", 0),
                        "games":         data["games"],
                        "top_legend_id": top_legend_id,
                    }
            # If not 200 or no valid data
            if attempt < retries:
                await asyncio.sleep(delay)
        except Exception:
            if attempt < retries:
                await asyncio.sleep(delay)
    return None


async def build_leaderboard(players: list[dict]) -> list[dict]:
    print(f"📋  Building leaderboard for {len(players)} players")

    # Step 1: Quick first pass – 3 retries per player, short delays
    tasks = []
    for p in players:
        tasks.append(fetch_stats_with_retry(p["brawlhalla_id"], mode="ranked_1v1", retries=3, delay=0.8))
        await asyncio.sleep(0.3)   # small delay between spawns to avoid burst
    stats_list = await asyncio.gather(*tasks)

    # Map player -> stats
    player_stats = {}
    missing_players = []
    for player, stats in zip(players, stats_list):
        if stats is not None:
            player_stats[player["brawlhalla_id"]] = stats
            print(f"   ✅ {player['name']}: {stats['rating']} ELO, {stats['tier']}")
        else:
            missing_players.append(player)

    # Step 2: AGGRESSIVE persistent retry loop – up to 100 extra rounds
    max_persistent_retries = 100   # <-- 100 TRIES FOR ABSOLUTE PEACE OF MIND
    if missing_players:
        print(f"🔄  {len(missing_players)} players still missing – will retry up to {max_persistent_retries} times...")
        for attempt in range(1, max_persistent_retries + 1):
            if not missing_players:
                break
            print(f"   --- Round {attempt}/{max_persistent_retries} ---")
            retry_tasks = []
            for p in missing_players:
                # Increase delay each round (1s, 1.5s, 2s …) to be kind to the API
                retry_tasks.append(fetch_stats_with_retry(p["brawlhalla_id"], mode="ranked_1v1", retries=1, delay=0.5 + attempt * 0.1))
                await asyncio.sleep(0.4)
            retry_results = await asyncio.gather(*retry_tasks)

            still_missing = []
            for player, stats in zip(missing_players, retry_results):
                if stats is not None:
                    player_stats[player["brawlhalla_id"]] = stats
                    print(f"      ✅ Recovered {player['name']}: {stats['rating']} ELO")
                else:
                    still_missing.append(player)
            missing_players = still_missing

    # Step 3: Build final enriched list
    enriched = []
    for player in players:
        stats = player_stats.get(player["brawlhalla_id"])
        if stats is None:
            print(f"   ❌ Skipping {player['name']} – no 1v1 data after {max_persistent_retries} extra attempts (likely no placements)")
            continue
        # Safety check
        if stats["brawlhalla_id"] != player["brawlhalla_id"]:
            print(f"   ⚠️  Mismatch for {player['name']} – skipping")
            continue
        enriched.append({
            "display_name":  player["name"],
            "rating":        stats["rating"],
            "peak_rating":   stats["peak_rating"],
            "tier":          stats["tier"],
            "wins":          stats["wins"],
            "games":         stats["games"],
            "top_legend_id": stats["top_legend_id"],
        })

    sorted_board = sorted(enriched, key=lambda p: p["rating"], reverse=True)
    print(f"🏁  Leaderboard built with {len(sorted_board)} players")
    for i, p in enumerate(sorted_board[:3]):
        print(f"   #{i+1}: {p['display_name']} – {p['rating']} ELO, {p['tier']}")
    return sorted_board


# ── Image generation (unchanged) ──────────────────────────────────────

def paste_image(canvas, img, x, y, size):
    img = img.resize(size, Image.LANCZOS)
    if img.mode == "RGBA":
        canvas.paste(img, (x, y), img)
    else:
        canvas.paste(img, (x, y))

def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png", start_rank: int = 1):
    ensure_assets_dir()
    legend_map = load_legend_map()

    ROW_H    = 72
    WIDTH    = 900
    HEADER_H = 75
    HEIGHT   = HEADER_H + len(leaderboard) * ROW_H + 16

    BG       = (14,  18,  32)
    ROW_A    = (21,  27,  48)
    ROW_B    = (17,  22,  40)
    BORDER   = (38,  48,  80)
    MUTED    = (105, 115, 158)
    GOLD     = (255, 195,  40)
    SILVER   = (178, 188, 210)
    BRONZE_C = (192, 122,  52)
    WHITE    = (255, 255, 255)
    GREEN    = ( 68, 200, 138)
    RED      = (255,  95,  95)

    img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    try:
        f_title = ImageFont.truetype("arialbd.ttf", 22)
        f_rank  = ImageFont.truetype("arialbd.ttf", 19)
        f_name  = ImageFont.truetype("arialbd.ttf", 16)
        f_med   = ImageFont.truetype("arial.ttf",   14)
        f_small = ImageFont.truetype("arial.ttf",   12)
    except Exception:
        f_title = f_rank = f_name = f_med = f_small = ImageFont.load_default()

    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=(18, 24, 50))
    draw.text((20, 22), "🏆 Brawlhalla Pakistan Leaderboard", fill=GOLD, font=f_title)

    for label, x in [("#", 18), ("Legend", 68), ("Player", 150), ("ELO / Peak", 480), ("W / L", 640), ("Win%", 780)]:
        draw.text((x, HEADER_H - 17), label, fill=MUTED, font=f_small)

    for i, p in enumerate(leaderboard):
        y      = HEADER_H + i * ROW_H
        row_bg = ROW_A if i % 2 == 0 else ROW_B
        draw.rectangle([(0, y), (WIDTH, y + ROW_H)], fill=row_bg)
        draw.line([(0, y + ROW_H - 1), (WIDTH, y + ROW_H - 1)], fill=BORDER)

        cy = y + ROW_H // 2

        rank_col = GOLD if i == 0 else SILVER if i == 1 else BRONZE_C if i == 2 else MUTED
        draw.text((18, cy - 10), f"#{start_rank + i}", fill=rank_col, font=f_rank)

        legend_name = None
        if p.get("top_legend_id") and legend_map:
            legend_name = legend_map.get(p["top_legend_id"])

        portrait_x, portrait_y = 62, y + 8
        portrait_drawn = False

        if legend_name:
            legend_img = get_legend_image(legend_name)
            if legend_img:
                paste_image(img, legend_img, portrait_x, portrait_y, (56, 56))
                portrait_drawn = True

        if not portrait_drawn:
            draw.rectangle(
                [(portrait_x, portrait_y), (portrait_x + 56, portrait_y + 56)],
                fill=(35, 42, 70), outline=BORDER
            )
            if legend_name:
                abbr = legend_name[:3].upper()
                draw.text((portrait_x + 10, portrait_y + 18), abbr, fill=MUTED, font=f_small)

        t_col = tier_color(p["tier"])
        draw.rectangle(
            [(portrait_x - 3, portrait_y - 3), (portrait_x + 59, portrait_y + 59)],
            outline=t_col, width=3
        )

        draw.text((148, cy - 16), p["display_name"], fill=WHITE, font=f_name)
        draw.text((148, cy + 3),  p["tier"],          fill=t_col, font=f_small)

        if legend_name:
            draw.text((148, cy + 16), legend_name, fill=MUTED, font=f_small)

        draw.text((480, cy - 16), str(p["rating"]),           fill=GREEN, font=f_name)
        draw.text((480, cy + 3),  f"/ {p['peak_rating']} pk", fill=MUTED, font=f_small)

        losses = p["games"] - p["wins"]
        draw.text((640, cy - 8), f"{p['wins']}W", fill=GREEN, font=f_med)
        draw.text((690, cy - 8), "/",             fill=MUTED, font=f_med)
        draw.text((703, cy - 8), f"{losses}L",   fill=RED,   font=f_med)

        wr    = (p["wins"] / p["games"] * 100) if p["games"] > 0 else 0
        wr_c  = GREEN if wr >= 50 else RED
        draw.text((780, cy - 8), f"{wr:.1f}%", fill=wr_c, font=f_med)

    img.save(output_path)
    print(f"✅  Image saved → {output_path}")
    return output_path
