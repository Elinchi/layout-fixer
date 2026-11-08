"""Minimal Hyprland IPC: commands on .socket.sock, events from .socket2.sock."""

import json
import os
import socket


def _dir():
    return os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr",
                        os.environ["HYPRLAND_INSTANCE_SIGNATURE"])


def command(cmd: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(os.path.join(_dir(), ".socket.sock"))
        s.sendall(cmd.encode())
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out.decode(errors="replace")


def query(what: str):
    return json.loads(command("j/" + what))


def events():
    """Yield (name, data) for every Hyprland event, forever."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(os.path.join(_dir(), ".socket2.sock"))
        buf = b""
        while chunk := s.recv(4096):
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                name, _, data = line.decode(errors="replace").partition(">>")
                yield name, data


def device_name(evdev_name: str) -> str:
    """Hyprland's name for an evdev device: 'Logitech G512 X' -> 'logitech-g512-x'."""
    return evdev_name.lower().replace(" ", "-")


def layouts() -> list[str]:
    """Configured layout codes in index order, e.g. ['us', 'ua']."""
    for kb in query("devices")["keyboards"]:
        return kb["layout"].split(",")
    return []


def keymaps() -> dict[str, str]:
    """Hyprland keyboard name -> active keymap name ('English (US)', 'Ukrainian')."""
    return {kb["name"]: kb["active_keymap"] for kb in query("devices")["keyboards"]}


def switch_layout(index: int) -> None:
    command(f"switchxkblayout all {index}")


def active_window() -> dict:
    return query("activewindow")
