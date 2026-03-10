"""
BuitKing's Loadout Updater - v6
=================================
1. Downloadt TeeP's Excel en parseert loadouts
2. Scrapet warzoneloadout.games/warzone-meta/ (WZ Meta)
3. Scrapet wzhub.gg/loadouts (WZHUB Meta)
4. Update buitking_loadouts.html

Vereisten: pip install openpyxl requests beautifulsoup4
"""

import sys, os, json, logging, datetime, tempfile, re

# ─────────────────────────────────────────────
#  CONFIGURATIE
# ─────────────────────────────────────────────

EXCEL_URL      = "https://docs.google.com/spreadsheets/d/10uE2AoXbZpy6C9sdRdJ8GzQGPYNzg-xrNrEoM6V1-jE/export?format=xlsx"
HTML_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
LOG_PATH       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buitking_update.log")
WZ_URL         = "https://warzoneloadout.games/warzone-meta/"
WZHUB_URL      = "https://wzhub.gg/loadouts"
PLAYLIST_URL   = "https://wzhub.gg/playlist/wz"

# ─────────────────────────────────────────────

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
    try: import openpyxl
    except ImportError: pkgs.append("openpyxl")
    try: import requests
    except ImportError: pkgs.append("requests")
    try: import bs4
    except ImportError: pkgs.append("beautifulsoup4")
    if pkgs:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + pkgs + ["--quiet"])

ensure_deps()
import openpyxl, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ══════════════════════════════════════════════
#  DEEL 1: EXCEL PARSER (TeeP)
# ══════════════════════════════════════════════

ATT_SLOTS = {
    'MUZZLE','BARREL','UNDERBARREL','LASER','AMMUNITION','MAGAZINE','OPTIC',
    'STOCK/COMB','REAR GRIP','FIRE MOD','FIRE MODS','STOCK','COMB',
    'TRIGGER','TRIGGER ACTION','COMBO'
}
CAT_KW = [
    'ASSAULT RIFLE','SUB MACHINE','SUBMACHINE','LIGHT MACHINE',
    'MARKSMAN','SNIPER','SHOTGUN','PISTOL','HANDGUN','LMG','BATTLE RIFLE'
]
SKIP_NAMES = {
    'PERK 1','PERK 2','CONVERSION KIT','BOLT','SLING','AFTERMARKET CONVERSION KIT',
    'RAIL','STOCK PAD','AFTERMARKET PARTS','STOCK/GUARD',
    'UNDERBARREL/CARRY HANDLE','MAGAZINE/LOADER'
}
SECTION_BOUNDS = [
    (58,782,'BO7'),(783,1523,'BO6'),(1524,2282,'MW3'),(2283,9999,'MW2'),
]

def get_game(i):
    for s,e,n in SECTION_BOUNDS:
        if s<=i<=e: return n
    return None

def norm_cat(s):
    s = s.upper()
    if 'ASSAULT' in s:                  return 'Assault Rifles'
    if 'SUB' in s or 'SMG' in s:        return 'SMGs'
    if 'LIGHT MACHINE' in s or s.strip()=='LMGS': return 'LMGs'
    if 'MARKSMAN' in s:                 return 'Marksman Rifles'
    if 'SNIPER' in s:                   return 'Sniper Rifles'
    if 'SHOTGUN' in s:                  return 'Shotguns'
    if 'PISTOL' in s or 'HANDGUN' in s: return 'Pistols'
    if 'BATTLE' in s:                   return 'Battle Rifles'
    return None

