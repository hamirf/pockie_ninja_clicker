"""
Pockie Ninja Auto-Clicker (dynamic templates, per-step click toggle, scoped sections)
---------------------------------------------------------------------------------------
Detects on-screen elements (bosses, buildings, buttons) using template
matching via OpenCV + PyAutoGUI, and clicks them as soon as they appear —
reacting to what's on screen instead of waiting on a fixed timer.

Templates are loaded dynamically from the ./templates/ folder — drop a new
screenshot in there while the script is running and it's picked up
automatically (no code edits, no restart).

FILE NAMING:
    <priority>_<name>[@confidence][_click|_noclick].<ext>

    priority     : number controlling check order — lower is checked first
    name         : just used in the console log
    @confidence  : optional, defaults to DEFAULT_CONFIDENCE
    _click       : (default) click the element when found
    _noclick     : only detect it, never click — used as a checkpoint OR,
                   when it's the anchor of a section folder (see below),
                   as the box that scopes where its sibling buttons are
                   searched for.

SCOPING TO A SECTION (fixes "same-looking button in different sections"):
    Put a section's anchor screenshot and the button(s) that belong to it
    in the SAME subfolder under templates/. The lowest-priority _noclick
    file in that folder is treated as the section's anchor: its detected
    bounding box becomes the ONLY area searched for the other templates in
    that same folder. If the anchor isn't currently on screen, those
    templates are skipped entirely that cycle — so a visually identical
    button sitting in a different, unrelated section will never match.

    Example:
        templates/
            01_main_menu_click.png                  <- global scope
            tailed_beast_section/
                02_hard_section_noclick.png          <- anchor for this folder
                03_tailed_beast_button_click.png     <- only searched INSIDE
                                                         the anchor's box
            another_boss_section/
                02_boss_room_noclick.png             <- different anchor
                03_attack_button_click.png           <- scoped to ITS OWN box,
                                                         even if the button
                                                         image looks identical
                                                         to the one above

    Subfolders can be nested (a subfolder inside a subfolder) and each
    level's anchor box is resolved inside its parent's box first.

Setup:
    pip install -r requirements.txt

Usage:
    1. Build out ./templates/ with top-level files and/or section subfolders.
    2. Run: python ninja_clicker.py
    3. Add/remove/rename files or folders any time — rescanned every
       RELOAD_INTERVAL seconds automatically.
    4. F7 = reload templates now, F8 = pause/resume, F9 = quit.
       Mouse to a screen corner also aborts immediately (PyAutoGUI failsafe).
"""

import re
import time
from pathlib import Path

import pyautogui
import keyboard  # hotkeys

pyautogui.FAILSAFE = True

TEMPLATES_DIR = Path("templates")
DEFAULT_CONFIDENCE = 0.85
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}

SCAN_INTERVAL = 0.15      # seconds between screen scans (replaces your fixed delay)
CLICK_COOLDOWN = 0.5      # minimum seconds between two clicks (avoids double-firing)
RELOAD_INTERVAL = 3.0     # seconds between rescans of the templates folder
REGION = None             # e.g. (x, y, width, height) to limit the GLOBAL search area

paused = False
running = True
force_reload = False

NAME_PATTERN = re.compile(
    r"^(?:(?P<priority>\d+)_)?(?P<name>.+?)(?:@(?P<conf>0?\.\d+))?(?:_(?P<flag>click|noclick))?$"
)


def parse_template(path: Path):
    stem = path.stem
    m = NAME_PATTERN.match(stem)
    priority = int(m.group("priority")) if m and m.group("priority") else 10_000
    name = m.group("name") if m else stem
    confidence = float(m.group("conf")) if m and m.group("conf") else DEFAULT_CONFIDENCE
    should_click = not (m and m.group("flag") == "noclick")

    rel_parent = path.parent.relative_to(TEMPLATES_DIR)
    scope = "" if rel_parent == Path(".") else rel_parent.as_posix()
    parent_scope = "" if Path(scope).parent == Path(".") else Path(scope).parent.as_posix()
    depth = 0 if scope == "" else len(Path(scope).parts)

    return {
        "name": name,
        "path": str(path),
        "confidence": confidence,
        "priority": priority,
        "click": should_click,
        "scope": scope,
        "parent_scope": parent_scope,
        "depth": depth,
    }


