import requests
import os
import json
import time
from PIL import Image, ImageDraw, ImageFont, ImageOps
from io import BytesIO

BH_API    = "https://api.brawlhalla.com/v1"
ASSETS    = "assets"   # local cache folder
ASSETS    = "assets"
HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Tier colours (fallback if images fail) ────────────────────────────────────
TIER_COLORS = {
    "Valhallan": (220,  80,  80),
    "Diamond":   ( 80, 210, 255),
@@ -34,8 +32,6 @@ def tier_key(tier: str):
            return key
    return "Unranked"

# ── Asset downloading ─────────────────────────────────────────────────────────

def ensure_assets_dir():
    os.makedirs(f"{ASSETS}/legends", exist_ok=True)

@@ -51,11 +47,9 @@ def download_image(url: str, save_path: str) -> bool:
        return False

def get_legend_image(legend_name: str) -> Image.Image | None:
    """Download and cache legend portrait."""
    safe_name = legend_name.lower().replace(" ", "_").replace("'", "")
    path      = f"{ASSETS}/legends/{safe_name}.png"
    if not os.path.exists(path):
        # Try multiple sources
        sources = [
            f"https://corehalla.com/images/legends/{legend_name}.png",
            f"https://corehalla.com/images/legends/{legend_name.lower()}.png",
@@ -71,12 +65,9 @@ def get_legend_image(legend_name: str) -> Image.Image | None:
            pass
    return None

# ── Legend ID → Name map ──────────────────────────────────────────────────────

LEGEND_CACHE_PATH = f"{ASSETS}/legends_map.json"

def load_legend_map() -> dict:
    """Fetch legend list from Brawlhalla API and cache it."""
    ensure_assets_dir()
    if os.path.exists(LEGEND_CACHE_PATH):
        with open(LEGEND_CACHE_PATH) as f:
@@ -95,37 +86,80 @@ def load_legend_map() -> dict:
        print(f"⚠️  Could not fetch legends: {e}")
        return {}

# ── ELO Fetching ──────────────────────────────────────────────────────────────
# ── ELO Fetching with retries ─────────────────────────────────────────────────

def fetch_ranked(brawlhalla_id: str) -> dict | None:
    url    = f"{BH_API}/player/stats"
    params = {"brawlhalla_id": brawlhalla_id, "mode": "ranked_1v1"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if "rating" not in data:
            return None

        # Find most-played legend this season
        top_legend_id = None
        if data.get("legends"):
            top = max(data["legends"], key=lambda x: x["games"])
            top_legend_id = str(top["legend_id"])

        return {
            "name":          data.get("name", "Unknown"),
            "rating":        data.get("rating", 0),
            "peak_rating":   data.get("peak_rating", 0),
            "tier":          data.get("tier", "Unranked"),
            "wins":          data.get("wins", 0),
            "games":         data.get("games", 0),
            "global_rank":   data.get("global_rank", 0),
            "top_legend_id": top_legend_id,
        }
    except requests.RequestException as e:
        print(f"❌  Fetch failed for ID {brawlhalla_id}: {e}")
        return None
def fetch_ranked(brawlhalla_id: str, retries: int = 3, delay: float = 2.0) -> dict | None:
    for attempt in range(retries):
        try:
            # Try ranked_1v1 first
            r = requests.get(f"{BH_API}/player/stats",
                            params={"brawlhalla_id": brawlhalla_id, "mode": "ranked_1v1"},
                            timeout=10)

            if r.status_code in (500, 502, 503, 504):
                print(f"⚠️  API error {r.status_code} for ID {brawlhalla_id} (attempt {attempt+1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(delay)
                    continue
                return None

            if r.status_code == 200 and "rating" in r.json():
                data = r.json()
            else:
                # Fallback: general stats
                r2 = requests.get(f"{BH_API}/player/stats",
                                params={"brawlhalla_id": brawlhalla_id},
                                timeout=10)

                if r2.status_code in (500, 502, 503, 504):
                    print(f"⚠️  API error {r2.status_code} for ID {brawlhalla_id} (attempt {attempt+1}/{retries})")
                    if attempt < retries - 1:
                        time.sleep(delay)
                        continue
                    return None

                if r2.status_code != 200:
                    print(f"❌  Fetch failed for ID {brawlhalla_id}: {r2.status_code}")
                    return None

                data = r2.json()
                ranked_legends = [l for l in data.get("legends", []) if "rating" in l]
                if not ranked_legends:
                    print(f"⚠️  No ranked data for ID {brawlhalla_id}")
                    return None

                best = max(ranked_legends, key=lambda x: x["rating"])
                data["rating"]      = best["rating"]
                data["peak_rating"] = best.get("peak_rating", best["rating"])
                data["tier"]        = best.get("tier", "Unranked")
                data["wins"]        = data.get("wins", 0)
                data["games"]       = data.get("games", 0)

            top_legend_id = None
            if data.get("legends"):
                ranked_legends = [l for l in data["legends"] if "rating" in l]
                if ranked_legends:
                    top = max(ranked_legends, key=lambda x: x["games"])
                    top_legend_id = str(top["legend_id"])

            return {
                "name":          data.get("name", "Unknown"),
                "rating":        data.get("rating", 0),
                "peak_rating":   data.get("peak_rating", 0),
                "tier":          data.get("tier", "Unranked"),
                "wins":          data.get("wins", 0),
                "games":         data.get("games", 0),
                "global_rank":   data.get("global_rank", 0),
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
@@ -147,14 +181,13 @@ def build_leaderboard(players: list[dict]) -> list[dict]:
# ── Image Generation ──────────────────────────────────────────────────────────

def paste_image(canvas: Image.Image, img: Image.Image, x: int, y: int, size: tuple):
    """Resize and paste an RGBA image onto canvas."""
    img = img.resize(size, Image.LANCZOS)
    if img.mode == "RGBA":
        canvas.paste(img, (x, y), img)
    else:
        canvas.paste(img, (x, y))

def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"):
def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png", start_rank: int = 1):
    ensure_assets_dir()
    legend_map = load_legend_map()

@@ -167,7 +200,6 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"
    ROW_A    = (21,  27,  48)
    ROW_B    = (17,  22,  40)
    BORDER   = (38,  48,  80)
    TEXT     = (220, 225, 255)
    MUTED    = (105, 115, 158)
    GOLD     = (255, 195,  40)
    SILVER   = (178, 188, 210)
@@ -179,7 +211,6 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"
    img  = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Fonts
    try:
        f_title = ImageFont.truetype("arialbd.ttf", 22)
        f_rank  = ImageFont.truetype("arialbd.ttf", 19)
@@ -189,11 +220,9 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"
    except Exception:
        f_title = f_rank = f_name = f_med = f_small = ImageFont.load_default()

    # Header
    draw.rectangle([(0, 0), (WIDTH, HEADER_H)], fill=(18, 24, 50))
    draw.text((20, 22), "🏆 Brawlhalla Pakistan Leaderboard", fill=GOLD, font=f_title)
    draw.text((20, 22), "🏆 Brawlhalla Leaderboard", fill=GOLD, font=f_title)

    # Column headers
    for label, x in [("#", 18), ("Legend", 68), ("Player", 150), ("ELO / Peak", 480), ("W / L", 640), ("Win%", 780)]:
        draw.text((x, HEADER_H - 17), label, fill=MUTED, font=f_small)

@@ -205,11 +234,10 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"

        cy = y + ROW_H // 2

        # ── Rank ──────────────────────────────────────────────────────────────
        rank_col = GOLD if i == 0 else SILVER if i == 1 else BRONZE_C if i == 2 else MUTED
        draw.text((18, cy - 10), f"#{i+1}", fill=rank_col, font=f_rank)
        actual_rank = start_rank + i
        rank_col = GOLD if actual_rank == 1 else SILVER if actual_rank == 2 else BRONZE_C if actual_rank == 3 else MUTED
        draw.text((18, cy - 10), f"#{actual_rank}", fill=rank_col, font=f_rank)

        # ── Legend portrait (56x56) ───────────────────────────────────────────
        legend_name = None
        if p.get("top_legend_id") and legend_map:
            legend_name = legend_map.get(p["top_legend_id"])
@@ -224,7 +252,6 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"
                portrait_drawn = True

        if not portrait_drawn:
            # Grey placeholder box
            draw.rectangle(
                [(portrait_x, portrait_y), (portrait_x + 56, portrait_y + 56)],
                fill=(35, 42, 70), outline=BORDER
@@ -233,38 +260,28 @@ def generate_image(leaderboard: list[dict], output_path: str = "leaderboard.png"
                abbr = legend_name[:3].upper()
                draw.text((portrait_x + 10, portrait_y + 18), abbr, fill=MUTED, font=f_small)

        # ── Tier frame overlay on portrait (56x56) - Using colored border only ──
        # Coloured border for tier
        t_col = tier_color(p["tier"])
        draw.rectangle(
            [(portrait_x - 3, portrait_y - 3), (portrait_x + 59, portrait_y + 59)],
            outline=t_col, width=3
        )

        # ── Player name + tier label ──────────────────────────────────────────
        draw.text((148, cy - 16), p["display_name"], fill=WHITE, font=f_name)
        t_col = tier_color(p["tier"])
        draw.text((148, cy + 3),  p["tier"],          fill=t_col, font=f_small)

        # Legend name below tier
        draw.text((148, cy - 16), p["display_name"], fill=WHITE,  font=f_name)
        draw.text((148, cy +  3), p["tier"],          fill=t_col, font=f_small)
        if legend_name:
            draw.text((148, cy + 16), legend_name, fill=MUTED, font=f_small)

        # ── ELO / Peak ────────────────────────────────────────────────────────
        draw.text((480, cy - 16), str(p["rating"]),           fill=GREEN, font=f_name)
        draw.text((480, cy + 3),  f"/ {p['peak_rating']} pk", fill=MUTED, font=f_small)
        draw.text((480, cy - 16), str(p["rating"]),            fill=GREEN, font=f_name)
        draw.text((480, cy +  3), f"/ {p['peak_rating']} pk",  fill=MUTED, font=f_small)

        # ── W / L ─────────────────────────────────────────────────────────────
        losses = p["games"] - p["wins"]
        draw.text((640, cy - 8), f"{p['wins']}W", fill=GREEN, font=f_med)
        draw.text((690, cy - 8), "/",             fill=MUTED, font=f_med)
        draw.text((703, cy - 8), f"{losses}L",   fill=RED,   font=f_med)
        draw.text((703, cy - 8), f"{losses}L",    fill=RED,   font=f_med)

        # ── Win rate ──────────────────────────────────────────────────────────
        wr    = (p["wins"] / p["games"] * 100) if p["games"] > 0 else 0
        wr_c  = GREEN if wr >= 50 else RED
        draw.text((780, cy - 8), f"{wr:.1f}%", fill=wr_c, font=f_med)
        wr   = (p["wins"] / p["games"] * 100) if p["games"] > 0 else 0
        draw.text((780, cy - 8), f"{wr:.1f}%", fill=GREEN if wr >= 50 else RED, font=f_med)

    img.save(output_path)
    print(f"✅  Image saved → {output_path}")
    return output_path
    return output_path
