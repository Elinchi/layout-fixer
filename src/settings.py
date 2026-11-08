"""Settings window (GTK4 + libadwaita). Every change is saved and applied at once."""

import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

import config  # noqa: E402
from cli import send  # noqa: E402

MODE_LABELS = {"auto": "Автоматично", "manual": "Тільки за комбінацією клавіш",
               "log": "Тест: нічого не міняти, лише записувати в журнал"}
HOTKEY_LABELS = {
    "double:shift": "Подвійний Shift", "double:ctrl": "Подвійний Ctrl", "pause": "Pause",
    "shift+pause": "Shift + Pause", "ctrl+pause": "Ctrl + Pause", "alt+pause": "Alt + Pause",
    "shift+tab": "Shift + Tab (у формах ще й перейде на попереднє поле)", "none": "Вимкнено",
}
ACTIONS = [
    ("fix_last", "Виправити останнє слово",
     "Повторне натискання одразу після виправлення його скасовує"),
    ("fix_selection", "Конвертувати виділений текст", "Спершу виділіть текст мишею"),
    ("toggle_auto", "Увімкнути / вимкнути автоматику", ""),
]
SERVICE = "layout-fixer.service"


def combo_row(title, subtitle, labels: dict, current: str, on_change):
    keys = list(labels)
    if current not in keys:
        keys.append(current)
    row = Adw.ComboRow(title=title, subtitle=subtitle,
                       model=Gtk.StringList.new([labels.get(k, k) for k in keys]))
    row.set_selected(keys.index(current))
    row.connect("notify::selected", lambda r, _: on_change(keys[r.get_selected()]))
    return row


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Розкладка: автовиправлення",
                         default_width=620, default_height=760)
        self.cfg = config.load()
        page = Adw.PreferencesPage()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.toasts = Adw.ToastOverlay(child=page)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

        # --- mode + service
        g = Adw.PreferencesGroup(title="Режим",
                                 description="Слова, набрані не в тій розкладці (ghbdsn → привіт)")
        g.add(combo_row("Як виправляти", "", MODE_LABELS, self.cfg["mode"],
                        lambda v: self.set("mode", v)))
        self.status = Adw.ActionRow(title="Служба")
        restart = Gtk.Button(label="Перезапустити", valign=Gtk.Align.CENTER)
        restart.connect("clicked", self.restart)
        self.status.add_suffix(restart)
        g.add(self.status)
        page.add(g)

        # --- hotkeys
        g = Adw.PreferencesGroup(
            title="Комбінації клавіш",
            description="Клавіші не перехоплюються, програма теж їх отримує. Тому подвійне "
                        "натискання Shift/Ctrl найзручніше: воно ніде нічого не робить.")
        for action, title, sub in ACTIONS:
            g.add(combo_row(title, sub, HOTKEY_LABELS, self.cfg["hotkeys"][action],
                            lambda v, a=action: self.set_hotkey(a, v)))
        page.add(g)

        # --- behaviour
        g = Adw.PreferencesGroup(title="Поведінка")
        for key, title, sub in [
            ("notify", "Сповіщення", "Про відкат, вивчене слово, перемикання автоматики"),
            ("learn", "Вчитися на моїх виправленнях",
             "Скасоване виправлення більше не повториться; слово, двічі виправлене вручну, "
             "далі виправлятиметься саме"),
            ("auto_in_fullscreen", "Автоматика в повноекранних вікнах",
             "Напр. відео. Ігри вимкнені завжди й повністю, разом із хоткеями (див. нижче)"),
        ]:
            row = Adw.SwitchRow(title=title, subtitle=sub, active=self.cfg[key])
            row.connect("notify::active", lambda r, _, k=key: self.set(k, r.get_active()))
            g.add(row)
        page.add(g)

        # --- exclusions
        self.lists = {}
        for key, title, desc in [
            ("exclude", "Без автоматики в цих програмах",
             "Клас вікна (як у hyprctl clients), по одному в рядку; можна regex. "
             "Комбінації клавіш працюють і тут."),
            ("allow_titles", "Але з автоматикою, якщо заголовок вікна такий",
             "Для AI-агентів і чатів у терміналі: OpenCode пише в заголовку «OC | …». "
             "Regex, по одному в рядку."),
            ("games", "Ігри: повністю вимкнено",
             "Тут не працюють навіть комбінації клавіш. Усе, що запущене зі Steam, "
             "вважається грою автоматично."),
        ]:
            g = Adw.PreferencesGroup(title=title, description=desc)
            view = Gtk.TextView(monospace=True, top_margin=8, bottom_margin=8,
                                left_margin=10, right_margin=10)
            view.get_buffer().set_text("\n".join(self.cfg.get(key, [])))
            view.get_buffer().connect("changed", self.list_changed, key)
            self.lists[key] = view
            g.add(Gtk.Frame(child=Gtk.ScrolledWindow(child=view, min_content_height=110)))
            row = Adw.ActionRow(title="Додати з відкритих вікон")
            add = Gtk.MenuButton(label="Додати", valign=Gtk.Align.CENTER)
            add.set_popover(self.windows_popover(key))
            row.add_suffix(add)
            g.add(row)
            page.add(g)

        # --- learned + log
        g = Adw.PreferencesGroup(title="Вивчене")
        self.learned_row = Adw.ActionRow(title="Слова")
        clear = Gtk.Button(label="Забути все", valign=Gtk.Align.CENTER)
        clear.add_css_class("destructive-action")
        clear.connect("clicked", self.clear_learned)
        self.learned_row.add_suffix(clear)
        g.add(self.learned_row)
        log = Adw.ActionRow(title="Журнал тестового режиму",
                            subtitle="Що програма виправила б. Зберігається лише в пам'яті")
        show = Gtk.Button(label="Показати", valign=Gtk.Align.CENTER)
        show.connect("clicked", self.show_log)
        log.add_suffix(show)
        g.add(log)
        page.add(g)

        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)

    # ---- saving ---------------------------------------------------------
    def apply(self):
        config.save(self.cfg)
        send("reload")

    def set(self, key, value):
        self.cfg[key] = value
        self.apply()

    def set_hotkey(self, action, value):
        self.cfg["hotkeys"][action] = value
        self.apply()

    def list_changed(self, buf, key):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.cfg[key] = [l.strip() for l in text.splitlines() if l.strip()]
        GLib.timeout_add(600, self._save_list, key, list(self.cfg[key]))

    def _save_list(self, key, snapshot):
        if snapshot == self.cfg[key]:          # typing has paused
            self.apply()
        return False

    # ---- status ---------------------------------------------------------
    def refresh(self):
        st = send("status")
        if st.get("ok"):
            self.status.set_subtitle("Працює · клавіатури: " + ", ".join(st["keyboards"]))
        else:
            self.status.set_subtitle("Не запущена: " + st.get("error", ""))
        learned = config.load_learned()
        self.learned_row.set_subtitle(f"не виправляти: {len(learned['keep'])} · "
                                      f"виправляти завжди: {len(learned['switch'])}")
        return True

    def restart(self, _):
        subprocess.run(["systemctl", "--user", "restart", SERVICE])
        GLib.timeout_add(800, lambda: self.refresh() and False)
        self.toasts.add_toast(Adw.Toast(title="Службу перезапущено"))

    def windows_popover(self, key):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6,
                      margin_bottom=6, margin_start=6, margin_end=6)
        pop.set_child(box)

        def fill(*_):
            while child := box.get_first_child():
                box.remove(child)
            try:
                import hypr
                classes = sorted({c["class"] for c in hypr.query("clients") if c["class"]})
            except (OSError, ValueError, KeyError):
                classes = []
            for cls in classes:
                b = Gtk.Button(label=cls, has_frame=False)
                b.connect("clicked", lambda _, c=cls: (self.add_to_list(key, c), pop.popdown()))
                box.append(b)
        pop.connect("show", fill)
        return pop

    def add_to_list(self, key, cls):
        import re
        pattern = re.escape(cls)
        if pattern not in self.cfg[key]:
            buf = self.lists[key].get_buffer()
            buf.insert(buf.get_end_iter(), ("\n" if self.cfg[key] else "") + pattern)

    def clear_learned(self, _):
        config.save_learned({"keep": [], "switch": [], "manual": {}})
        send("reload")
        self.refresh()
        self.toasts.add_toast(Adw.Toast(title="Вивчені слова забуто"))

    def show_log(self, _):
        reply = send("log")
        text = "\n".join(reply.get("log", [])) or (
            "Порожньо. Увімкніть режим «Тест» і попишіть: тут з'явиться, що програма "
            "виправила б.")
        dlg = Adw.AlertDialog(heading="Журнал", body=text)
        dlg.add_response("ok", "Закрити")
        dlg.present(self)


def main():
    app = Adw.Application(application_id="io.github.Elinchi.LayoutFixer")
    app.connect("activate", lambda a: (a.get_active_window() or Window(a)).present())
    app.run(sys.argv[:1])