def load_templates():
    if not TEMPLATES_DIR.exists():
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        return []
    files = sorted(
        (p for p in TEMPLATES_DIR.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.as_posix(),
    )
    templates = [parse_template(p) for p in files]
    templates.sort(key=lambda t: (t["priority"], t["name"]))
    return templates


def toggle_pause():
    global paused
    paused = not paused
    print("\n[PAUSED]" if paused else "\n[RESUMED]")


def stop():
    global running
    running = False
    print("\n[STOPPING]")


def request_reload():
    global force_reload
    force_reload = True


def locate(tpl, region):
    try:
        return pyautogui.locateOnScreen(
            tpl["path"], confidence=tpl["confidence"], region=region
        )
    except pyautogui.ImageNotFoundException:
        return None


def resolve_scope_regions(templates, seen_noclick):
    """
    Resolve each subfolder's search box, shallowest first, so a nested
    subfolder's anchor is searched inside its already-resolved parent box.
    Returns {scope: region_or_None}. "" (global) always maps to REGION.
    """
    region_cache = {"": REGION}

    scopes = sorted({t["scope"] for t in templates if t["scope"] != ""},
                     key=lambda s: len(Path(s).parts))

    # index anchor candidates (the lowest-priority _noclick file per scope)
    anchors = {}
    for t in templates:
        if t["scope"] and not t["click"]:
            if t["scope"] not in anchors or t["priority"] < anchors[t["scope"]]["priority"]:
                anchors[t["scope"]] = t

    for scope in scopes:
        parent_scope = _parent_of(scope)
        parent_region = region_cache.get(parent_scope)

        if parent_scope != "" and parent_region is None:
            # parent section isn't on screen, so this nested scope can't be either
            region_cache[scope] = None
            continue

        anchor = anchors.get(scope)
        if anchor is None:
            region_cache[scope] = None
            continue

        box = locate(anchor, parent_region)
        if box:
            if anchor["name"] not in seen_noclick:
                print(f"[DETECTED] {anchor['name']} (section anchor)")
                seen_noclick.add(anchor["name"])
            region_cache[scope] = tuple(box)
        else:
            seen_noclick.discard(anchor["name"])
            region_cache[scope] = None

    return region_cache


def _parent_of(scope):
    p = Path(scope).parent
    return "" if p == Path(".") else p.as_posix()


def scan_step(templates, seen_noclick):
    region_cache = resolve_scope_regions(templates, seen_noclick)

    for tpl in templates:
        region = region_cache.get(tpl["scope"], REGION if tpl["scope"] == "" else None)

        # top-level (non-scoped) noclick checkpoints: just log, don't stop the scan
        if not tpl["click"] and tpl["scope"] == "":
            box = locate(tpl, region)
            if box and tpl["name"] not in seen_noclick:
                print(f"[DETECTED] {tpl['name']} (no click)")
                seen_noclick.add(tpl["name"])
            elif not box and tpl["name"] in seen_noclick:
                seen_noclick.discard(tpl["name"])
            continue

        # scoped-folder anchors were already handled in resolve_scope_regions
        if not tpl["click"] and tpl["scope"] != "":
            continue

        if not tpl["click"]:
            continue

        if region is None and tpl["scope"] != "":
            # this template's section anchor isn't on screen right now -> skip
            continue

        box = locate(tpl, region)
        if box:
            center = pyautogui.center(box)
            pyautogui.click(center)
            print(f"[CLICK] {tpl['name']} at {center}")
            return True

    return False


def describe(templates):
    if not templates:
        return "(none — add screenshots to ./templates/)"
    return ", ".join(
        f"{t['priority']}:{t['scope'] or 'global'}/{t['name']}"
        f"({t['confidence']}, {'click' if t['click'] else 'no-click'})"
        for t in templates
    )


def main():
    global force_reload

    keyboard.add_hotkey("f7", request_reload)
    keyboard.add_hotkey("f8", toggle_pause)
    keyboard.add_hotkey("f9", stop)

    templates = load_templates()
    seen_noclick = set()

    print("Pockie Ninja Auto-Clicker running.")
    print("F7 = reload templates, F8 = pause/resume, F9 = quit.")
    print("Mouse to a screen corner = emergency stop.\n")
    print(f"[TEMPLATES] {describe(templates)}\n")

    last_click = 0.0
    last_reload = time.time()

    while running:
        now = time.time()

        if force_reload or (now - last_reload >= RELOAD_INTERVAL):
            new_templates = load_templates()
            if new_templates != templates:
                templates = new_templates
                seen_noclick.clear()
                print(f"[RELOADED] {describe(templates)}")
            last_reload = now
            force_reload = False

        if not paused and templates:
            if now - last_click >= CLICK_COOLDOWN:
                if scan_step(templates, seen_noclick):
                    last_click = now

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()