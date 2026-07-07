import requests
import os
import json
import re
import asyncio
import time
from PIL import Image, ImageDraw, ImageFont, ImageOps
from io import BytesIO

BH_API    = "https://api.brawlhalla.com"
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

def tier_key(tier: str):
    for key in TIER_COLORS:
        if tier.startswith(key):
            return key
    return "Unranked"

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

def get_legend_image(legend_name: str) -> Image.Image | None:
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
    print("⬇️   Fetching legend list from Brawlhalla API...")
    try:
        r = requests.get(f"{BH_API}/legends", headers=HEADERS, timeout=10)
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

# ── Ranked stats via headless-browser scrape of Corehalla ────────────────────
#
# Corehalla is a client‑rendered site; we use Playwright (async API) to
# wait for the JavaScript to mount the ranked data.

CH_BASE = "https://corehalla.com"

DEFAULT_STATS = {
    "name": "Unknown", "rating": 0, "peak_rating": 0, "tier": "Unranked",
    "wins": 0, "games": 0, "global_rank": 0, "top_legend_id": None,
}

def parse_corehalla_text(text: str, brawlhalla_id: str) -> dict:
    """
    Extract ranked stats from the page's visible text.
    Now works even if 'Ranked Season' is not present.
    """
    text = re.sub(r"\s+", " ", text)

    # Try to find rating and peak – pattern like "1872 / 1925 Peak"
    rating_match = re.search(r"(\d+)\s*/\s*(\d+)\s*Peak", text)
    if rating_match:
        rating = int(rating_match.group(1))
        peak   = int(rating_match.group(2))
        # Extract tier from the text before the rating
        before = text[:rating_match.start()].strip().split()
        # The last two non-"Ranked"/"Season" words usually form the tier
        tail = [w for w in before[-2:] if w not in ("Ranked", "Season")]
        tier = " ".join(tail) if tail else "Unranked"
    else:
        # Fallback: try to find tier names separately
        rating, peak, tier = 0, 0, "Unranked"
        for known in TIER_COLORS:
            if known in text and known != "Unranked":
                tier = known
                break

    # Wins/Losses – pattern: "123W (45.6%) 456L"
    wins_match = re.search(r"(\d+)W\s*\(\d+\.\d+%\)\s*(\d+)L", text)
    if wins_match:
        wins   = int(wins_match.group(1))
        losses = int(wins_match.group(2))
        games  = wins + losses
    else:
        # Alternative: look for "W" and "L" numbers separately
        w_match = re.search(r"(\d+)W", text)
        l_match = re.search(r"(\d+)L", text)
        if w_match and l_match:
            wins   = int(w_match.group(1))
            losses = int(l_match.group(1))
            games  = wins + losses
        else:
            wins, losses, games = 0, 0, 0

    print(f"🔎  Parsed Corehalla stats for {brawlhalla_id}: tier={tier} rating={rating} peak={peak} wins={wins} games={games}")
    return {
        "name":          "Unknown",
        "rating":        rating,
        "peak_rating":   peak,
        "tier":          tier or "Unranked",
        "wins":          wins,
        "games":         games,
        "global_rank":   0,
        "top_legend_id": None,
    }

async def fetch_all_ranked(brawlhalla_ids: list[str], retries: int = 2) -> dict[str, dict]:
    """
    Opens ONE headless browser and visits every player's Corehalla page.
    Returns {brawlhalla_id: stats_dict}.
    """
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    results: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()

        for bh_id in brawlhalla_ids:
            url = f"{CH_BASE}/stats/player/{bh_id}"
            stats = None

            for attempt in range(retries):
                try:
                    # Wait for full network idle – React has finished loading
                    await page.goto(url, timeout=30000, wait_until="networkidle")

                    # Give a bit more time for the stats to populate after hydration
                    await page.wait_for_timeout(1500)

                    # Optionally, wait for a specific element that we know appears
                    try:
                        await page.wait_for_selector(".ranked-stats", timeout=5000)
                    except PWTimeout:
                        pass  # not critical, we'll parse the whole body anyway

                    visible_text = await page.inner_text("body")
                    # Debug snippet (will show in logs)
                    print(f"DEBUG: visible_text[:200] for {bh_id} = {visible_text[:200]}")

                    stats = parse_corehalla_text(visible_text, bh_id)
                    break

                except Exception as e:
                    print(f"⚠️  Browser fetch issue for ID {bh_id} (attempt {attempt+1}/{retries}): {e}")
                    await asyncio.sleep(1.5)

            results[bh_id] = stats or dict(DEFAULT_STATS)

        await browser.close()

    return results

async def build_leaderboard(players: list[dict]) -> list[dict]:
    ids = [p["brawlhalla_id"] for p in players]
    stats_map = await fetch_all_ranked(ids)

    enriched = []
    for player in players:
        stats = stats_map.get(player["brawlhalla_id"], DEFAULT_STATS)
        enriched.append({
            **player,
            "display_name":  player["name"],
            "rating":        stats["rating"],
            "peak_rating":   stats["peak_rating"],
            "tier":          stats["tier"],
            "wins":          stats["wins"],
            "games":         stats["games"],
            "global_rank":   stats["global_rank"],
            "top_legend_id": stats["top_legend_id"],
        })
    return sorted(enriched, key=lambda p: p["rating"], reverse=True)

# ── Image Generation ──────────────────────────────────────────────────────────

def paste_image(canvas: Image.Image, img: Image.Image, x: int, y: int, size: tuple):
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
    draw.text((20, 22), "🏆 Brawlhalla Leaderboard", fill=GOLD, font=f_title)

    for label, x in [("#", 18), ("Legend", 68), ("Player", 150), ("ELO / Peak", 480), ("W / L", 640), ("Win%", 780)]:
        draw.text((x, HEADER_H - 17), label, fill=MUTED, font=f_small)

    for i, p in enumerate(leaderboard):
        y      = HEADER_H + i * ROW_H
        row_bg = ROW_A if i % 2 == 0 else ROW_B
        draw.rectangle([(0, y), (WIDTH, y + ROW_H)], fill=row_bg)
        draw.line([(0, y + ROW_H - 1), (WIDTH, y + ROW_H - 1)], fill=BORDER)

        cy = y + ROW_H // 2

        actual_rank = start_rank + i
        rank_col = GOLD if actual_rank == 1 else SILVER if actual_rank == 2 else BRONZE_C if actual_rank == 3 else MUTED
        draw.text((18, cy - 10), f"#{actual_rank}", fill=rank_col, font=f_rank)

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

        draw.text((148, cy - 16), p["display_name"], fill=WHITE,  font=f_name)
        draw.text((148, cy +  3), p["tier"],          fill=t_col, font=f_small)
        if legend_name:
            draw.text((148, cy + 16), legend_name, fill=MUTED, font=f_small)

        draw.text((480, cy - 16), str(p["rating"]),            fill=GREEN, font=f_name)
        draw.text((480, cy +  3), f"/ {p['peak_rating']} pk",  fill=MUTED, font=f_small)

        losses = p["games"] - p["wins"]
        draw.text((640, cy - 8), f"{p['wins']}W", fill=GREEN, font=f_med)
        draw.text((690, cy - 8), "/",             fill=MUTED, font=f_med)
        draw.text((703, cy - 8), f"{losses}L",    fill=RED,   font=f_med)

        wr   = (p["wins"] / p["games"] * 100) if p["games"] > 0 else 0
        draw.text((780, cy - 8), f"{wr:.1f}%", fill=GREEN if wr >= 50 else RED, font=f_med)

    img.save(output_path)
    print(f"✅  Image saved → {output_path}")
    return output_path
