"""
Pockie Ninja Auto-Clicker
----------------------------------------------------------------------
Detects on-screen elements (bosses, buildings, buttons, icons) using
multi-scale template matching (OpenCV) and clicks them as soon as they
appear -- reacting to what's on screen instead of waiting on a fixed timer.

MULTIPLE MAPS (optional):
    If a top-level "maps/" folder exists, each of its direct subfolders is
    a separate, self-contained template profile (same internal structure
    as described below -- top-level files, section subfolders, config.json,
    region.txt, all of it). Only ONE map's templates are active/scanned at
    a time. Switch with:
        F5 = previous map     F6 = next map
    The currently active map is printed whenever you switch.

    maps/
        forest_map/
            01_stage_banner_click.png
            ...
        desert_map/
            01_stage_banner_click.png
            ...

    If "maps/" doesn't exist, the app just uses the single "templates/"
    folder as before -- nothing changes for a one-map setup.

CONFIG FILES (shorter filenames, with a global layer + per-map overrides):
    Instead of (or in addition to) encoding settings in the filename, two
    JSON config files can set them explicitly. They stack, least to most
    specific -- a later layer only overrides the keys it actually sets:

        1. filename tags (see below)
        2. global_config.json  at the PROJECT ROOT (next to auto_clicker_opencv.py,
           sibling of templates/ and maps/) -- applies to EVERY map/profile
        3. config.json  at the root of ONE profile (templates/config.json,
           or maps/<map>/config.json) -- overrides the global file, but
           only for that one map

    Both files use the same shape:

        {
          "_defaults": { "confidence": 0.88 },
          "close_button.png": { "priority": 2, "delay_ms": 800 },
          "battle_icons/active_icon.png": {
            "priority": 3, "min_saturation": 40, "pre_delay_ms": 500
          }
        }

    "_defaults" applies to every template in scope (every map, for
    global_config.json; just that one map, for a profile's config.json)
    unless a specific entry overrides it. In global_config.json, a
    per-file entry's key is prefixed with the map's folder name, e.g.
    "forest_map/battle_icons/active_icon.png" (no prefix needed in
    single-profile/templates-only mode). Recognized settings: confidence
    (float), click (true/false), min_saturation (int 0-255),
    pre_delay_ms (int), delay_ms (int), priority (int).

    Example: set min_saturation=40 for every map via global_config.json,
    but let one specific map use 60 instead via its own config.json --
    every other map keeps using the global 40.

        global_config.json:  { "_defaults": { "min_saturation": 40 } }
        maps/tailed_beast/config.json:  { "_defaults": { "min_saturation": 60 } }

FILE NAMING (still works, optional if you use config.json instead):
    <priority>_<name>[@confidence][_click|_noclick][_satNN][_predelayNN][_delayNN].<ext>

    priority     : number controlling check order -- lower is checked first
    name         : just used in the console log
    @confidence  : optional, defaults to DEFAULT_CONFIDENCE
    _click       : (default) click the element when found
    _noclick     : only detect it, never click -- a checkpoint, OR (when
                   it's the anchor of a section folder, see below) the box
                   that scopes where its sibling templates are searched for
    _satNN       : (click templates only) require the matched spot to have
                   an average color saturation of at least NN (0-255) --
                   picks the colorful (enabled) copy out of several
                   identical-shaped icons, skipping grayed-out ones.
    _predelayNN  : (click templates only) after the element is FOUND, wait
                   NN milliseconds, then re-check it's still there before
                   actually clicking.
    _delayNN     : (click templates only) after THIS template is clicked,
                   wait NN milliseconds before the next click is allowed --
                   instead of the global CLICK_COOLDOWN.

RESOLUTION / ZOOM INDEPENDENCE:
    Matching tries several scale factors of each template (see SCALES
    below) instead of only the exact pixel size it was captured at.
    Widen SCALES if your game window size varies a lot; narrow it for
    speed if it's always the same size.

SCOPING TO A SECTION (restrict a template to one area of the screen):
    A) IMAGE ANCHOR: the lowest-priority _noclick file in a subfolder is
       that section's anchor -- its detected box scopes where its sibling
       templates in the same folder are searched.
    B) FIXED region.txt: a "region.txt" (format: x,y,width,height) placed
       directly inside a subfolder fixes that folder's search area,
       bypassing anchor detection -- use this when a section's on-screen
       POSITION never changes but its CONTENT (numbers, stats) does.
       Use find_coords.py to read pixel coordinates off your screen, and
       make the box noticeably bigger than the templates searched inside it.

Setup:
    pip install -r requirements.txt

Usage:
    1. Build out ./templates/ (or ./maps/<name>/ for multiple maps).
    2. Run: python auto_clicker_opencv.py
    3. F5/F6 = switch map (if using maps/), F7 = reload templates now,
       F8 = pause/resume, F9 = quit.
       Mouse to a screen corner also aborts immediately (PyAutoGUI failsafe).
"""