def parse_excel(path):
    wb = openpyxl.load_workbook(path)
    ws = wb['WZ BUILDS']
    rows = list(ws.iter_rows(values_only=True))
    data, cur_cat = {}, None
    for i, row in enumerate(rows):
        game = get_game(i)
        if not game: continue
        a = str(row[0]).strip() if row[0] else ''
        b = str(row[1]).strip() if row[1] else ''
        if not a: continue
        au = a.upper()
        if any(kw in au for kw in CAT_KW):
            cat = norm_cat(a)
            if cat:
                cur_cat = cat
                if game not in data: data[game] = {}
                if cat not in data[game]: data[game][cat] = []
            continue
        if a=='-' or 'WEAPONS' in au: continue
        if au in ATT_SLOTS:
            if cur_cat and game in data and data[game].get(cur_cat):
                val = b.split('\n')[0].strip()
                if val.startswith('='):  # Excel formula — skip
                    val = ''
                data[game][cur_cat][-1]['attachments'][a.strip().title()] = val
            continue
        if cur_cat and au not in SKIP_NAMES:
            code = ''
            if 'BUILD CODE' in b.upper():
                code = b.upper().replace('BUILD CODE:','').replace('BUILD CODE :','').strip()
            if game not in data: data[game] = {}
            if cur_cat not in data[game]: data[game][cur_cat] = []
            data[game][cur_cat].append({'name':a,'build_code':code,'attachments':{}})
    cleaned = {}
    for game,cats in data.items():
        cleaned[game] = {}
        for cat,wps in cats.items():
            f = [w for w in wps if any(v and v.strip() for v in w['attachments'].values())]
            if f: cleaned[game][cat] = f
    return cleaned


# ══════════════════════════════════════════════
#  DEEL 2: WARZONELOADOUT.GAMES SCRAPER
# ══════════════════════════════════════════════

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

def extract_note(lines, weapon_name, att_values):
    for line in lines:
        l = line.strip()
        if (len(l) > 30 and not get_slot(l) and not is_junk(l)
                and l != weapon_name and l not in att_values
                and not l.lower().startswith(("bo7","bo6","mw3","mw2","#"))):
            return l
    return ""

