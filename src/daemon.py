"""The background service: wires real devices, Hyprland and the Engine together."""

import asyncio
import json
import logging
import os
import subprocess
import threading
import time

import evdev
from evdev import ecodes as e

import config
import hypr
from engine import Engine
from keyboard import DEVICE_NAME, Typist
from model import Model

log = logging.getLogger("layout-fixer")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORED_DEVICES = {DEVICE_NAME, "ydotoold virtual device"}
TERMINALS = ("ghostty", "kitty", "alacritty", "foot", "wezterm", "konsole", "terminal")


def model_path():
    for p in (os.path.join(config.DATA_DIR, "model.json.gz"),
              os.path.join(ROOT, "data/model.json.gz")):
        if os.path.exists(p):
            return p
    raise SystemExit("model.json.gz not found: run `layout-fixer train`")


class Layout:
    """Which layout each keyboard is in, from Hyprland keymap names."""

    def __init__(self):
        self.codes = hypr.layouts()                       # e.g. ['us', 'ua']
        self.keymaps = hypr.keymaps()
        self.last = next((km for name, km in self.keymaps.items()
                          if "keyboard" in name and "virtual" not in name), None)

    @staticmethod
    def _lang(keymap: str | None):
        if not keymap:
            return None
        if keymap.startswith("Ukrainian"):
            return "uk"
        if keymap.startswith("English"):
            return "en"
        return None

    def on_event(self, data: str):
        name, _, keymap = data.rpartition(",")
        self.keymaps[name] = keymap
        if not name.startswith("layout-fixer"):
            self.last = keymap

    def lang(self, evdev_name):
        km = self.keymaps.get(hypr.device_name(evdev_name)) if evdev_name else None
        return self._lang(km or self.last)

    def switch(self, lang):
        code = "us" if lang == "en" else "ua"
        if code in self.codes:
            hypr.switch_layout(self.codes.index(code))
            km = "English (US)" if lang == "en" else "Ukrainian"
            self.keymaps = {k: km for k in self.keymaps}
            self.last = km


class Clipboard:
    def primary(self) -> str:
        try:
            return subprocess.run(["wl-paste", "--primary", "--no-newline"], capture_output=True,
                                  text=True, timeout=1).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def paste(self, text, window_class):
        """Put text on the clipboard, paste it, then restore the old clipboard."""
        try:
            old = subprocess.run(["wl-paste", "--no-newline"], capture_output=True,
                                 timeout=1).stdout
        except (OSError, subprocess.TimeoutExpired):
            old = None
        subprocess.run(["wl-copy"], input=text.encode(), timeout=2)
        time.sleep(0.05)
        terminal = any(t in window_class.lower() for t in TERMINALS)
        mods = (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT) if terminal else (e.KEY_LEFTCTRL,)
        self.typist.tap(e.KEY_V, *mods)
        if old is not None:
            time.sleep(0.3)
            subprocess.run(["wl-copy"], input=old, timeout=2)


