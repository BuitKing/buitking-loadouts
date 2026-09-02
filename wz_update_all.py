"""
BuitKing's Loadout Updater - v10 (GitHub Actions)
==================================================
Correct gebaseerd op echte HTML structuur van wzhub.gg en warzoneloadout.games
"""

import sys, os, json, logging, datetime, re

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HTML_PATH    = os.path.join(SCRIPT_DIR, "index.html")
LOG_PATH     = os.path.join(SCRIPT_DIR, "buitking_update.log")
WZ_URL       = "https://warzoneloadout.games/warzone-meta/"
WZHUB_URL    = "https://wzhub.gg/loadouts"

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
    try: import bs4
    except ImportError: pkgs.append("beautifulsoup4")
    if pkgs:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + pkgs + ["--quiet"])

ensure_deps()
from bs4 import BeautifulSoup

PLAYWRIGHT_ARGS = ["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SLOT_NAMES_CAP = {"Muzzle","Barrel","Underbarrel","Optic","Stock","Magazine","Laser","Rear Grip","Fire Mods","Trigger","Comb","Combo","Ammunition"}
SLOT_NAMES = {"muzzle","barrel","underbarrel","optic","stock","magazine","laser","rear grip","fire mods","trigger","comb","combo","ammunition"}
SLOT_NORMALIZE = {
    "muzzle":"Muzzle","barrel":"Barrel","underbarrel":"Underbarrel",
    "laser":"Laser","ammunition":"Ammunition","magazine":"Magazine",
    "optic":"Optic","stock":"Stock","rear grip":"Rear Grip",
    "fire mods":"Fire Mods","fire mod":"Fire Mods",
    "trigger":"Trigger","comb":"Comb","combo":"Combo",
}

def fetch_playwright(url, wait_ms=5000, js_click=None):
    from playwright.sync_api import sync_playwright
    for attempt in range(1, 3):
        try:
            log(f"  Browser: {url} (poging {attempt})")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
                ctx = browser.new_context(user_agent=UA, viewport={"width":1280,"height":800})
                page = ctx.new_page()
                page.goto(url, timeout=90000, wait_until="networkidle")
                page.wait_for_timeout(wait_ms)
                # Scroll door de pagina voor lazy loading
                for _ in range(15):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(250)
                page.wait_for_timeout(1500)
                if js_click:
                    clicked = page.evaluate(js_click)
                    log(f"  JS geklikt: {clicked}")
                    page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
            log(f"  Geladen len={len(html)}")
            return html
        except Exception as e:
            log(f"  [FOUT] poging {attempt}: {e}", "warning")
    return None


# ══════════════════════════════════════════════
#  WZHUB SCRAPER
# ══════════════════════════════════════════════

WZHUB_TIER_MAP = {"absolute meta": "S", "meta": "A"}
JS_CLICK_ALL = """() => {
    const els = [...document.querySelectorAll('button,span,div')].filter(
        e => e.textContent.trim() === 'SHOW DETAILS'
    );
    els.forEach(e => e.click());
    return els.length;
}"""

def scrape_wzhub():
    html = fetch_playwright(WZHUB_URL, wait_ms=5000, js_click=JS_CLICK_ALL)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")

    # Alle wapennamen uit bo7 links
    weapon_names = set()
    for a in soup.find_all("a", href=True):
        if "/loadouts/bo7-" in a.get("href", ""):
            n = a.get_text(strip=True)
            if n and len(n) >= 2:
                weapon_names.add(n)
    log(f"  bo7 wapennamen: {len(weapon_names)}")

    all_weapons = {}
    current_tier = "?"

    for el in soup.find_all(True):
        if el.name == "h2":
            t = el.get_text(strip=True).lower()
            current_tier = WZHUB_TIER_MAP.get(t, "?")
            continue

        classes = ' '.join(el.get('class', []))
        if 'loadouts-list__group' not in classes:
            continue
        if current_tier not in ("S", "A"):
            continue

        lines = [l.strip() for l in el.get_text(separator="\n").split("\n") if l.strip()]

        # Splits de groep in wapens: nieuw wapen start bij een bekende wapennaam
        cur_name = None
        cur = None
        in_details = False
        i = 0
        while i < len(lines):
            line = lines[i]

            if line in weapon_names and (i + 1 < len(lines)) and lines[i + 1] not in SLOT_NAMES_CAP:
                # nieuw wapen
                if cur and cur["attachments"] and cur_name not in all_weapons:
                    all_weapons[cur_name] = cur
                    log(f"    + {cur_name} ({cur['tier']}) {list(cur['attachments'].keys())}")
                cur_name = line
                cur = {"tier": current_tier, "build_code": "", "attachments": {}}
                in_details = False
                i += 1
                continue

            if cur is None:
                i += 1
                continue

            if line in ("HIDE DETAILS", "SHOW DETAILS"):
                in_details = True
                i += 1
                continue
            if not in_details:
                i += 1
                continue
            if line == "Loadout code" and i + 1 < len(lines):
                if not cur["build_code"]:
                    cur["build_code"] = lines[i + 1]
                i += 2
                continue
            if i + 1 < len(lines) and lines[i + 1].lower() in SLOT_NAMES:
                slot = SLOT_NORMALIZE.get(lines[i + 1].lower(), lines[i + 1])
                if slot not in cur["attachments"]:   # alleen eerste build
                    cur["attachments"][slot] = line.title()
                i += 2
                continue
            i += 1

        if cur and cur["attachments"] and cur_name not in all_weapons:
            all_weapons[cur_name] = cur
            log(f"    + {cur_name} ({cur['tier']}) {list(cur['attachments'].keys())}")

    log(f"  Totaal WZHUB: {len(all_weapons)} wapens")
    return all_weapons


# ══════════════════════════════════════════════
#  WZ META SCRAPER
# ══════════════════════════════════════════════

WZ_TIER_MAP = {"s": "S", "a": "A", "b": "B"}

def scrape_wz_meta():
    html = fetch_playwright(WZ_URL, wait_ms=5000)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    all_weapons = {}

    # Zoek alle weapon-acc details elementen
    weapon_cards = soup.select("details.weapon-acc")
    if not weapon_cards:
        weapon_cards = [d for d in soup.find_all("details") if "weapon-acc" in " ".join(d.get("class", []))]
    if not weapon_cards:
        weapon_cards = soup.find_all("details")
    log(f"  weapon-acc cards: {len(weapon_cards)}")
    if not weapon_cards:
        dump = os.path.join(SCRIPT_DIR, "debug_wz_live.html")
        with open(dump, "w", encoding="utf-8") as f: f.write(html)
        log(f"  [DEBUG] HTML opgeslagen: {dump}", "warning")

    dbg = 0
    for card in weapon_cards:
        texts = [t.strip() for t in card.get_text(separator="\n").split("\n") if t.strip()]
        if not texts:
            continue
        name = texts[0]

        # Tier: uit voorafgaande h3 ('SAbsolute MetaS Tier·4' / 'AMetaA Tier·8')
        tier = "?"
        h3 = card.find_previous("h3")
        if h3:
            ht = h3.get_text(strip=True).lower()
            if "absolute" in ht: tier = "S"
            elif "contender" in ht: tier = "B"
            elif "meta" in ht: tier = "A"
        if tier == "?":
            section = card.find_parent("section")
            if section:
                st = section.get_text(separator="|", strip=True)[:60].lower()
                if "absolute" in st: tier = "S"
                elif st.startswith("a|") or "|meta|" in st: tier = "A"

        # Builds
        builds = []
        build_divs = card.find_all("div", class_=lambda k: k and "border-t" in " ".join(k) and "border-border" in " ".join(k))
        containers = build_divs if build_divs else [card]
        for bd in containers:
            div_texts = [t.strip() for t in bd.get_text(separator="\n").split("\n") if t.strip()]
            label = div_texts[0] if div_texts else "Build"
            attachments = {}
            for li in bd.find_all("li"):
                hud = li.find(class_="hud-line")
                if not hud: continue
                slot_text = hud.get_text(strip=True)
                slot = SLOT_NORMALIZE.get(slot_text.lower())
                if not slot: continue
                value = li.get_text(separator="|", strip=True).replace(slot_text, "").replace("|", " ").strip()
                if value:
                    attachments[slot] = value
            if attachments:
                builds.append({"label": label, "attachments": attachments, "note": "", "rank": ""})

        if dbg < 3:
            dbg += 1
            log(f"    [dbg] {name} tier={tier} build_divs={len(build_divs)} li={len(card.find_all('li'))} hud={len(card.find_all(class_='hud-line'))} builds={len(builds)}")

        if tier not in ("S", "A"):
            continue
        if builds and name not in all_weapons:
            all_weapons[name] = {"tier": tier, "builds": builds}
            log(f"    + {name} ({tier}) {len(builds)} builds")

    log(f"  Totaal WZ Meta: {len(all_weapons)} wapens")
    return all_weapons


# ══════════════════════════════════════════════
#  HTML UPDATE
# ══════════════════════════════════════════════

WZ_START    = "/* WZ_META_START */"
WZ_END      = "/* WZ_META_END */"
WZHUB_START = "/* WZHUB_META_START */"
WZHUB_END   = "/* WZHUB_META_END */"

def replace_between(content, start, end, new_code):
    si = content.find(start)
    ei = content.find(end, si)
    if si == -1 or ei == -1:
        return content, 0
    return content[:si] + f'{start}\n  {new_code}\n  {end}' + content[ei + len(end):], 1

def update_html(path, wz_meta, wzhub_data):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
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


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def run():
    now = datetime.datetime.now()
    timestamp = now.strftime('%d/%m/%Y %H:%M')
    log("=" * 55)
    log("BuitKing's Loadout Updater gestart (v12)")
    log(f"Datum: {timestamp}")

    if not os.path.exists(HTML_PATH):
        log(f"FOUT: HTML niet gevonden: {HTML_PATH}", "error")
        sys.exit(1)

    log("\n[1/2] WZ Meta scrapen...")
    try:
        wz_meta = scrape_wz_meta()
        log(f"      OK: {len(wz_meta)} wapens")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); wz_meta = {}

    log("\n[2/2] WZHUB scrapen...")
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