import json
import re
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import keyboard  # hotkeys

pyautogui.FAILSAFE = True

TEMPLATES_DIR = Path("templates")   # single-profile (legacy) location
MAPS_DIR = Path("maps")             # optional multi-profile location
CONFIG_FILENAME = "config.json"             # per-profile (per-map, or templates/) overrides
GLOBAL_CONFIG_PATH = Path("global_config.json")  # applies to EVERY map/profile; per-map config.json can override it
REGION_FILENAME = "region.txt"
DEFAULT_CONFIDENCE = 0.85
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}

SCAN_INTERVAL = 0.15      # seconds between screen scans (replaces your fixed delay)
CLICK_COOLDOWN = 0.5      # default minimum seconds between two clicks (see delay_ms to override per step)
RELOAD_INTERVAL = 3.0     # seconds between rescans of the active profile's templates folder
REGION = None             # e.g. (x, y, width, height) to limit the GLOBAL search area

# Scale factors tried when matching, to tolerate the game being displayed at
# a different size/zoom than when the templates were captured.
SCALES = [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2]
NMS_IOU_THRESHOLD = 0.3   # overlap fraction above which two matches are considered duplicates

paused = False
running = True
force_reload = False
switch_profile_direction = 0  # set to +1 / -1 by hotkeys, consumed by main loop

NAME_PATTERN = re.compile(
    r"^(?:(?P<priority>\d+)_)?(?P<name>.+?)(?:@(?P<conf>0?\.\d+))?"
    r"(?:_(?P<flag>click|noclick))?(?:_sat(?P<sat>\d+))?"
    r"(?:_predelay(?P<predelay>\d+))?(?:_delay(?P<delay>\d+))?$"
)


# ---------------------------------------------------------------------------
# Profiles ("maps")
# ---------------------------------------------------------------------------

def list_profiles():
    """
    Returns (profiles, is_multi). profiles is a list of profile roots
    (Paths). is_multi is True if maps/ is in use (switching enabled).
    """
    if MAPS_DIR.exists():
        subdirs = sorted(p for p in MAPS_DIR.iterdir() if p.is_dir())
        if subdirs:
            return subdirs, True
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return [TEMPLATES_DIR], False


def request_next_profile():
    global switch_profile_direction
    switch_profile_direction = 1


def request_prev_profile():
    global switch_profile_direction
    switch_profile_direction = -1


# ---------------------------------------------------------------------------
# Config file + filename tag parsing
# ---------------------------------------------------------------------------

def load_profile_config(profile_root: Path):
    config_path = profile_root / CONFIG_FILENAME
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] failed to read {config_path}: {e}")
        return {}


def load_global_config():
    if not GLOBAL_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(GLOBAL_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] failed to read {GLOBAL_CONFIG_PATH}: {e}")
        return {}


def parse_template(path: Path, profile_root: Path, global_prefix: str, global_config: dict, profile_config: dict):
    stem = path.stem
    m = NAME_PATTERN.match(stem)
    priority = int(m.group("priority")) if m and m.group("priority") else 10_000
    name = m.group("name") if m else stem
    confidence = float(m.group("conf")) if m and m.group("conf") else DEFAULT_CONFIDENCE
    should_click = not (m and m.group("flag") == "noclick")
    min_saturation = int(m.group("sat")) if m and m.group("sat") else 0
    pre_delay = (int(m.group("predelay")) / 1000.0) if m and m.group("predelay") else 0.0
    delay_ms = int(m.group("delay")) if m and m.group("delay") else None
    delay = (delay_ms / 1000.0) if delay_ms is not None else None

    rel_path = path.relative_to(profile_root).as_posix()
    rel_parent = path.parent.relative_to(profile_root)
    scope = "" if rel_parent == Path(".") else rel_parent.as_posix()
    parent_scope = "" if Path(scope).parent == Path(".") else Path(scope).parent.as_posix()
    depth = 0 if scope == "" else len(Path(scope).parts)

    global_key = f"{global_prefix}/{rel_path}" if global_prefix else rel_path

    # merge order: global defaults -> global per-file -> profile defaults -> profile per-file
    # (each later layer overrides only the keys it actually sets)
    overrides = {}
    overrides.update(global_config.get("_defaults", {}))
    overrides.update(global_config.get(global_key, {}))
    overrides.update(profile_config.get("_defaults", {}))
    overrides.update(profile_config.get(rel_path, {}))

    if "confidence" in overrides:
        confidence = float(overrides["confidence"])
    if "click" in overrides:
        should_click = bool(overrides["click"])
    if "min_saturation" in overrides:
        min_saturation = int(overrides["min_saturation"])
    if "pre_delay_ms" in overrides:
        pre_delay = float(overrides["pre_delay_ms"]) / 1000.0
    if "delay_ms" in overrides:
        delay = float(overrides["delay_ms"]) / 1000.0
    if "priority" in overrides:
        priority = int(overrides["priority"])

    return {
        "name": name,
        "path": str(path),
        "confidence": confidence,
        "priority": priority,
        "click": should_click,
        "min_saturation": min_saturation,
        "pre_delay": pre_delay,
        "delay": delay,
        "scope": scope,
        "parent_scope": parent_scope,
        "depth": depth,
    }


