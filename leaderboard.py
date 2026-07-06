import requests
import os
import json
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

# ── ELO Fetching with retries ─────────────────────────────────────────────────

def fetch_ranked(brawlhalla_id: str, retries: int = 3, delay: float = 2.0) -> dict | None:
    for attempt in range(retries):
        try:
            # Ranked data (rating, peak, tier, region, global_rank) lives on
            # /player/{id}/ranked — NOT /player/stats?brawlhalla_id=
            r = requests.get(f"{BH_API}/player/{brawlhalla_id}/ranked", headers=HEADERS, timeout=10)

            if r.status_code in (500, 502, 503, 504):
                print(f"⚠️  API error {r.status_code} for ID {brawlhalla_id} (attempt {attempt+1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                return None

            if r.status_code != 200:
                # DEBUG: print the raw body so we can see exactly what the API said
                print(f"❌  /ranked fetch failed for ID {brawlhalla_id}: {r.status_code} — {r.text[:200]}")
                return None

            ranked_data = r.json()
            # DEBUG: show exactly what the API returned
            print(f"🔎  Raw /ranked response for {brawlhalla_id}: {ranked_data}")

            games = ranked_data.get("games", 0)
            wins  = ranked_data.get("wins", 0)

            r2 = requests.get(f"{BH_API}/player/{brawlhalla_id}/stats", headers=HEADERS, timeout=10)
            if r2.status_code == 200:
                stats_data = r2.json()
                games = stats_data.get("games", games)
                wins  = stats_data.get("wins", wins)
            else:
                print(f"⚠️  /stats fetch failed for ID {brawlhalla_id}: {r2.status_code} — {r2.text[:200]}")

            top_legend_id = None
            legends = ranked_data.get("legends", [])
            if legends:
                top = max(legends, key=lambda x: x.get("games", 0))
                top_legend_id = str(top.get("legend_id"))

            return {
                "name":          ranked_data.get("name", "Unknown"),
                "rating":        ranked_data.get("rating", 0),
                "peak_rating":   ranked_data.get("peak_rating", 0),
                "tier":          ranked_data.get("tier", "Unranked"),
                "wins":          wins,
                "games":         games,
                "global_rank":   ranked_data.get("global_rank", 0),
                "top_legend_id": top_legend_id,
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
            "display_name":  stats["name"]          if stats else player["name"],
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
