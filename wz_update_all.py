"""
BuitKing's Loadout Updater - v9 (GitHub Actions)
==================================================
1. Scrapet warzoneloadout.games (WZ Meta) via Playwright
2. Scrapet wzhub.gg/loadouts (WZHUB Meta) via Playwright
3. Update index.html

Als een scraper 0 resultaten geeft => bestaande data in HTML behouden (geen abort).
"""

import sys, os, json, logging, datetime, re

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HTML_PATH    = r"D:\Documenten\GitHub\buitking-loadouts\index.html"
LOG_PATH     = r"D:\Documenten\GitHub\buitking-loadouts\buitking_update.log"
WZ_URL       = "https://warzoneloadout.games/warzone-meta/"
WZHUB_URL    = "https://wzhub.gg/loadouts"
PLAYLIST_URL = "https://wzhub.gg/playlist/wz"

logging.basicConfig(
    filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
def log(msg, level="info"):
    print(msg)
    getattr(logging, level)(msg)

def ensure_deps():
    pkgs = []
    try: import requests
    except ImportError: pkgs.append("requests")
    try: import bs4
    except ImportError: pkgs.append("beautifulsoup4")
    if pkgs:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + pkgs + ["--quiet"])

ensure_deps()
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
}

PLAYWRIGHT_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]
PLAYWRIGHT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def fetch_with_playwright(url, wait_ms=4000, timeout_ms=90000, retries=2):
    from playwright.sync_api import sync_playwright
    for attempt in range(1, retries + 1):
        try:
            log(f"  Browser openen: {url} (poging {attempt})")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
                ctx = browser.new_context(
                    user_agent=PLAYWRIGHT_UA,
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={"Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8"},
                )
                page = ctx.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                page.wait_for_timeout(wait_ms)
                html = page.content()
                browser.close()
            log(f"  Geladen, len={len(html)}")
            return html
        except Exception as e:
            log(f"  [FOUT] Playwright poging {attempt}: {e}", "warning")
    return None


# === WZ META ===
TIER_MAP = {
    "absolute meta": "S", "meta warzone": "A",
    "contender": "B", "average": "C", "weak": "D",
}
SLOT_NORMALIZE = {
    "muzzle":"Muzzle","barrel":"Barrel","underbarrel":"Underbarrel",
    "laser":"Laser","ammunition":"Ammunition","magazine":"Magazine",
    "optic":"Optic","stock":"Stock","rear grip":"Rear Grip",
    "fire mods":"Fire Mods","fire mod":"Fire Mods",
    "trigger":"Trigger","comb":"Comb","combo":"Combo",
}

def get_tier(text):
    tl = text.lower()
    for k, v in TIER_MAP.items():
        if k in tl: return v
    return "?"

def get_slot(line):
    return SLOT_NORMALIZE.get(line.strip().lower())

def is_junk(line):
    l = line.strip()
    return (not l or l.startswith("Updated:") or re.match(r"#\d+", l)
            or l.lower() in ("bo7","bo6","mw3","mw2","warzone")
            or "Best Loadout" in l or "Open accordion" in l
            or "copyright" in l.lower() or l.startswith("http")
            or bool(re.search(r"\d+\s*Attachments?", l, re.I)))

def parse_build_pairs(lines, weapon_name):
    atts = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        slot = get_slot(line)
        if slot:
            j = i + 1
            while j < len(lines) and is_junk(lines[j]):
                j += 1
            if j < len(lines):
                val = lines[j].strip()
                if val and val != weapon_name and not get_slot(val) and not is_junk(val):
                    atts[slot] = val
                    i = j + 1
                    continue
        i += 1
    return atts

def scrape_wz_meta():
    html = fetch_with_playwright(WZ_URL, wait_ms=6000)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    all_weapons = {}
    current_tier = "?"
    seen = set()
    for el in soup.find_all(["h2","li"]):
        if el.name == "h2":
            current_tier = get_tier(el.get_text())
            continue
        h3 = el.find("h3")
        if not h3: continue
        name = h3.get_text(strip=True)
        if not name or len(name) < 2: continue
        labels = []
        for ul in el.find_all("ul"):
            for item in ul.find_all("li"):
                t = item.get_text(strip=True)
                if "ttachment" in t:
                    label = re.sub(r'\s*-?\s*\d+\s*Attachments?', '', t, flags=re.I).strip()
                    if label: labels.append(label)
        text = el.get_text(separator="\n")
        raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
        chunks, cur = [], []
        for line in raw_lines:
            if line.startswith("Updated:"):
                if cur: chunks.append(cur); cur = []
            else:
                cur.append(line)
        if cur: chunks.append(cur)
        builds = []
        for ci, chunk in enumerate(chunks):
            label = labels[ci] if ci < len(labels) else f"Build {ci+1}"
            atts = parse_build_pairs(chunk, name)
            if atts:
                builds.append({"label": label, "attachments": atts, "note": "", "rank": ""})
        if builds and current_tier in ("S","A") and name not in seen:
            seen.add(name)
            all_weapons[name] = {"tier": current_tier, "builds": builds}
            log(f"    + {name} ({current_tier})")
    log(f"  Totaal: {len(all_weapons)} wapens")
    return all_weapons