def scrape_wz_meta():
    log(f"  Ophalen: {WZ_URL}")
    try:
        r = requests.get(WZ_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log(f"  [FOUT] {e}", "warning")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    all_weapons = {}
    current_tier = "?"
    seen_names = set()

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

        rank_map = {}
        for line in raw_lines:
            m = re.match(r'^(#\d+)\s+(.+)$', line.strip())
            if m:
                rank_map[m.group(2).strip().lower()] = m.group(1)

        chunks, cur_chunk = [], []
        for line in raw_lines:
            if line.startswith("Updated:"):
                if cur_chunk: chunks.append(cur_chunk); cur_chunk = []
            else:
                cur_chunk.append(line)
        if cur_chunk: chunks.append(cur_chunk)

        builds = []
        for ci, chunk in enumerate(chunks):
            label = labels[ci] if ci < len(labels) else f"Build {ci+1}"
            atts  = parse_build_pairs(chunk, name)
            note  = extract_note(chunk, name, set(atts.values()))
            rank  = rank_map.get(label.lower(), "")
            if atts:
                builds.append({"label": label, "attachments": atts, "note": note, "rank": rank})

        if builds and current_tier in ("S", "A"):
            if name not in seen_names:
                seen_names.add(name)
                all_weapons[name] = {"tier": current_tier, "builds": builds}
                log(f"    + {name} ({current_tier})")
            else:
                existing = {b["label"] for b in all_weapons[name]["builds"]}
                for b in builds:
                    if b["label"] not in existing:
                        all_weapons[name]["builds"].append(b)

    log(f"  Totaal: {len(all_weapons)} wapens")
    return all_weapons


# ══════════════════════════════════════════════
#  DEEL 3: WZHUB.GG SCRAPER
#  https://wzhub.gg/loadouts -- Warzone meta, 1 pagina
#  Absolute Meta -> S-tier, Meta -> A-tier
#  Attachment formaat: WAARDE op lijn N, " Slot" (met spatie) op lijn N+1
# ══════════════════════════════════════════════

WZHUB_TIER_MAP = {
    "absolute meta": "S",
    "meta": "A",
}

WZHUB_SLOT_NORMALIZE = {
    "muzzle":"Muzzle","barrel":"Barrel","underbarrel":"Underbarrel",
    "laser":"Laser","ammunition":"Ammunition","magazine":"Magazine",
    "optic":"Optic","stock":"Stock","rear grip":"Rear Grip",
    "fire mods":"Fire Mods","fire mod":"Fire Mods",
    "trigger":"Trigger","comb":"Comb","combo":"Combo",
}

def parse_wzhub_atts(lines):
    """
    wzhub.gg formaat: waarde eerst, dan " Slot" met voorloopspatie.
    Voorbeeld:
      "MONOLITHIC SUPPRESSOR"
      " Muzzle"
    """
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

def ensure_playwright():
    """Installeer Playwright + Chromium als dat nog niet is gebeurd."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        import subprocess
        log("  Playwright installeren...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "--quiet"])
        log("  Chromium installeren...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"])
        return True


def scrape_wzhub():
    """
    wzhub.gg is een Next.js app — data wordt puur via JS geladen.
    Playwright start een echte Chromium browser en wacht tot de content gerenderd is.
    """
    if not ensure_playwright():
        log("  [FOUT] Playwright niet beschikbaar", "warning")
        return {}

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    all_weapons = {}
    log(f"  Browser openen: {WZHUB_URL}")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36"
            )
            page.goto(WZHUB_URL, wait_until="networkidle", timeout=30000)

            # Wacht tot minstens één wapennaam zichtbaar is
            try:
                page.wait_for_selector("h2", timeout=10000)
            except PWTimeout:
                pass

            html = page.content()
            browser.close()

        log("  Pagina geladen — parsen...")
        soup = BeautifulSoup(html, "html.parser")

        # Verwijder overbodige tags
        for tag in soup(["script", "style", "img", "svg", "noscript", "button", "nav"]):
            tag.decompose()

        current_tier = "?"

        # Loop over alle elementen op volgorde
        for el in soup.find_all(["h2", "div", "a", "section"]):
            tag = el.name

            # Tier-headers (h2)
            if tag == "h2":
                t = el.get_text(strip=True).lower()
                if "absolute" in t:
                    current_tier = "S"
                elif t == "meta":
                    current_tier = "A"
                else:
                    current_tier = "C"
                continue

            # Wapen-links
            if tag == "a":
                href = el.get("href", "")
                if "loadouts/bo7-" not in href:
                    continue
                if current_tier not in ("S", "A"):
                    continue

                name = el.get_text(strip=True).title()
                if not name or len(name) < 2:
                    continue

                # Zoek de parent-container met attachment-data
                parent = el.parent
                for _ in range(6):
                    if not parent:
                        break
                    txt = parent.get_text(separator="\n")
                    if any(s in txt.lower() for s in ("muzzle","barrel","magazine","optic","stock")):
                        break
                    parent = parent.parent
                if not parent:
                    continue

                text = parent.get_text(separator="\n")
                lines_list = [l.strip() for l in text.split("\n") if l.strip()]

                # Build code
                build_code = ""
                for line in lines_list:
                    if re.match(r"^[A-Z][0-9]{2}-", line):
                        build_code = line
                        break

                # Attachments: "WAARDE\n Slot" patroon
                atts = parse_wzhub_atts(lines_list)

                # Fallback: slot op regel N, waarde op N+1
                if not atts:
                    i = 0
                    while i < len(lines_list) - 1:
                        slot = WZHUB_SLOT_NORMALIZE.get(lines_list[i].lower())
                        if slot:
                            val = lines_list[i+1].strip()
                            if val and not WZHUB_SLOT_NORMALIZE.get(val.lower()):
                                atts[slot] = val.title()
                                i += 2
                                continue
                        i += 1

                if atts and name not in all_weapons:
                    all_weapons[name] = {
                        "tier": current_tier,
                        "build_code": build_code,
                        "attachments": atts
                    }
                    log(f"    + {name} ({current_tier})")

    except Exception as e:
        log(f"  [FOUT] Playwright: {e}", "warning")

    log(f"  Totaal: {len(all_weapons)} wapens van wzhub.gg")
    return all_weapons

def scrape_playlist():
    log(f"  Ophalen: {PLAYLIST_URL}")
    try:
        r = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log(f"  [FOUT] {e}", "warning")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    result = {
        "date_range": "",
        "season_label": "",
        "season_pct": 0,
        "playlists": []
    }

    # --- Date range ---
    for el in soup.find_all(["p", "span", "div", "h2", "h3"]):
        t = el.get_text(strip=True)
        if re.match(r'^[A-Z][a-z]+ \d+ [-–] [A-Z][a-z]+ \d+$', t):
            result["date_range"] = t
            break

    # --- Season bar ---
    for el in soup.find_all(True):
        t = el.get_text(strip=True)
        m = re.search(r'(SEASON\s*\d+\s*[-–]\s*\d+%\s*\(\d+ DAYS?\))', t, re.IGNORECASE)
        if m:
            result["season_label"] = m.group(1).strip()
            pct = re.search(r'(\d+)%', m.group(1))
            if pct:
                result["season_pct"] = int(pct.group(1))
            break

    # --- Playlist cards --- probeer meerdere selector-strategieën
    seen = set()

    # Strategie 1: klasse bevat 'playlist-card' maar NIET sub-elementen
    card_candidates = []
    for el in soup.find_all(class_=re.compile(r'playlist.?card', re.I)):
        classes = ' '.join(el.get('class', []))
        # skip bekende sub-elementen
        if re.search(r'(title|mode|item|row|badge|tag|ltm)', classes, re.I):
            continue
        card_candidates.append(el)

    # Strategie 2: fallback — zoek op li/article/div met een tekst die lijkt op een playlist-naam
    if not card_candidates:
        PLAYLIST_NAMES = {'BATTLE ROYALE', 'RESURGENCE', 'PLUNDER', 'DMZ', 'REBIRTH', 'FORTUNE'}
        for el in soup.find_all(['li', 'article', 'div']):
            txt = el.get_text(separator=' ', strip=True).upper()
            if any(pn in txt for pn in PLAYLIST_NAMES) and len(txt) < 500:
                card_candidates.append(el)

    for card in card_candidates:
        # Naam: probeer title-sub-element, anders eerste tekst-node
        title_el = (card.find(class_=re.compile(r'title', re.I)) or
                    card.find(['h2','h3','h4','strong','b']))
        name = (title_el.get_text(strip=True) if title_el else card.get_text(separator=' ', strip=True)[:50]).upper()
        name = re.sub(r'\s+', ' ', name).strip()
        if not name or len(name) < 3 or name in seen:
            continue
        # Alleen echte playlist-namen doorlaten
        if not any(kw in name for kw in ['BATTLE ROYALE','RESURGENCE','PLUNDER','DMZ','CASUAL','LOADED']):
            continue
        seen.add(name)

        # LTM badge
        ltm = bool(card.find(string=re.compile(r'\bLTM\b', re.IGNORECASE)) or
                   card.find(class_=re.compile(r'ltm', re.IGNORECASE)))

        # Mode-rijen: probeer sub-elementen met 'mode|item|row|entry', anders alle tekst-blokken
        modes = []
        mode_els = card.find_all(class_=re.compile(r'mode|item|row|entry', re.I))
        if mode_els:
            for mel in mode_els:
                t = mel.get_text(strip=True).upper()
                if t and len(t) > 2 and 'LTM' not in t and name not in t:
                    modes.append(t)
        else:
            # Fallback: haal alle tekst-regels op, filter op MAP - MODE patroon
            raw = card.get_text(separator='\n')
            for line in raw.split('\n'):
                line = line.strip().upper()
                if ' - ' in line and len(line) > 4 and len(line) < 60:
                    if name not in line and 'LTM' not in line:
                        modes.append(line)

        # Dedupliceer
        modes = list(dict.fromkeys(modes))

        result["playlists"].append({"name": name, "modes": modes, "ltm": ltm})
        log(f"    + {name} (ltm={ltm}, modes={len(modes)})")

    log(f"  Totaal: {len(result['playlists'])} playlists, seizoen: {result['season_label']}")
    return result

TEEP_START      = "/* TEEP_DATA_START */"
TEEP_END        = "/* TEEP_DATA_END */"
WZ_START        = "/* WZ_META_START */"
WZ_END          = "/* WZ_META_END */"
WZHUB_START     = "/* WZHUB_META_START */"
WZHUB_END       = "/* WZHUB_META_END */"
PLAYLIST_START  = "/* PLAYLIST_START */"
PLAYLIST_END    = "/* PLAYLIST_END */"

def replace_between(content, start, end, new_code):
    """Replace content between start and end markers using string operations (not regex)."""
    si = content.find(start)
    ei = content.find(end, si)
    if si == -1 or ei == -1:
        return content, 0
    replacement = f'{start}\n  {new_code}\n  {end}'
    new_content = content[:si] + replacement + content[ei + len(end):]
    return new_content, 1

def update_html(path, teep_data, wz_meta, wzhub_data, playlist_data, timestamp):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if TEEP_START not in content or WZ_START not in content or WZHUB_START not in content:
        log("FOUT: markers niet gevonden -- gebruik de nieuwste buitking_loadouts.html", "error")
        raise ValueError("Markers ontbreken")

    content, _ = replace_between(content, TEEP_START, TEEP_END,
                                 f'const RAW = {json.dumps(teep_data, ensure_ascii=False)};')
    if wz_meta:
        content, _ = replace_between(content, WZ_START, WZ_END,
                                     f'const WZ_META = {json.dumps(wz_meta, ensure_ascii=False)};')
    else:
        log("  [WAARSCHUWING] WZ Meta leeg -- bestaande data behouden", "warning")
    if wzhub_data:
        content, _ = replace_between(content, WZHUB_START, WZHUB_END,
                                     f'const WZHUB_META = {json.dumps(wzhub_data, ensure_ascii=False)};')
    else:
        log("  [WAARSCHUWING] WZHUB leeg -- bestaande data behouden", "warning")
    if playlist_data and playlist_data.get("playlists"):
        ORDER = ['BATTLE ROYALE', 'RESURGENCE', 'BATTLE ROYALE CASUAL', 'RESURGENCE CASUAL']
        def pl_sort(p):
            if p.get('ltm'): return (99, p['name'])
            try: return (ORDER.index(p['name']), p['name'])
            except ValueError: return (50, p['name'])
        playlist_data['playlists'] = sorted(playlist_data['playlists'], key=pl_sort)
        def escape_sq(obj):
            if isinstance(obj, str):   return obj.replace("'", "\u2019")
            if isinstance(obj, list):  return [escape_sq(i) for i in obj]
            if isinstance(obj, dict):  return {k: escape_sq(v) for k, v in obj.items()}
            return obj
        pd = escape_sq(playlist_data)
        # Update JS data
        content, _ = replace_between(content, PLAYLIST_START, PLAYLIST_END,
                                     f'const PLAYLIST_DATA = {json.dumps(pd, ensure_ascii=True)};')
        # Also pre-render static HTML directly into the panel div (bulletproof)
        def render_panel_html(d):
            cards = ''
            for p in d.get('playlists', []):
                ltm = '<span class="pl-ltm">LTM</span>' if p.get('ltm') else ''
                modes = ''
                for ms in p.get('modes', []):
                    dash = ms.rfind(' - ')
                    left  = ms[dash+3:] if dash > 0 else ms   # mode left
                    right = ms[:dash]   if dash > 0 else ''    # map right
                    modes += f'<div class="pl-mode-row"><span class="pl-mode-map">{left}</span>'
                    if right: modes += f'<span class="pl-mode-type">{right}</span>'
                    modes += '</div>'
                cls = 'pl-card ltm' if p.get('ltm') else 'pl-card'
                cards += f'<div class="{cls}"><div class="pl-card-head"><span class="pl-name">{p["name"]}</span>{ltm}</div><div class="pl-modes">{modes}</div></div>'
            dr = f'<div class="pl-daterange">{d.get("date_range","")}</div>' if d.get('date_range') else ''
            return f'<div class="pl-title">🎮 WZ PLAYLISTS</div>{dr}<hr class="pl-divider">{cards}'

        static_inner = render_panel_html(pd)
        # Vervang panel-inhoud via brace-matching (robust, geen regex-fragility)
        panel_open = '<div class="playlist-panel" id="playlistPanel">'
        pi = content.find(panel_open)
        if pi != -1:
            close_start = pi + len(panel_open)
            depth, pos = 1, close_start
            while pos < len(content) and depth > 0:
                o = content.find('<div', pos)
                c = content.find('</div>', pos)
                if o != -1 and (c == -1 or o < c):
                    depth += 1; pos = o + 4
                elif c != -1:
                    depth -= 1
                    if depth == 0:
                        content = content[:close_start] + static_inner + content[c:]
                    else:
                        pos = c + 6
                else:
                    break
    else:
        log("  [WAARSCHUWING] Playlist leeg -- bestaande data behouden", "warning")

    content = re.sub(
        r'(id="lastUpdated"[^>]*>)[^<]*(<)',
        rf'\1Bijgewerkt: {timestamp}\2',
        content
    )

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def run():
    now       = datetime.datetime.now()
    timestamp = now.strftime('%d/%m/%Y %H:%M')

    log("=" * 55)
    log("BuitKing's Loadout Updater gestart")
    log(f"Datum: {timestamp}")

    if not os.path.exists(HTML_PATH):
        log(f"FOUT: HTML niet gevonden: {HTML_PATH}", "error")
        sys.exit(1)

    # -- Stap 1: Excel
    log("\n[1/4] Excel downloaden & parseren...")
    tmp = os.path.join(tempfile.gettempdir(), "buitking_temp.xlsx")
    try:
        r = requests.get(EXCEL_URL, timeout=30)
        r.raise_for_status()
        with open(tmp, 'wb') as f: f.write(r.content)
        teep_data = parse_excel(tmp)
        total = sum(len(w) for cats in teep_data.values() for w in cats.values())
        log(f"      OK: {total} wapens over {len(teep_data)} games")
    except Exception as e:
        log(f"      FOUT: {e}", "error"); sys.exit(1)
    finally:
        try: os.remove(tmp)
        except: pass

    # -- Stap 2: WZ Meta (warzoneloadout.games)
    log("\n[2/5] WZ Meta scrapen (warzoneloadout.games)...")
    try:
        wz_meta = scrape_wz_meta()
        log(f"      OK: {len(wz_meta)} wapens")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); wz_meta = {}

    # -- Stap 3: WZHUB Meta (wzhub.gg)
    log("\n[3/5] WZHUB Meta scrapen (wzhub.gg)...")
    try:
        wzhub_data = scrape_wzhub()
        log(f"      OK: {len(wzhub_data)} wapens")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); wzhub_data = {}

    # -- Stap 4: Warzone Playlists (wzhub.gg/playlist/wz)
    log("\n[4/5] Warzone Playlists scrapen (wzhub.gg/playlist/wz)...")
    try:
        playlist_data = scrape_playlist()
        log(f"      OK: {len(playlist_data.get('playlists', []))} playlists")
    except Exception as e:
        log(f"      FOUT: {e}", "warning"); playlist_data = {}

    # -- Stap 5: HTML updaten
    log(f"\n[5/5] HTML updaten...")
    try:
        update_html(HTML_PATH, teep_data, wz_meta, wzhub_data, playlist_data, timestamp)
        log(f"      OK: Bijgewerkt op {timestamp}")
    except Exception as e:
        log(f"      FOUT: {e}", "error"); sys.exit(1)

    log("\nBuitKing's Loadouts bijgewerkt!")
    log("=" * 55)

if __name__ == "__main__":
    run()