def is_game(pid: int) -> bool:
    """Anything started from a Steam library (native or Proton) counts as a game,
    windowed or not: auto-fixing would type Backspaces into it."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read()
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return False
    return b"steamapps" in cmd or "steamapps" in exe


def is_terminal(win: dict) -> bool:
    """By class or by executable: org.omarchy.agent is Ghostty under another class."""
    try:
        exe = os.path.basename(os.readlink(f"/proc/{win.get('pid', 0)}/exe"))
    except OSError:
        exe = ""
    return any(t in win.get("class", "").lower() or t in exe for t in TERMINALS)


def notify_fn(cfg):
    def notify(text):
        if cfg["notify"]:
            subprocess.Popen(["notify-send", "-a", "Layout Fixer", "-t", "2500",
                              "-i", "input-keyboard", "Розкладка", text])
    return notify


class Daemon:
    def __init__(self):
        cfg = config.load()
        self.typist = Typist()
        self.clipboard = Clipboard()
        self.clipboard.typist = self.typist
        self.layout = Layout()
        self.model = Model.load(model_path())
        self.engine = Engine(self.model, cfg, config.load_learned(), self.typist, self.layout,
                             self.clipboard, notify_fn(cfg), config.save, config.save_learned)
        self.keyboards: dict[str, evdev.InputDevice] = {}
        self.pointers: dict[str, evdev.InputDevice] = {}
        self.virtual_held: set[int] = set()
        self.loop = None

    # ---- devices --------------------------------------------------------
    def scan(self):
        for path in evdev.list_devices():
            if path in self.keyboards or path in self.pointers:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            keys = dev.capabilities().get(e.EV_KEY, [])
            if dev.name in IGNORED_DEVICES:
                dev.close()
            elif e.KEY_A in keys and e.KEY_SPACE in keys:
                self.keyboards[path] = dev
                self.loop.add_reader(dev.fd, self.read, dev, True)
                log.info("keyboard: %s", dev.name)
            elif e.BTN_LEFT in keys:
                self.pointers[path] = dev
                self.loop.add_reader(dev.fd, self.read, dev, False)
            else:
                dev.close()

    def drop(self, dev):
        self.loop.remove_reader(dev.fd)
        self.keyboards.pop(dev.path, None)
        self.pointers.pop(dev.path, None)
        try:
            dev.close()
        except OSError:
            pass

    def read(self, dev, is_keyboard):
        try:
            events = list(dev.read())
        except BlockingIOError:
            return
        except OSError:
            self.drop(dev)
            return
        for ev in events:
            if ev.type != e.EV_KEY:
                continue
            if not is_keyboard:
                if ev.value == 1:
                    self.engine.reset("click")
                continue
            self.key(ev.code, ev.value, dev.name)
        self.maybe_run()

    def key(self, code, value, name):
        self.engine.on_key(code, value, name)
        # A key we pressed on our virtual device during a grab is released here.
        if value == 0 and code in self.virtual_held:
            self.virtual_held.discard(code)
            self.typist.ui.write(e.EV_KEY, code, 0)
            self.typist.ui.syn()

    def maybe_run(self):
        """Run a pending fix once no key is held, with keyboards grabbed so keys
        typed meanwhile are queued and replayed after it instead of interleaving."""
        if not self.engine.pending:
            return
        if self.engine.held:
            # Trust the devices over our bookkeeping (a lost release must not block fixes).
            actual = set()
            for dev in self.keyboards.values():
                try:
                    actual |= set(dev.active_keys())
                except OSError:
                    pass
            self.engine.held = actual
            if actual:
                return
        grabbed = []
        try:
            for dev in self.keyboards.values():
                try:
                    dev.grab()
                    grabbed.append(dev)
                except OSError:
                    pass
            self.engine.run_pending()
            queued = []
            for dev in grabbed:
                try:
                    queued += [(ev, dev.name) for ev in dev.read() if ev.type == e.EV_KEY]
                except (BlockingIOError, OSError):
                    pass
        finally:
            for dev in grabbed:
                try:
                    dev.ungrab()
                except OSError:
                    pass
        for ev, name in sorted(queued, key=lambda q: q[0].timestamp()):
            if ev.value == 0 and ev.code not in self.virtual_held:
                continue   # pressed before the grab: its physical release is lost
            self.typist.ui.write(e.EV_KEY, ev.code, ev.value)
            self.typist.ui.syn()
            if ev.value == 1:
                self.virtual_held.add(ev.code)
            elif ev.value == 0:
                self.virtual_held.discard(ev.code)
            self.engine.on_key(ev.code, ev.value, name)
        if self.engine.pending and not self.engine.held:
            self.maybe_run()

    # ---- Hyprland -------------------------------------------------------
    def hypr_thread(self):
        while True:
            try:
                for name, data in hypr.events():
                    if name in ("activelayout", "activewindow", "fullscreen"):
                        self.loop.call_soon_threadsafe(self.hypr_event, name, data)
            except OSError as err:
                log.warning("hyprland events: %s", err)
            time.sleep(2)

    def hypr_event(self, name, data):
        if name == "activelayout":
            self.layout.on_event(data)
            return
        self.window_changed()

    def window_changed(self):
        try:
            win = hypr.active_window()
        except (OSError, ValueError):
            win = {}
        game = is_game(win.get("pid", 0)) or win.get("contentType") == "game"
        self.typist.delay = Typist.TERMINAL if is_terminal(win) else Typist.FAST
        self.engine.on_window(win.get("class", ""), bool(win.get("fullscreen")), game,
                              win.get("address", ""))

    # ---- primary selection ---------------------------------------------
    async def watch_selection(self):
        while True:
            proc = await asyncio.create_subprocess_exec(
                "wl-paste", "--primary", "--watch", "echo", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            first = True
            while await proc.stdout.readline():
                if not first:                 # the first line is the existing selection
                    self.engine.on_selection()
                first = False
            await proc.wait()
            await asyncio.sleep(3)

    # ---- control socket -------------------------------------------------
    async def control(self, reader, writer):
        line = (await reader.readline()).decode().strip()
        cmd, _, arg = line.partition(" ")
        eng = self.engine
        reply = {"ok": True}
        if cmd == "status":
            reply.update(mode=eng.cfg["mode"], window=eng.window_class,
                         auto_here=eng.auto_allowed(), game=eng.game, layout=self.layout.lang(eng.device),
                         keyboards=[d.name for d in self.keyboards.values()],
                         learned={k: len(eng.learned[k]) for k in ("keep", "switch")})
        elif cmd == "log":
            reply["log"] = list(eng.log)
        elif cmd == "reload":
            cfg = config.load()
            eng.notify = notify_fn(cfg)
            eng.configure(cfg, config.load_learned())
        elif cmd == "mode" and arg in config.MODES:
            eng.cfg["mode"] = arg
            config.save(eng.cfg)
        elif cmd in ("toggle", "fix-last", "fix-selection"):
            eng.trigger({"toggle": "toggle_auto", "fix-last": "fix_last",
                         "fix-selection": "fix_selection"}[cmd])
            self.maybe_run()
        else:
            reply = {"ok": False, "error": f"unknown command: {line}"}
        writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        writer.close()

    async def rescan(self):
        while True:
            await asyncio.sleep(3)
            self.scan()

    async def main(self):
        self.loop = asyncio.get_running_loop()
        self.window_changed()
        self.scan()
        if not self.keyboards:
            log.error("no keyboards readable: is the user in the 'input' group?")
        threading.Thread(target=self.hypr_thread, daemon=True).start()
        if os.path.exists(config.SOCKET_PATH):
            os.unlink(config.SOCKET_PATH)
        server = await asyncio.start_unix_server(self.control, config.SOCKET_PATH)
        log.info("running, mode=%s", self.engine.cfg["mode"])
        async with server:
            await asyncio.gather(self.watch_selection(), self.rescan())


def run():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    d = Daemon()
    try:
        asyncio.run(d.main())
    finally:
        d.typist.close()
