import requests
import os
import json
import time
from PIL import Image, ImageDraw, ImageFont, ImageOps
from io import BytesIO

BH_API    = "https://api.brawlhalla.com"  # kept for load_legend_map only
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

# ── ELO Fetching with retries ─────────────────────────────────────────────────

import re

CH_BASE = "https://corehalla.com"

def fetch_ranked(brawlhalla_id: str, retries: int = 3, delay: float = 2.0) -> dict | None:
    """
    Scrapes corehalla.com's public player page instead of calling Brawlhalla's
    official API (which requires a key we don't have). No login/key needed,
    but this depends on Corehalla's page layout staying the same.
    """
    url = f"{CH_BASE}/stats/player/{brawlhalla_id}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)

            if r.status_code in (500, 502, 503, 504):
                print(f"⚠️  Corehalla error {r.status_code} for ID {brawlhalla_id} (attempt {attempt+1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                return None

            if r.status_code != 200:
                print(f"❌  Corehalla fetch failed for ID {brawlhalla_id}: {r.status_code}")
                return None

            html = r.text
            text = re.sub(r"<[^>]+>", " ", html)   # crude tag-strip, good enough for regex anchors
            text = re.sub(r"\s+", " ", text)

            # If the page has no ranked season section rendered at all, treat as unranked
            if "Ranked Season" not in text:
                print(f"⚠️  No ranked section found for ID {brawlhalla_id} — treating as Unranked")
                return {
                    "name": "Unknown", "rating": 0, "peak_rating": 0, "tier": "Unranked",
                    "wins": 0, "games": 0, "global_rank": 0, "top_legend_id": None,
                }

            def grab(pattern, default=None, cast=str):
                m = re.search(pattern, text)
                if not m:
                    return default
                try:
                    return cast(m.group(1))
                except (ValueError, TypeError):
                    return default

            rating_match = re.search(r"(\d+)/\s*(\d+)Peak", text)
            if rating_match:
                rating = int(rating_match.group(1))
                peak   = int(rating_match.group(2))
                before = text[:rating_match.start()].strip().split()
                tail   = [w for w in before[-2:] if w not in ("Ranked", "Season")]
                tier   = " ".join(tail) if tail else "Unranked"
            else:
                rating, peak, tier = 0, 0, "Unranked"

            wins    = grab(r"(\d+)W \(\d+\.\d+%\)\d+L", 0, int)
            losses  = grab(r"\d+W \(\d+\.\d+%\)(\d+)L", 0, int)
            games   = (wins or 0) + (losses or 0)

            print(f"🔎  Parsed Corehalla stats for {brawlhalla_id}: tier={tier} rating={rating} peak={peak} wins={wins} games={games}")

            return {
                "name":          "Unknown",   # Corehalla page doesn't cleanly expose the name near stats; keep players.json name
                "rating":        rating or 0,
                "peak_rating":   peak or 0,
                "tier":          tier or "Unranked",
                "wins":          wins or 0,
                "games":         games or 0,
                "global_rank":   0,
                "top_legend_id": None,
            }

        except requests.RequestException as e:
            print(f"⚠️  Request error for ID {brawlhalla_id} (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print(f"❌  All retries failed for ID {brawlhalla_id}")
                return None

def build_leaderboard(players: list[dict]) -> list[dict]:
    enriched = []
    for player in players:
        stats = fetch_ranked(player["brawlhalla_id"])
        enriched.append({
            **player,
            "display_name":  player["name"],
            "rating":        stats["rating"]         if stats else 0,
            "peak_rating":   stats["peak_rating"]    if stats else 0,
            "tier":          stats["tier"]           if stats else "Unranked",
            "wins":          stats["wins"]           if stats else 0,
            "games":         stats["games"]          if stats else 0,
            "global_rank":   stats["global_rank"]    if stats else 0,
            "top_legend_id": stats["top_legend_id"]  if stats else None,
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
