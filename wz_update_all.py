""" BuitKing's Loadout Updater - v8
=================================
TeeP Excel volledig verwijderd.
Data-bronnen: WZ Meta (warzoneloadout.games) + WZHUB (wzhub.gg)

Stappen:
1. Scrapet warzoneloadout.games/warzone-meta/ (WZ Meta)
2. Scrapet wzhub.gg/loadouts (WZHUB Meta)
3. Bouwt RAW-structuur vanuit WZ Meta + WZHUB
4. Scrapet playlists (wzhub.gg/playlist/wz)
5. Update index.html (incl. eenmalige TeeP-migratie)

Vereisten: pip install requests beautifulsoup4
"""

import sys, os, json, logging, datetime, re

# ─────────────────────────────────────────────
# CONFIGURATIE
# ─────────────────────────────────────────────
HTML_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
LOG_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buitking_update.log")
WZ_URL       = "https://warzoneloadout.games/warzone-meta/"
WZHUB_URL    = "https://wzhub.gg/loadouts"
PLAYLIST_URL = "https://wzhub.gg/playlist/wz"
# ─────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
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

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ══════════════════════════════════════════════
# CATEGORIE NORMALISATIE
# ══════════════════════════════════════════════
WZ_GAME_TAGS = {'bo7', 'bo6', 'mw3', 'mw2'}
WZ_CAT_TAGS  = {
    'assault rifle', 'smg', 'sniper rifle', 'marksman rifle',
    'lmg', 'light machine gun', 'shotgun', 'pistol', 'handgun', 'battle rifle'
}

def norm_wz_cat(s):
    s = s.lower().strip()
    if 'assault' in s:      return 'Assault Rifles'
    if 'smg' in s or 'submachine' in s: return 'SMGs'
    if 'sniper' in s:       return 'Sniper Rifles'
    if 'marksman' in s:     return 'Marksman Rifles'
    if 'lmg' in s or 'light machine' in s: return 'LMGs'
    if 'shotgun' in s:      return 'Shotguns'
    if 'pistol' in s or 'handgun' in s: return 'Pistols'
    if 'battle rifle' in s: return 'Battle Rifles'
    return ''

# WZHUB URL-slug → categorie
WZHUB_CAT_SLUGS = {
    'assault-rifle':  'Assault Rifles',
    'smg':            'SMGs',
    'sniper-rifle':   'Sniper Rifles',
    'marksman-rifle': 'Marksman Rifles',
    'lmg':            'LMGs',
    'shotgun':        'Shotguns',
    'pistol':         'Pistols',
    'battle-rifle':   'Battle Rifles',
}

def cat_from_wzhub_href(href):
    """Haal categorie op uit WZHUB URL: loadouts/bo7-assault-rifle-name"""
    for slug, name in WZHUB_CAT_SLUGS.items():
        if f'bo7-{slug}-' in href:
            return name
    return ''