def load_templates(profile_root: Path, global_prefix: str):
    if not profile_root.exists():
        profile_root.mkdir(parents=True, exist_ok=True)
        return []
    global_config = load_global_config()
    profile_config = load_profile_config(profile_root)
    files = sorted(
        (p for p in profile_root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.as_posix(),
    )
    templates = [parse_template(p, profile_root, global_prefix, global_config, profile_config) for p in files]
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


# ---------------------------------------------------------------------------
# Multi-scale template matching (own OpenCV implementation)
# ---------------------------------------------------------------------------

_template_cache = {}
_warned_names = set()


def clear_caches():
    _template_cache.clear()
    _warned_names.clear()


def _warn_once(name, message):
    if name not in _warned_names:
        print(f"[WARN] {name}: {message}")
        _warned_names.add(name)


def get_cv_template(path):
    if path not in _template_cache:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"could not read image: {path}")
        _template_cache[path] = img
    return _template_cache[path]


def _capture(region):
    try:
        img = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    except Exception:
        return None
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def find_matches(tpl, region, want_all):
    try:
        template_img = get_cv_template(tpl["path"])
    except FileNotFoundError as e:
        _warn_once(tpl["name"], str(e))
        return []

    haystack = _capture(region)
    if haystack is None:
        _warn_once(tpl["name"], "could not capture screen region")
        return []

    hh, hw = haystack.shape[:2]
    th0, tw0 = template_img.shape[:2]
    offset_x, offset_y = (int(region[0]), int(region[1])) if region else (0, 0)

    raw_matches = []
    for scale in SCALES:
        tw, th = int(round(tw0 * scale)), int(round(th0 * scale))
        if tw < 4 or th < 4 or tw > hw or th > hh:
            continue
        resized = cv2.resize(template_img, (tw, th))
        result = cv2.matchTemplate(haystack, resized, cv2.TM_CCOEFF_NORMED)

        if want_all:
            ys, xs = np.where(result >= tpl["confidence"])
            for x, y in zip(xs, ys):
                raw_matches.append((float(result[y, x]), int(x), int(y), tw, th))
        else:
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= tpl["confidence"]:
                raw_matches.append((float(max_val), int(max_loc[0]), int(max_loc[1]), tw, th))

    if not raw_matches:
        return []

    raw_matches.sort(key=lambda m: m[0], reverse=True)

    if not want_all:
        _, x, y, w, h = raw_matches[0]
        return [(offset_x + x, offset_y + y, w, h)]

    selected = []
    for _, x, y, w, h in raw_matches:
        box = (x, y, w, h)
        if not any(_iou(box, s) > NMS_IOU_THRESHOLD for s in selected):
            selected.append(box)

    return [(offset_x + x, offset_y + y, w, h) for (x, y, w, h) in selected]


def locate(tpl, region):
    matches = find_matches(tpl, region, want_all=False)
    return matches[0] if matches else None


def average_saturation(box):
    region = tuple(int(v) for v in box)
    img = pyautogui.screenshot(region=region)
    hsv = np.array(img.convert("HSV"))
    return float(hsv[..., 1].mean())


def locate_colorful(tpl, region):
    boxes = find_matches(tpl, region, want_all=True)
    if not boxes:
        return None
    candidates = [(b, average_saturation(b)) for b in boxes]
    candidates = [c for c in candidates if c[1] >= tpl["min_saturation"]]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates[0][0]


