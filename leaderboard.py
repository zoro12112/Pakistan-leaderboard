import requests
import os
import json
import re
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

# ── Ranked stats via headless-browser scrape of Corehalla ────────────────────
#
# Corehalla is a client-rendered site (React/Next.js): the numbers you see in
# a real browser are injected by JavaScript *after* the page loads. A plain
# requests.get() only ever downloads the empty pre-JS shell, which is why
# every player used to come back as 0/Unranked no matter what the regex was.
# Playwright runs a real (headless) Chromium, lets that JS execute, and only
# then reads the page — so this reads the same DOM a human would see.

CH_BASE = "https://corehalla.com"

DEFAULT_STATS = {
    "name": "Unknown", "rating": 0, "peak_rating": 0, "tier": "Unranked",
    "wins": 0, "games": 0, "global_rank": 0, "top_legend_id": None,
}

def parse_corehalla_text(text: str, brawlhalla_id: str) -> dict:
    """Given the fully-rendered page's visible text, pull out ranked stats."""
    text = re.sub(r"\s+", " ", text)

    if "Ranked Season" not in text:
        print(f"⚠️  No ranked section found for ID {brawlhalla_id} — treating as Unranked")
        return dict(DEFAULT_STATS)

    rating_match = re.search(r"(\d+)/\s*(\d+)Peak", text)
    if rating_match:
        rating = int(rating_match.group(1))
        peak   = int(rating_match.group(2))
        before = text[:rating_match.start()].strip().split()
        tail   = [w for w in before[-2:] if w not in ("Ranked", "Season")]
        tier   = " ".join(tail) if tail else "Unranked"
    else:
        rating, peak, tier = 0, 0, "Unranked"

    wins_match = re.search(r"(\d+)W \(\d+\.\d+%\)(\d+)L", text)
    wins   = int(wins_match.group(1)) if wins_match else 0
    losses = int(wins_match.group(2)) if wins_match else 0
    games  = wins + losses

    print(f"🔎  Parsed Corehalla stats for {brawlhalla_id}: tier={tier} rating={rating} peak={peak} wins={wins} games={games}")

    return {
        "name":          "Unknown",  # Corehalla doesn't expose the name cleanly near stats; players.json name is used instead
        "rating":        rating,
        "peak_rating":   peak,
        "tier":          tier or "Unranked",
        "wins":          wins,
        "games":         games,
        "global_rank":   0,
        "top_legend_id": None,
    }

def fetch_all_ranked(brawlhalla_ids: list[str], retries: int = 2) -> dict[str, dict]:
    """
    Opens ONE headless browser and visits every player's Corehalla page with it,
    instead of launching a new browser per player (which would be extremely slow).
    Returns {brawlhalla_id: stats_dict}.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    results: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        for bh_id in brawlhalla_ids:
            url = f"{CH_BASE}/stats/player/{bh_id}"
            stats = None

            for attempt in range(retries):
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")

                    # Wait until the client-side JS has actually mounted the
                    # ranked section, instead of trusting a fixed sleep.
                    try:
                        page.wait_for_selector("text=Ranked Season", timeout=15000)
                        # Small extra buffer for the numbers themselves to populate
                        # after the section mounts (they can lag the label by a beat).
                        page.wait_for_timeout(800)
                    except PWTimeout:
                        # Section never showed up — page rendered, just no ranked data.
                        pass

                    visible_text = page.inner_text("body")
                    stats = parse_corehalla_text(visible_text, bh_id)
                    break

                except Exception as e:
                    print(f"⚠️  Browser fetch issue for ID {bh_id} (attempt {attempt+1}/{retries}): {e}")
                    time.sleep(1.5)

            results[bh_id] = stats or dict(DEFAULT_STATS)

        browser.close()

    return results

def build_leaderboard(players: list[dict]) -> list[dict]:
    ids = [p["brawlhalla_id"] for p in players]
    stats_map = fetch_all_ranked(ids)

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
