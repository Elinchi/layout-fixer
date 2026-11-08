# layout-fixer

Detects words typed in the wrong keyboard layout (us ↔ ua), Punto Switcher style.
A user service reads the physical keyboards (evdev), and when a finished word is in
the wrong layout it erases it, switches the layout (Hyprland, all devices) and
retypes the same keys through a virtual keyboard.

Ukrainian: виправляє слова, набрані не в тій розкладці (`ghbdsn` → `привіт`), прямо
під час набору або за комбінацією клавіш; конвертує виділений текст.

## Requirements
Hyprland (Wayland), layouts `us` and `ua` in `kb_layout`, Python 3.12+, `python-evdev`,
`wl-clipboard`, `libnotify`, GTK4 + libadwaita (`python-gobject`) for the settings window,
and your user in the `input` group (to read keyboards and create the virtual one).

## Install
    git clone https://github.com/Elinchi/layout-fixer && cd layout-fixer
    ./install.sh

The first run downloads the Leipzig corpora (~80 MB) and builds the model locally
(it also learns package and command names from your own system, so it is not shipped).

## Use
    layout-fixer settings        # settings window (also in the app launcher)
    layout-fixer status | log | toggle | mode auto|manual|log

Default hotkeys (not swallowed, so they must be harmless keys):
- double Shift: fix the last word; again right after = undo (and remember the word)
- double Ctrl: convert the selected text
- Shift+Pause: auto mode on/off

Auto mode is off in terminals/editors/password managers (hotkeys still work) and
completely off in games, including everything launched from a Steam library.
Nothing typed is written to disk; the log mode keeps its notes in memory only.

## How it decides
Every word is read both ways (`ghbdsn` / `привіт`) and scored with character
trigram models for en and uk. It switches only when the current reading is clearly
worse: never for a known word, a package/command name, or anything with digits.
Short words and ACRONYMS need a frequent real word on the other side.
Slang and surzhyk work without a dictionary because their letter combinations are
normal for Ukrainian.

## Files
- `src/daemon.py`: devices, Hyprland events, grabs keyboards while retyping
- `src/engine.py`: typing state machine, actions, learning
- `src/settings.py`: GTK4/libadwaita settings window
- `src/cli.py`: `layout-fixer` command
- `src/layouts.py`: us/ua key maps (xkb `ua` default variant)
- `src/model.py`: training, scoring, `decide(keys, current_layout, model)`
- `src/train.py`: builds `data/model.json.gz` (~1 MB, ~20 s)
- `data/lexicon/{en,uk}.txt`: your own extra words, edit freely
- `tests/eval.py`: false-switch / missed rates on held-out text
- `tests/cases.txt`: hand-written cases
- `tests/sentences.py`: whole mixed-language sentences
- `tests/test_engine.py`: typing scenarios against a fake screen

## Personal training data (optional)
Telegram Desktop → Settings → Advanced → Export Telegram data → only messages
(no media), format **JSON**. Then:

    layout-fixer train --extra ~/Downloads/Telegram\ Desktop/DataExport_*/result.json:5
    python tests/eval.py && python tests/sentences.py

Only your own messages are used, and everything stays local.

## Data
Corpora: [Leipzig Corpora Collection](https://wortschatz.uni-leipzig.de/en/download), downloaded at install time, not redistributed.