# === WZHUB ===
WZHUB_TIER_MAP = {"absolute meta": "S", "meta": "A"}
WZHUB_SLOT_NORMALIZE = {
    "muzzle":"Muzzle","barrel":"Barrel","underbarrel":"Underbarrel",
    "laser":"Laser","ammunition":"Ammunition","magazine":"Magazine",
    "optic":"Optic","stock":"Stock","rear grip":"Rear Grip",
    "fire mods":"Fire Mods","fire mod":"Fire Mods",
    "trigger":"Trigger","comb":"Comb","combo":"Combo",
}

def parse_wzhub_atts(lines):
    atts = {}
    i = 0
    while i < len(lines) - 1:
        current = lines[i].strip()
        next_l  = lines[i + 1]
        if next_l.startswith(" ") and next_l.strip().lower() in WZHUB_SLOT_NORMALIZE:
            slot = WZHUB_SLOT_NORMALIZE[next_l.strip().lower()]
            atts[slot] = current.title()
            i += 2
        else:
            i += 1
    return atts

def scrape_wzhub():
    html = fetch_with_playwright(WZHUB_URL, wait_ms=8000, timeout_ms=90000, retries=2)
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    all_weapons = {}
    current_tier = "?"
    for el in soup.find_all(["h2","a"]):
        if el.name == "h2":
            t = el.get_text(strip=True).lower()
            current_tier = WZHUB_TIER_MAP.get(t, "?")
            continue
        if el.name != "a": continue
        href = el.get("href", "")
        if not href.startswith("/loadouts/bo7-"): continue
        if current_tier not in ("S","A"): continue
        name = el.get_text(strip=True)
        if not name or len(name) < 2: continue
        parent = el.find_parent()
        if not parent: continue
        text = parent.get_text(separator="\n")
        lines = text.split("\n")
        build_code = ""
        for i, line in enumerate(lines):
            if "loadout code" in line.lower() and i + 1 < len(lines):
                candidate = lines[i+1].strip()
                if re.match(r"^[A-Z0-9][0-9]{2}-", candidate):
                    build_code = candidate
                break
        atts = parse_wzhub_atts(lines)
        if not atts: continue
        entry = {"tier": current_tier, "build_code": build_code, "attachments": atts}
        if name not in all_weapons:
            all_weapons[name] = entry
            log(f"    + {name} ({current_tier})")
        elif current_tier == "S" and all_weapons[name]["tier"] == "A":
            all_weapons[name] = entry
    log(f"  Totaal: {len(all_weapons)} wapens van wzhub.gg")
    return all_weapons


# === HTML UPDATE ===
WZ_START    = "/* WZ_META_START */"
WZ_END      = "/* WZ_META_END */"
WZHUB_START = "/* WZHUB_META_START */"
WZHUB_END   = "/* WZHUB_META_END */"

def replace_between(content, start, end, new_code):
    si = content.find(start)
    ei = content.find(end, si)
    if si == -1 or ei == -1:
        return content, 0
    replacement = f'{start}\n  {new_code}\n  {end}'
    return content[:si] + replacement + content[ei + len(end):], 1

def update_html(path, wz_meta, wzhub_data):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if WZ_START not in content or WZHUB_START not in content:
        log("FOUT: markers niet gevonden in HTML", "error")
        raise ValueError("Markers ontbreken")
    if wz_meta:
        content, _ = replace_between(content, WZ_START, WZ_END,
                                     f'const WZ_META = {json.dumps(wz_meta, ensure_ascii=False)};')
        log(f"  WZ Meta: {len(wz_meta)} wapens bijgewerkt")
    else:
        log("  [WAARSCHUWING] WZ Meta leeg — bestaande data behouden", "warning")
    if wzhub_data:
        content, _ = replace_between(content, WZHUB_START, WZHUB_END,
                                     f'const WZHUB_META = {json.dumps(wzhub_data, ensure_ascii=False)};')
        log(f"  WZHUB: {len(wzhub_data)} wapens bijgewerkt")
    else:
        log("  [WAARSCHUWING] WZHUB leeg — bestaande data behouden", "warning")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# === MAIN ===
def run():
    now       = datetime.datetime.now()
    timestamp = now.strftime('%d/%m/%Y %H:%M')
    log("=" * 55)
    log("BuitKing's Loadout Updater gestart (v9)")
    log(f"Datum: {timestamp}")

    if not os.path.exists(HTML_PATH):
        log(f"FOUT: HTML niet gevonden: {HTML_PATH}", "error")
        sys.exit(1)

    log("\n[1/2] WZ Meta scrapen (warzoneloadout.games)...")
    try:
        wz_meta = scrape_wz_meta()
        log(f"      OK: {len(wz_meta)} wapens")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); wz_meta = {}

    log("\n[2/2] WZHUB Meta scrapen (wzhub.gg)...")
    try:
        wzhub_data = scrape_wzhub()
        log(f"      OK: {len(wzhub_data)} wapens")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); wzhub_data = {}

    log("\n[3/3] HTML updaten...")
    try:
        update_html(HTML_PATH, wz_meta, wzhub_data)
        log(f"      OK: Bijgewerkt op {timestamp}")
    except Exception as e:
        log(f"      FOUT: {e}", "error"); sys.exit(1)

    log("\nBuitKing's Loadouts bijgewerkt!")
    log("=" * 55)

if __name__ == "__main__":
    run()