# ══════════════════════════════════════════════
# DEEL 1: WARZONELOADOUT.GAMES SCRAPER
# ══════════════════════════════════════════════
TIER_MAP = {
    "absolute meta": "S",
    "meta warzone":  "A",
    "contender":     "B",
    "average":       "C",
    "weak":          "D",
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
    return (not l or l.startswith("Updated:") or
            re.match(r"#\d+", l) or
            l.lower() in ("bo7","bo6","mw3","mw2","warzone") or
            "Best Loadout" in l or "Open accordion" in l or
            "copyright" in l.lower() or l.startswith("http") or
            bool(re.search(r"\d+\s*Attachments?", l, re.I)))

def parse_build_pairs(lines, weapon_name):
    atts = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        slot = get_slot(line)
        if slot:
            j = i + 1
            while j < len(lines) and is_junk(lines[j]): j += 1
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
        if (len(l) > 30 and not get_slot(l) and not is_junk(l) and
                l != weapon_name and l not in att_values and
                not l.lower().startswith(("bo7","bo6","mw3","mw2","#"))):
            return l
    return ""

def scrape_wz_meta():
    log(f"  Ophalen: {WZ_URL}")
    try:
        r = requests.get(WZ_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log(f"  [FOUT] {e}", "warning"); return {}

    soup = BeautifulSoup(r.text, "html.parser")
    all_weapons  = {}
    current_tier = "?"
    seen_names   = set()

    for el in soup.find_all(["h2", "li"]):
        if el.name == "h2":
            current_tier = get_tier(el.get_text())
            continue

        h3 = el.find("h3")
        if not h3: continue
        name = h3.get_text(strip=True)
        if not name or len(name) < 2: continue

        # Categorie + game uit span-tags
        wz_cat  = ''
        wz_game = ''
        for span in el.find_all('span'):
            t = span.get_text(strip=True).lower()
            if t in WZ_CAT_TAGS:
                wz_cat = norm_wz_cat(t)
            elif t in WZ_GAME_TAGS:
                wz_game = t.upper()

        labels = []
        for ul in el.find_all("ul"):
            for item in ul.find_all("li"):
                t = item.get_text(strip=True)
                if "ttachment" in t:
                    label = re.sub(r'\s*-?\s*\d+\s*Attachments?', '', t, flags=re.I).strip()
                    if label: labels.append(label)

        text      = el.get_text(separator="\n")
        raw_lines = [l.strip() for l in text.split("\n") if l.strip()]

        rank_map = {}
        for line in raw_lines:
            m = re.match(r'^(#\d+)\s+(.+)$', line.strip())
            if m: rank_map[m.group(2).strip().lower()] = m.group(1)

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

        if builds and current_tier in ("S", "A", "B"):
            if name not in seen_names:
                seen_names.add(name)
                all_weapons[name] = {
                    "tier":     current_tier,
                    "builds":   builds,
                    "category": wz_cat,
                    "game":     wz_game,
                }
                log(f"  + {name} ({current_tier}, {wz_cat}, {wz_game})")
            else:
                existing = {b["label"] for b in all_weapons[name]["builds"]}
                for b in builds:
                    if b["label"] not in existing:
                        all_weapons[name]["builds"].append(b)

    log(f"  Totaal: {len(all_weapons)} wapens")
    return all_weapons

# ══════════════════════════════════════════════
# DEEL 2: WZHUB.GG SCRAPER
# ══════════════════════════════════════════════
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
        next_l  = lines[i+1]
        if next_l.startswith(" ") and next_l.strip().lower() in WZHUB_SLOT_NORMALIZE:
            slot = WZHUB_SLOT_NORMALIZE[next_l.strip().lower()]
            atts[slot] = current.title()
            i += 2
        else:
            i += 1
    return atts

def ensure_playwright():
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
    if not ensure_playwright(): return {}
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    all_weapons = {}
    log(f"  Browser openen: {WZHUB_URL}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36"
            )
            page.goto(WZHUB_URL, wait_until="networkidle", timeout=30000)
            try: page.wait_for_selector("h2", timeout=10000)
            except PWTimeout: pass
            html    = page.content()
            browser.close()

        log("  Pagina geladen — parsen...")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script","style","img","svg","noscript","button","nav"]):
            tag.decompose()

        current_tier = "?"
        for el in soup.find_all(["h2","div","a","section"]):
            tag = el.name
            if tag == "h2":
                t = el.get_text(strip=True).lower()
                if "absolute" in t:   current_tier = "S"
                elif t == "meta":     current_tier = "A"
                elif "contender" in t: current_tier = "B"
                else:                 current_tier = "C"
                continue

            if tag == "a":
                href = el.get("href", "")
                if "loadouts/bo7-" not in href: continue
                if current_tier not in ("S","A","B"): continue

                name = el.get_text(strip=True).title()
                if not name or len(name) < 2: continue

                # Categorie uit URL
                category = cat_from_wzhub_href(href)

                parent = el.parent
                for _ in range(6):
                    if not parent: break
                    txt = parent.get_text(separator="\n")
                    if any(s in txt.lower() for s in ("muzzle","barrel","magazine","optic","stock")):
                        break
                    parent = parent.parent
                if not parent: continue

                text       = parent.get_text(separator="\n")
                lines_list = [l.strip() for l in text.split("\n") if l.strip()]

                build_code = ""
                for line in lines_list:
                    if re.match(r"^[A-Z][0-9]{2}-", line):
                        build_code = line; break

                # Rank extractie (#1, #2 etc) — staat vaak als eerste regel
                rank = ""
                for line in lines_list:
                    m = re.match(r'^(#\d+)(?:\s|$)', line.strip())
                    if m: rank = m.group(1); break

                atts = parse_wzhub_atts(lines_list)
                if not atts:
                    i = 0
                    while i < len(lines_list) - 1:
                        slot = WZHUB_SLOT_NORMALIZE.get(lines_list[i].lower())
                        if slot:
                            val = lines_list[i+1].strip()
                            if val and not WZHUB_SLOT_NORMALIZE.get(val.lower()):
                                atts[slot] = val.title()
                            i += 2; continue
                        i += 1

                if atts and name not in all_weapons:
                    all_weapons[name] = {
                        "tier":        current_tier,
                        "build_code":  build_code,
                        "rank":        rank,
                        "attachments": atts,
                        "category":    category,
                    }
                    rank_str = f" {rank}" if rank else ""
                    log(f"  + {name} ({current_tier}{rank_str}, {category})")
    except Exception as e:
        log(f"  [FOUT] Playwright: {e}", "warning")

    log(f"  Totaal: {len(all_weapons)} wapens van wzhub.gg")
    return all_weapons

# ══════════════════════════════════════════════
# DEEL 3: BOUW RAW VANUIT WZ META + WZHUB
# ══════════════════════════════════════════════
def build_raw(wz_meta, wzhub_data):
    """
    Bouwt de RAW-structuur (game → categorie → wapens) uitsluitend
    vanuit WZ Meta en WZHUB. TeeP Excel wordt niet meer gebruikt.
    """
    raw  = {}
    seen = set()

    # ── WZ Meta wapens (hebben categorie + game uit scraper) ──
    for name, meta in wz_meta.items():
        cat  = meta.get('category', '')
        game = meta.get('game', '')
        if not cat or not game:
            log(f"  [SKIP] {name}: geen cat/game info in WZ Meta")
            continue
        raw.setdefault(game, {}).setdefault(cat, []).append({
            'name': name, 'build_code': '', 'attachments': {}
        })
        seen.add(name.strip().upper())

    # ── WZHUB wapens die nog niet in RAW zitten ──
    for name, hub in wzhub_data.items():
        if name.strip().upper() in seen:
            continue
        cat = hub.get('category', '')
        if not cat:
            log(f"  [SKIP] {name}: geen categorie-info in WZHUB")
            continue
        game = 'BO7'  # WZHUB toont momenteel alleen BO7
        raw.setdefault(game, {}).setdefault(cat, []).append({
            'name': name, 'build_code': '', 'attachments': {}
        })
        seen.add(name.strip().upper())
        log(f"  + WZHUB-only wapen: {name} ({cat})")

    total = sum(len(ws) for cats in raw.values() for ws in cats.values())
    log(f"  RAW gebouwd: {total} wapens over {len(raw)} games")
    return raw

# ══════════════════════════════════════════════
# DEEL 4: PLAYLIST SCRAPER
# ══════════════════════════════════════════════
def scrape_playlist():
    log(f"  Ophalen: {PLAYLIST_URL}")
    try:
        r = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log(f"  [FOUT] {e}", "warning"); return {}

    soup   = BeautifulSoup(r.text, "html.parser")
    result = {"date_range":"","season_label":"","season_pct":0,"playlists":[]}

    for el in soup.find_all(["p","span","div","h2","h3"]):
        t = el.get_text(strip=True)
        if re.match(r'^[A-Z][a-z]+ \d+ [-\u2013] [A-Z][a-z]+ \d+$', t):
            result["date_range"] = t; break

    for el in soup.find_all(True):
        t = el.get_text(strip=True)
        m = re.search(r'(SEASON\s*\d+\s*[-\u2013]\s*\d+%\s*\(\d+ DAYS?\))', t, re.IGNORECASE)
        if m:
            result["season_label"] = m.group(1).strip()
            pct = re.search(r'(\d+)%', m.group(1))
            if pct: result["season_pct"] = int(pct.group(1))
            break

    seen = set()
    card_candidates = []
    for el in soup.find_all(class_=re.compile(r'playlist.?card', re.I)):
        classes = ' '.join(el.get('class',[]))
        if re.search(r'(title|mode|item|row|badge|tag|ltm)', classes, re.I): continue
        card_candidates.append(el)

    if not card_candidates:
        PLAYLIST_NAMES = {'BATTLE ROYALE','RESURGENCE','PLUNDER','DMZ','REBIRTH','FORTUNE'}
        for el in soup.find_all(['li','article','div']):
            txt = el.get_text(separator=' ', strip=True).upper()
            if any(pn in txt for pn in PLAYLIST_NAMES) and len(txt) < 500:
                card_candidates.append(el)

    for card in card_candidates:
        title_el = (card.find(class_=re.compile(r'title', re.I)) or
                    card.find(['h2','h3','h4','strong','b']))
        name = (title_el.get_text(strip=True) if title_el
                else card.get_text(separator=' ', strip=True)[:50]).upper()
        name = re.sub(r'\s+', ' ', name).strip()
        if not name or len(name) < 3 or name in seen: continue
        if not any(kw in name for kw in ['BATTLE ROYALE','RESURGENCE','PLUNDER','DMZ','CASUAL','LOADED']): continue
        seen.add(name)

        ltm = bool(card.find(string=re.compile(r'\bLTM\b', re.IGNORECASE)) or
                   card.find(class_=re.compile(r'ltm', re.IGNORECASE)))

        modes    = []
        mode_els = card.find_all(class_=re.compile(r'mode|item|row|entry', re.I))
        if mode_els:
            for mel in mode_els:
                t = mel.get_text(strip=True).upper()
                if t and len(t) > 2 and 'LTM' not in t and name not in t:
                    modes.append(t)
        else:
            raw = card.get_text(separator='\n')
            for line in raw.split('\n'):
                line = line.strip().upper()
                if ' - ' in line and 4 < len(line) < 60:
                    if name not in line and 'LTM' not in line:
                        modes.append(line)

        modes = list(dict.fromkeys(modes))
        result["playlists"].append({"name":name,"modes":modes,"ltm":ltm})
        log(f"  + {name} (ltm={ltm}, modes={len(modes)})")

    log(f"  Totaal: {len(result['playlists'])} playlists, seizoen: {result['season_label']}")
    return result

# ══════════════════════════════════════════════
# DEEL 5: HTML UPDATER
# ══════════════════════════════════════════════
TEEP_START     = "/* TEEP_DATA_START */"
TEEP_END       = "/* TEEP_DATA_END */"
WZ_START       = "/* WZ_META_START */"
WZ_END         = "/* WZ_META_END */"
WZHUB_START    = "/* WZHUB_META_START */"
WZHUB_END      = "/* WZHUB_META_END */"
PLAYLIST_START = "/* PLAYLIST_START */"
PLAYLIST_END   = "/* PLAYLIST_END */"

def replace_between(content, start, end, new_code):
    si = content.find(start)
    ei = content.find(end, si)
    if si == -1 or ei == -1: return content, 0
    replacement = f'{start}\n  {new_code}\n  {end}'
    return content[:si] + replacement + content[ei + len(end):], 1

def render_panel_html(d):
    ORDER = ['BATTLE ROYALE','RESURGENCE','BATTLE ROYALE CASUAL','RESURGENCE CASUAL']
    def pl_sort(p):
        if p.get('ltm'): return (99, p['name'])
        try: return (ORDER.index(p['name']), p['name'])
        except ValueError: return (50, p['name'])

    playlists = sorted(d.get('playlists',[]), key=pl_sort)
    cards = ''
    for p in playlists:
        ltm   = '<span class="pl-ltm">LTM</span>' if p.get('ltm') else ''
        modes = ''
        for ms in p.get('modes',[]):
            dash  = ms.rfind(' - ')
            left  = ms[dash+3:] if dash > 0 else ms
            right = ms[:dash]   if dash > 0 else ''
            modes += f'<div class="pl-mode-row"><span class="pl-mode-map">{left}</span>'
            if right: modes += f'<span class="pl-mode-type">{right}</span>'
            modes += '</div>'
        cls    = 'pl-card ltm' if p.get('ltm') else 'pl-card'
        cards += (f'<div class="{cls}"><div class="pl-card-head">'
                  f'<span class="pl-name">{p["name"]}</span>{ltm}</div>'
                  f'<div class="pl-modes">{modes}</div></div>')
    dr = f'<div class="pl-daterange">{d.get("date_range","")}</div>' if d.get('date_range') else ''
    return f'<div class="pl-title">\U0001f3ae WZ PLAYLISTS</div>{dr}<hr class="pl-divider">{cards}'

def migrate_html(content):
    """
    Eenmalige migratie: verwijder TeeP-specifieke JS-code uit index.html.
    Idempotent — als al gepatcht, verandert er niets.
    """
    original = content

    # 1. teepBuilds altijd 0 (was: ternary op w.attachments)
    content = re.sub(
        r'const teepBuilds\s*=\s*Object\.values\(w\.attachments\)\.some\([^)]+\)\s*\?\s*1\s*:\s*\n?\s*0;',
        'const teepBuilds = 0;',
        content
    )

    # 2. Verwijder has-code class toewijzing
    content = content.replace(
        "if(w.build_code) classes+=' has-code';",
        "// build_code niet meer van TeeP"
    )

    # 3. Verwijder codeOnly filter op build_code
    content = content.replace(
        "if(codeOnly && !w.build_code) return false;",
        "// codeOnly-filter verwijderd (geen TeeP build codes meer)"
    )

    # 4. Verwijder BUILD CODE toggle knop uit filter bar
    #    Zoek de specifieke div inclusief de volgende filter-sep
    content = re.sub(
        r"`<div class=\"code-toggle[^`]*>BUILD CODE</div>` \+\s*\n\s*`<div class=\"filter-sep\"></div>` \+\s*\n\s*",
        '',
        content
    )

    # 5. TeeP-panel in modal verbergen (zet display:none op modalCodeRow sectie)
    #    Alleen als het TeeP paneel nog zichtbaar is (niet al verborgen)
    if 'id="modalCodeRow"' in content and 'display:none' not in content[content.find('id="modalCodeRow"')-20:content.find('id="modalCodeRow"')+5]:
        content = content.replace(
            'id="modalCodeRow"',
            'id="modalCodeRow" style="display:none"'
        )

    # 6. B-TIER pill toevoegen na A-TIER (idempotent)
    a_pill = "`<div class=\"tier-pill ${activeTier==='A'?'active':''}\" onclick=\"setTier('A')\">A-TIER</div>`"
    b_pill = " +\n    `<div class=\"tier-pill ${activeTier==='B'?'active':''}\" onclick=\"setTier('B')\">B-TIER</div>`"
    if a_pill in content and "setTier('B')" not in content:
        content = content.replace(a_pill, a_pill + b_pill)
        log("  [MIGRATIE] B-TIER pill toegevoegd aan filterbar")

    # 7. B-tier badge CSS (idempotent)
    b_css = '.mini-badge.b{background:#7a5500;color:#ffcc44;}'
    if b_css not in content and '.mini-badge.a{' in content:
        content = content.replace('.mini-badge.a{', b_css + '\n.mini-badge.a{')
        log("  [MIGRATIE] B-tier badge CSS toegevoegd")

    # 8. filterWeapon: B-tier filterregel toevoegen
    hub_filter_line = "if(activeSource==='hub' && !getHubEntry(w.name))  return false;"
    b_filter_line   = "\n  if(activeTier==='B'   && ![getWzEntry(w.name),getHubEntry(w.name)].some(e=>e&&e.tier==='B')) return false;"
    if hub_filter_line in content and "activeTier==='B'" not in content:
        content = content.replace(hub_filter_line, hub_filter_line + b_filter_line)
        log("  [MIGRATIE] B-tier filterregel toegevoegd")

    # 9. tierSort: return 4 (geen tier) -> B-tier op positie 4, geen tier op 5
    no_tier_line = "  return 4;                   // geen tier"
    if no_tier_line in content and 'bCount' not in content:
        b_sort = (
            "  const bCount = (wzTier==='B'?1:0) + (hubTier==='B'?1:0);\n"
            "  if(bCount>=1) return 4;    // B tier\n"
            "  return 5;                  // geen tier"
        )
        content = content.replace(no_tier_line, b_sort)
        log("  [MIGRATIE] B-tier sortering toegevoegd")

    if content != original:
        log("  [MIGRATIE] HTML succesvol bijgewerkt")
    else:
        log("  [MIGRATIE] HTML al up-to-date (geen wijzigingen nodig)")
    return content

def update_html(path, raw_data, wz_meta, wzhub_data, playlist_data, timestamp):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if WZ_START not in content or WZHUB_START not in content:
        log("FOUT: markers niet gevonden -- gebruik de nieuwste index.html", "error")
        raise ValueError("Markers ontbreken")

    # Eenmalige TeeP-migratie
    content = migrate_html(content)

    # RAW data (nu vanuit WZ Meta + WZHUB ipv TeeP)
    if TEEP_START in content:
        content, _ = replace_between(content, TEEP_START, TEEP_END,
            f'const RAW = {json.dumps(raw_data, ensure_ascii=False)};')

    # WZ Meta data
    if wz_meta:
        content, _ = replace_between(content, WZ_START, WZ_END,
            f'const WZ_META = {json.dumps(wz_meta, ensure_ascii=False)};')
    else:
        log("  [WAARSCHUWING] WZ Meta leeg -- bestaande data behouden", "warning")

    # WZHUB data
    if wzhub_data:
        content, _ = replace_between(content, WZHUB_START, WZHUB_END,
            f'const WZHUB_META = {json.dumps(wzhub_data, ensure_ascii=False)};')
    else:
        log("  [WAARSCHUWING] WZHUB leeg -- bestaande data behouden", "warning")

    # Playlist data
    if playlist_data and playlist_data.get("playlists"):
        def escape_sq(obj):
            if isinstance(obj, str):  return obj.replace("'", "\u2019")
            if isinstance(obj, list): return [escape_sq(i) for i in obj]
            if isinstance(obj, dict): return {k: escape_sq(v) for k,v in obj.items()}
            return obj
        pd = escape_sq(playlist_data)

        content, _ = replace_between(content, PLAYLIST_START, PLAYLIST_END,
            f'const PLAYLIST_DATA = {json.dumps(pd, ensure_ascii=True)};')

        static_inner = render_panel_html(pd)
        panel_open   = '<div class="playlist-panel" id="playlistPanel">'
        pi           = content.find(panel_open)
        if pi != -1:
            close_start = pi + len(panel_open)
            depth, pos  = 1, close_start
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

    # LAST_UPDATED JS variabele injecteren
    LASTUPDATE_START = "/* LASTUPDATE_START */"
    LASTUPDATE_END   = "/* LASTUPDATE_END */"
    if LASTUPDATE_START in content:
        content, _ = replace_between(content, LASTUPDATE_START, LASTUPDATE_END,
            f'const LAST_UPDATED = "{timestamp}";')

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════
def run():
    now       = datetime.datetime.now()
    timestamp = now.strftime('%d/%m/%Y %H:%M')

    log("=" * 55)
    log("BuitKing's Loadout Updater gestart (v8 - geen TeeP)")
    log(f"Datum: {timestamp}")

    if not os.path.exists(HTML_PATH):
        log(f"FOUT: HTML niet gevonden: {HTML_PATH}", "error")
        sys.exit(1)

    # -- Stap 1: WZ Meta
    log("\n[1/4] WZ Meta scrapen (warzoneloadout.games)...")
    try:
        wz_meta = scrape_wz_meta()
        log(f"    OK: {len(wz_meta)} wapens")
    except Exception as e:
        log(f"  FOUT: {e}", "warning"); wz_meta = {}

    # -- Stap 2: WZHUB Meta
    log("\n[2/4] WZHUB Meta scrapen (wzhub.gg)...")
    try:
        wzhub_data = scrape_wzhub()
        log(f"    OK: {len(wzhub_data)} wapens")
    except Exception as e:
        log(f"  FOUT: {e}", "warning"); wzhub_data = {}

    if not wz_meta and not wzhub_data:
        log("FOUT: Beide scrapers zijn leeg -- update afgebroken", "error")
        sys.exit(1)

    # -- Stap 3: Bouw RAW vanuit WZ Meta + WZHUB
    log("\n[3/4] RAW-data bouwen vanuit WZ Meta + WZHUB...")
    raw_data = build_raw(wz_meta, wzhub_data)

    # -- Stap 4: Warzone Playlists
    log("\n[4/4] Warzone Playlists scrapen (wzhub.gg/playlist/wz)...")
    try:
        playlist_data = scrape_playlist()
        log(f"    OK: {len(playlist_data.get('playlists',[]))} playlists")
    except Exception as e:
        log(f"  FOUT: {e}", "warning"); playlist_data = {}

    # -- Stap 5: HTML updaten
    log(f"\n[5/5] HTML updaten...")
    try:
        update_html(HTML_PATH, raw_data, wz_meta, wzhub_data, playlist_data, timestamp)
        log(f"    OK: Bijgewerkt op {timestamp}")
    except Exception as e:
        log(f"  FOUT: {e}", "error"); sys.exit(1)

    log("\nBuitKing's Loadouts bijgewerkt!")
    log("=" * 55)

if __name__ == "__main__":
    run()
