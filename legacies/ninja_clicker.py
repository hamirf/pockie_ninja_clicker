"""
Pockie Ninja Auto-Clicker
----------------------------------------------------------------------
Detects on-screen elements (bosses, buildings, buttons, icons) using
template matching via OpenCV + PyAutoGUI, and clicks them as soon as they
appear — reacting to what's on screen instead of waiting on a fixed timer.

Templates load dynamically from ./templates/ — drop a new screenshot in
there while the script is running and it's picked up automatically.

FILE NAMING:
    <priority>_<name>[@confidence][_click|_noclick][_satNN][_delayNN].<ext>

    priority     : number controlling check order — lower is checked first
    name         : just used in the console log
    @confidence  : optional, defaults to DEFAULT_CONFIDENCE
    _click       : (default) click the element when found
    _noclick     : only detect it, never click — a checkpoint, OR (when
                   it's the anchor of a section folder, see below) the box
                   that scopes where its sibling templates are searched for
    _satNN       : (click templates only) require the matched spot to have
                   an average color saturation of at least NN (0-255) to
                   count as a real hit. Fixes the "enabled vs. grayed-out
                   disabled icon with identical artwork" problem: shape-only
                   matching can't tell them apart (and will happily grab
                   whichever copy it scans first, which is usually the
                   leftmost/disabled one) — a saturation check can. When
                   set, ALL on-screen matches of that shape are found and
                   the most saturated one that clears the bar gets clicked.
                   Start around _sat40 and tune after checking real numbers.
    _delayNN     : (click templates only) after THIS template is clicked,
                   wait NN milliseconds before the next click is allowed —
                   instead of the global CLICK_COOLDOWN. Use a longer delay
                   after buttons that trigger an animation/dialog (e.g. a
                   "Close" button) and leave others at the default.

    IMPORTANT: crop templates tightly around just the one icon/button you
    want to target. A crop that includes neighboring icons/buttons will
    only match where that exact multi-element arrangement repeats (or,
    worse, cause weird false positives) — it will not behave like "find
    this one icon". One tightly-cropped icon + a _sat filter is the right
    tool for "pick the colorful one out of a row of look-alikes".

SCOPING TO A SECTION (restrict a template to one area of the screen):
    Two ways to scope a subfolder's templates to one area of the screen —
    pick whichever fits:

    A) IMAGE ANCHOR (content-based, adapts if the UI moves):
       Put a section's anchor screenshot and the button(s)/icon(s) that
       belong to it in the SAME subfolder under templates/. The lowest-
       priority _noclick file in that folder is the section's anchor: its
       detected bounding box becomes the ONLY area searched for the other
       templates in that folder. If the anchor isn't on screen, those
       templates are skipped entirely that cycle.

    B) FIXED region.txt (position-based, immune to changing text/numbers):
       Put a "region.txt" file (format: x,y,width,height in screen pixels)
       directly inside the subfolder. That fixed box is used instead of
       looking for a _noclick anchor at all. Use this when a section's
       ON-SCREEN POSITION never changes but its CONTENT does — e.g. three
       stacked difficulty rows (Rampage/Hard/Normal) that only differ by
       Level/Honor/Damage numbers: an anchor screenshot of "Normal" will
       stop matching the moment those numbers change, but a fixed region
       for "wherever the bottom row always sits" never goes stale.
       Use find_coords.py to read pixel coordinates off your screen.

    Example (fixed region for a row whose numbers keep changing):
        templates/
            tailed_beast_normal/
                region.txt                        <- "480,610,320,60" etc.
                03_fight_button_click.png          <- only searched inside that box

    Example (image anchor for a row that stays visually constant):
        templates/
            01_stage_banner_click.png            <- click to open the stage
            02_close_button_click_delay800.png   <- global; waits 800ms after clicking
            battle_icons/
                03_row_anchor_noclick.png         <- anchor for this folder
                04_active_icon_click_sat40.png    <- searched INSIDE the anchor's
                                                      box; only the colorful
                                                      (enabled) icon is clicked,
                                                      not its grayed-out copies

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

import numpy as np
import pyautogui
import pyscreeze
import keyboard  # hotkeys

pyautogui.FAILSAFE = True

# Depending on installed pyautogui/pyscreeze versions, the "not found" exception
# raised isn't always the same class as the pyautogui.ImageNotFoundException
# alias, so catch both explicitly everywhere we call a locate function.
NOT_FOUND_EXCEPTIONS = (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException)

TEMPLATES_DIR = Path("templates")
DEFAULT_CONFIDENCE = 0.85
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}

SCAN_INTERVAL = 0.15      # seconds between screen scans (replaces your fixed delay)
CLICK_COOLDOWN = 0.5      # default minimum seconds between two clicks (see _delayNN to override per step)
RELOAD_INTERVAL = 3.0     # seconds between rescans of the templates folder
REGION = None             # e.g. (x, y, width, height) to limit the GLOBAL search area
REGION_FILENAME = "region.txt"  # optional per-folder fixed-region override (see docstring)

paused = False
running = True
force_reload = False

NAME_PATTERN = re.compile(
    r"^(?:(?P<priority>\d+)_)?(?P<name>.+?)(?:@(?P<conf>0?\.\d+))?"
    r"(?:_(?P<flag>click|noclick))?(?:_sat(?P<sat>\d+))?(?:_delay(?P<delay>\d+))?$"
)


def parse_template(path: Path):
    stem = path.stem
    m = NAME_PATTERN.match(stem)
    priority = int(m.group("priority")) if m and m.group("priority") else 10_000
    name = m.group("name") if m else stem
    confidence = float(m.group("conf")) if m and m.group("conf") else DEFAULT_CONFIDENCE
    should_click = not (m and m.group("flag") == "noclick")
    min_saturation = int(m.group("sat")) if m and m.group("sat") else 0
    delay_ms = int(m.group("delay")) if m and m.group("delay") else None

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
        "min_saturation": min_saturation,
        "delay": (delay_ms / 1000.0) if delay_ms is not None else None,
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


warned_region_too_small = set()


def locate(tpl, region):
    try:
        return pyautogui.locateOnScreen(
            tpl["path"], confidence=tpl["confidence"], region=region
        )
    except NOT_FOUND_EXCEPTIONS:
        return None
    except ValueError:
        if tpl["name"] not in warned_region_too_small:
            print(f"[WARN] {tpl['name']}: search area (region.txt or scope) is smaller than "
                  f"the template image — widen it. Skipping this template until fixed.")
            warned_region_too_small.add(tpl["name"])
        return None


def average_saturation(box):
    """Mean HSV saturation (0-255) of the screen region inside box. Higher = more colorful."""
    region = tuple(int(v) for v in box)
    img = pyautogui.screenshot(region=region)
    hsv = np.array(img.convert("HSV"))
    return float(hsv[..., 1].mean())


def locate_colorful(tpl, region):
    """
    For templates with a min_saturation requirement: finds every on-screen
    match of the shape, then returns the most saturated one that clears the
    threshold (skipping grayed-out/disabled copies of the same icon).
    Returns None if nothing qualifies.
    """
    try:
        boxes = list(pyautogui.locateAllOnScreen(
            tpl["path"], confidence=tpl["confidence"], region=region
        ))
    except NOT_FOUND_EXCEPTIONS:
        boxes = []
    except ValueError:
        if tpl["name"] not in warned_region_too_small:
            print(f"[WARN] {tpl['name']}: search area (region.txt or scope) is smaller than "
                  f"the template image — widen it. Skipping this template until fixed.")
            warned_region_too_small.add(tpl["name"])
        boxes = []

    if not boxes:
        return None

    candidates = [(b, average_saturation(b)) for b in boxes]
    candidates = [c for c in candidates if c[1] >= tpl["min_saturation"]]
    if not candidates:
        return None

    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates[0][0]


def resolve_scope_regions(templates, seen_noclick):
    """
    Resolve each subfolder's search box, shallowest first, so a nested
    subfolder's anchor is searched inside its already-resolved parent box.
    Returns {scope: region_or_None}. "" (global) always maps to REGION.
    """
    region_cache = {"": REGION}

    scopes = sorted({t["scope"] for t in templates if t["scope"] != ""},
                     key=lambda s: len(Path(s).parts))

    anchors = {}
    for t in templates:
        if t["scope"] and not t["click"]:
            if t["scope"] not in anchors or t["priority"] < anchors[t["scope"]]["priority"]:
                anchors[t["scope"]] = t

    for scope in scopes:
        parent_scope = _parent_of(scope)
        parent_region = region_cache.get(parent_scope)

        if parent_scope != "" and parent_region is None:
            region_cache[scope] = None
            continue

        manual_region = load_manual_region(scope)
        if manual_region is not None:
            region_cache[scope] = manual_region
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
            region_cache[scope] = tuple(int(v) for v in box)
        else:
            seen_noclick.discard(anchor["name"])
            region_cache[scope] = None

    return region_cache


def _parent_of(scope):
    p = Path(scope).parent
    return "" if p == Path(".") else p.as_posix()


def load_manual_region(scope: str):
    """
    If templates/<scope>/region.txt exists (format: "x,y,width,height"),
    that fixed pixel box is used as this scope's search area instead of
    detecting a _noclick anchor image. Use this when the section's position
    on screen is stable but its content (numbers, stats) changes over time,
    which would make an image-based anchor go stale.
    """
    region_file = TEMPLATES_DIR / scope / REGION_FILENAME
    if not region_file.exists():
        return None
    try:
        parts = [int(p.strip()) for p in region_file.read_text().strip().split(",")]
        if len(parts) != 4:
            raise ValueError
        return tuple(parts)
    except ValueError:
        print(f"[WARN] {region_file} must contain 4 comma-separated ints: x,y,width,height")
        return None


def scan_step(templates, seen_noclick):
    """
    Walk the sequence in priority order. Returns the template dict that
    was clicked, or None if nothing was clicked this cycle.
    """
    region_cache = resolve_scope_regions(templates, seen_noclick)

    for tpl in templates:
        region = region_cache.get(tpl["scope"], REGION if tpl["scope"] == "" else None)

        if not tpl["click"] and tpl["scope"] == "":
            box = locate(tpl, region)
            if box and tpl["name"] not in seen_noclick:
                print(f"[DETECTED] {tpl['name']} (no click)")
                seen_noclick.add(tpl["name"])
            elif not box and tpl["name"] in seen_noclick:
                seen_noclick.discard(tpl["name"])
            continue

        if not tpl["click"]:
            continue  # scoped-folder anchors are already handled above

        if region is None and tpl["scope"] != "":
            continue  # this template's section anchor isn't on screen right now

        box = locate_colorful(tpl, region) if tpl["min_saturation"] > 0 else locate(tpl, region)

        if box:
            center = pyautogui.center(box)
            pyautogui.click(center)
            print(f"[CLICK] {tpl['name']} at {center}")
            return tpl

    return None


def describe(templates):
    if not templates:
        return "(none — add screenshots to ./templates/)"
    parts = []
    for t in templates:
        extras = []
        if t["min_saturation"]:
            extras.append(f"sat>={t['min_saturation']}")
        if t["delay"] is not None:
            extras.append(f"delay={int(t['delay'] * 1000)}ms")
        extra_str = f", {', '.join(extras)}" if extras else ""
        parts.append(
            f"{t['priority']}:{t['scope'] or 'global'}/{t['name']}"
            f"({t['confidence']}, {'click' if t['click'] else 'no-click'}{extra_str})"
        )
    return ", ".join(parts)


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
    current_cooldown = CLICK_COOLDOWN
    last_reload = time.time()

    while running:
        now = time.time()

        if force_reload or (now - last_reload >= RELOAD_INTERVAL):
            new_templates = load_templates()
            if new_templates != templates:
                templates = new_templates
                seen_noclick.clear()
                warned_region_too_small.clear()
                print(f"[RELOADED] {describe(templates)}")
            last_reload = now
            force_reload = False

        if not paused and templates:
            if now - last_click >= current_cooldown:
                clicked = scan_step(templates, seen_noclick)
                if clicked:
                    last_click = now
                    current_cooldown = clicked["delay"] if clicked["delay"] is not None else CLICK_COOLDOWN

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()