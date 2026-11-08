"""Settings (~/.config/layout-fixer/config.json) and learned words."""

import json
import os

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                          "layout-fixer")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                        "layout-fixer")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LEARNED_PATH = os.path.join(DATA_DIR, "learned.json")
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "layout-fixer.sock")

MODES = ("auto", "manual", "log")

# Hotkey specs: "double:shift" / "double:ctrl" (two quick taps of the key alone),
# or "mod+...+KEY" with evdev key names, e.g. "pause", "shift+pause", "shift+tab".
HOTKEY_PRESETS = ["double:shift", "double:ctrl", "pause", "shift+pause", "ctrl+pause",
                  "alt+pause", "shift+tab", "none"]

DEFAULTS = {
    "mode": "auto",
    "hotkeys": {
        "fix_last": "double:shift",
        "fix_selection": "double:ctrl",
        "toggle_auto": "shift+pause",
    },
    # Window classes (regex, full match) where auto mode stays off; hotkeys still work.
    "exclude": [
        "com.mitchellh.ghostty", "kitty", "Alacritty", "foot", "org.wezfurlong.wezterm",
        "code", "Code", "code-oss", "codium", "VSCodium", "dev.zed.Zed", "jetbrains-.*",
        "neovide", "org.keepassxc.KeePassXC", "1Password",
    ],
    # Games: everything off, hotkeys too (double Shift is sprint/sneak there).
    # Anything launched from a Steam library is treated as a game as well.
    "games": ["steam_app_.*", "gamescope", "cs2", "dota2", "[Mm]inecraft.*", "osu!"],
    "auto_in_fullscreen": False,
    "notify": True,
    "learn": True,
    "double_tap_ms": 350,
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, ValueError):
        return cfg
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if cfg["mode"] not in MODES:
        cfg["mode"] = "auto"
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def load_learned() -> dict:
    try:
        with open(LEARNED_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {"keep": d.get("keep", []), "switch": d.get("switch", []),
            "manual": d.get("manual", {})}


def save_learned(d: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = LEARNED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEARNED_PATH)
