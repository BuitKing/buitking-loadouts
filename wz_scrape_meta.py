"""
warzoneloadout.games Scraper
==============================
Scrapet de meta loadouts van warzoneloadout.games
en slaat ze op als JSON voor gebruik in de HTML-app.

Vereisten: pip install requests beautifulsoup4
"""

import json
import sys
import re

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4"])
    from bs4 import BeautifulSoup


URLS = {
    "Warzone": "https://warzoneloadout.games/",
    "BO7":     "https://warzoneloadout.games/bo7/",
    "BO6":     "https://warzoneloadout.games/bo6/",
}

TIER_MAP = {
    "absolute meta": "S",
    "meta warzone":  "A",
    "meta bo":       "A",
    "contender":     "B",
    "average":       "C",
    "weak":          "D",
}

ATTACHMENT_SLOTS = {
    "muzzle", "barrel", "underbarrel", "laser", "ammunition", "magazine",
    "optic", "stock", "rear grip", "fire mods", "fire mod", "trigger",
    "trigger action", "combo", "comb"
}


def normalize_slot(s):
    s = s.strip()
    low = s.lower()
    if low in ("fire mods", "fire mod"):   return "Fire Mods"
    if low == "rear grip":                 return "Rear Grip"
    if low == "trigger action":            return "Trigger Action"
    return s.title()


def parse_attachment_text(text):
    """
    Attachment text looks like: 'MuzzleMonolithic Suppressor'
    Slot name is concatenated with the value — we split on known slot names.
    """
    slots_sorted = sorted(ATTACHMENT_SLOTS, key=len, reverse=True)
    tl = text.strip()
    for slot in slots_sorted:
        if tl.lower().startswith(slot):
            value = tl[len(slot):].strip()
            return normalize_slot(slot), value
    return None, tl


def get_tier(heading_text):
    ht = heading_text.lower()
    for key, tier in TIER_MAP.items():
        if key in ht:
            return tier
    return "?"


def scrape_page(url, source_label):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [FOUT] Kon {url} niet ophalen: {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    weapons = {}
    current_tier = "?"

    # Find all headings (h2 = tier headers, h3 = weapon names)
    content_area = soup.find("div", class_=re.compile(r"entry-content|post-content|wp-block")) or soup.body

    # Walk through all relevant elements
    for el in content_area.find_all(["h2", "h3", "li", "ol"]):
        tag = el.name

        if tag == "h2":
            current_tier = get_tier(el.get_text())
            continue

        if tag in ("ol",):
            continue

        if tag == "li":
            # Find weapon name (h3 inside li)
            h3 = el.find("h3")
            if not h3:
                continue

            weapon_name = h3.get_text(strip=True)
            if not weapon_name or len(weapon_name) < 2:
                continue

            # Get meta info (rank, category, game tag)
            meta_text = el.get_text(separator=" | ")
            game_tag = ""
            if "bo7" in meta_text.lower(): game_tag = "BO7"
            elif "bo6" in meta_text.lower(): game_tag = "BO6"
            elif "mw3" in meta_text.lower(): game_tag = "MW3"
            elif "mw2" in meta_text.lower(): game_tag = "MW2"

            # Find build sections — look for bullet points listing build types
            builds = []
            build_lists = el.find_all("ul")
            # Each <ul> inside the weapon li lists the build types
            build_type_labels = []
            for ul in build_lists:
                for li_item in ul.find_all("li"):
                    txt = li_item.get_text(strip=True)
                    if "attachment" in txt.lower():
                        build_type_labels.append(txt.replace(" Attachments", "").replace(" attachments", "").strip())

            # Find all attachment dl/div blocks
            att_blocks = el.find_all("div", recursive=True)

            # Alternative: get all text and parse
            # The page structure has attachment text like "MuzzleMonolithic Suppressor"
            # grouped per build. Let's find the updated timestamps to split builds.
            full_text = el.get_text(separator="\n")
            lines = [l.strip() for l in full_text.split("\n") if l.strip()]

            # Split on "Updated:" markers to separate builds
            build_chunks = []
            current_chunk = []
            for line in lines:
                if line.startswith("Updated:"):
                    if current_chunk:
                        build_chunks.append(current_chunk)
                    current_chunk = []
                else:
                    current_chunk.append(line)
            if current_chunk:
                build_chunks.append(current_chunk)

            # Parse each chunk for attachments
            note_lines = []
            for chunk_idx, chunk in enumerate(build_chunks):
                attachments = {}
                build_note = ""
                build_label = build_type_labels[chunk_idx] if chunk_idx < len(build_type_labels) else f"Build {chunk_idx + 1}"

                for line in chunk:
                    # Skip weapon name, meta badges, etc.
                    if line == weapon_name:
                        continue
                    if line in ("Open accordion", "Close accordion"):
                        continue
                    if re.match(r"#\d+", line):
                        continue
                    if line.lower() in ("bo7", "bo6", "mw3", "mw2"):
                        continue
                    if "Best Loadouts" in line:
                        continue
                    if "Attachment" in line and re.search(r"\d+", line):
                        continue  # "5 Attachments" line

                    slot, value = parse_attachment_text(line)
                    if slot:
                        attachments[slot] = value
                    elif len(line) > 10 and not any(c.isdigit() for c in line[:3]):
                        build_note = line  # likely a note/tip

                if attachments:
                    builds.append({
                        "label": build_label,
                        "attachments": attachments,
                        "note": build_note
                    })

            if builds:
                # Use weapon name as key, handle duplicates by appending game
                key = weapon_name
                if key in weapons:
                    # Merge builds if same weapon appears in multiple tiers
                    existing = weapons[key]
                    for b in builds:
                        if b not in existing["builds"]:
                            existing["builds"].append(b)
                else:
                    weapons[key] = {
                        "tier": current_tier,
                        "game": game_tag,
                        "source": source_label,
                        "builds": builds
                    }

    return weapons


def scrape_all():
    print("warzoneloadout.games scrapen...")
    all_weapons = {}

    for label, url in URLS.items():
        print(f"  Pagina: {label} ({url})")
        data = scrape_page(url, label)
        print(f"  → {len(data)} wapens gevonden")
        for name, info in data.items():
            if name not in all_weapons:
                all_weapons[name] = info
            else:
                # Add unique builds
                existing_labels = {b["label"] for b in all_weapons[name]["builds"]}
                for b in info["builds"]:
                    if b["label"] not in existing_labels:
                        all_weapons[name]["builds"].append(b)

    print(f"Totaal: {len(all_weapons)} unieke wapens")
    return all_weapons


if __name__ == "__main__":
    import os
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wz_meta.json")
    data = scrape_all()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Opgeslagen: {out_path}")