def find_box(tpl, region):
    return locate_colorful(tpl, region) if tpl["min_saturation"] > 0 else locate(tpl, region)


# ---------------------------------------------------------------------------
# Section scoping
# ---------------------------------------------------------------------------

def load_manual_region(scope: str, profile_root: Path):
    region_file = profile_root / scope / REGION_FILENAME
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


def _parent_of(scope):
    p = Path(scope).parent
    return "" if p == Path(".") else p.as_posix()


def resolve_scope_regions(templates, seen_noclick, profile_root):
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

        manual_region = load_manual_region(scope, profile_root)
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


def scan_step(templates, seen_noclick, profile_root):
    region_cache = resolve_scope_regions(templates, seen_noclick, profile_root)

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
            continue

        if region is None and tpl["scope"] != "":
            continue

        box = find_box(tpl, region)
        if not box:
            continue

        if tpl["pre_delay"] > 0:
            time.sleep(tpl["pre_delay"])
            box = find_box(tpl, region)
            if not box:
                print(f"[SKIP] {tpl['name']} disappeared during pre-click delay")
                continue

        center = pyautogui.center(box)
        pyautogui.click(center)
        print(f"[CLICK] {tpl['name']} at {center}")
        return tpl

    return None


def describe(templates):
    if not templates:
        return "(none -- add screenshots to this profile's folder)"
    parts = []
    for t in templates:
        extras = []
        if t["min_saturation"]:
            extras.append(f"sat>={t['min_saturation']}")
        if t["pre_delay"]:
            extras.append(f"predelay={int(t['pre_delay'] * 1000)}ms")
        if t["delay"] is not None:
            extras.append(f"delay={int(t['delay'] * 1000)}ms")
        extra_str = f", {', '.join(extras)}" if extras else ""
        parts.append(
            f"{t['priority']}:{t['scope'] or 'global'}/{t['name']}"
            f"({t['confidence']}, {'click' if t['click'] else 'no-click'}{extra_str})"
        )
    return ", ".join(parts)


def main():
    global force_reload, switch_profile_direction

    keyboard.add_hotkey("f5", request_prev_profile)
    keyboard.add_hotkey("f6", request_next_profile)
    keyboard.add_hotkey("f7", request_reload)
    keyboard.add_hotkey("f8", toggle_pause)
    keyboard.add_hotkey("f9", stop)

    profiles, is_multi = list_profiles()
    profile_index = 0
    profile_root = profiles[profile_index]
    global_prefix = profile_root.name if is_multi else ""

    templates = load_templates(profile_root, global_prefix)
    seen_noclick = set()

    print("Pockie Ninja Auto-Clicker running.")
    if is_multi:
        print(f"Maps available: {', '.join(p.name for p in profiles)}")
        print("F5 = previous map, F6 = next map.")
    print("F7 = reload templates, F8 = pause/resume, F9 = quit.")
    print("Mouse to a screen corner = emergency stop.\n")
    print(f"[MAP] {profile_root.name if is_multi else '(default)'}")
    print(f"[TEMPLATES] {describe(templates)}\n")

    last_click = 0.0
    current_cooldown = CLICK_COOLDOWN
    last_reload = time.time()

    while running:
        now = time.time()

        if switch_profile_direction != 0:
            if is_multi and len(profiles) > 1:
                profile_index = (profile_index + switch_profile_direction) % len(profiles)
                profile_root = profiles[profile_index]
                global_prefix = profile_root.name if is_multi else ""
                templates = load_templates(profile_root, global_prefix)
                seen_noclick.clear()
                clear_caches()
                last_reload = now
                print(f"\n[MAP] Switched to: {profile_root.name}")
                print(f"[TEMPLATES] {describe(templates)}\n")
            switch_profile_direction = 0

        if force_reload or (now - last_reload >= RELOAD_INTERVAL):
            new_templates = load_templates(profile_root, global_prefix)
            if new_templates != templates:
                templates = new_templates
                seen_noclick.clear()
                clear_caches()
                print(f"[RELOADED] {describe(templates)}")
            last_reload = now
            force_reload = False

        if not paused and templates:
            if now - last_click >= current_cooldown:
                clicked = scan_step(templates, seen_noclick, profile_root)
                if clicked:
                    last_click = now
                    current_cooldown = clicked["delay"] if clicked["delay"] is not None else CLICK_COOLDOWN

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
