"""GTK3 desktop UI for managing ~/.ssh/config and opening SSH sessions in a
native terminal."""
import difflib
import ipaddress
import os
import sys
import threading
import time
from datetime import datetime

import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    HAVE_INDICATOR = True
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3
        HAVE_INDICATOR = True
    except (ValueError, ImportError):
        HAVE_INDICATOR = False

from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Pango
try:
    gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource
    HAVE_SOURCE = True
except (ValueError, ImportError):
    HAVE_SOURCE = False

from . import backend
from . import i18n
from .i18n import T
from .backend import ConfigError, ExternalChangeError

APP_TITLE = "Hostkeep"
ICON_NAME = "hostkeep"
APP_ID = "io.github.qnsi337.Hostkeep"
ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.svg")


def icon_installed():
    return Gtk.IconTheme.get_default().has_icon(ICON_NAME)


def app_icon_image():
    if icon_installed():
        return Gtk.Image.new_from_icon_name(ICON_NAME, Gtk.IconSize.LARGE_TOOLBAR)
    return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(ICON_FILE, 24, 24))

ACCENT_FROM = "#5B8DEF"
ACCENT_TO = "#8E6CF0"

CSS = f"""
/* ---------- layout surfaces */
.sidebar {{
    background-color: @theme_base_color;
    border-right: 1px solid alpha(currentColor, 0.08);
}}
.content {{
    background-color: @theme_bg_color;
}}
.bottom-panel {{
    background-color: @theme_bg_color;
    border-top: 1px solid alpha(currentColor, 0.08);
}}
paned > separator {{
    background-color: transparent;
    background-image: none;
    min-width: 1px;
    min-height: 1px;
}}

/* ---------- typography */
.section-title {{
    font-weight: 600;
}}
.form-section {{
    font-weight: 700;
    font-size: 0.82em;
    letter-spacing: 1px;
    opacity: 0.5;
    margin: 14px 0 6px 4px;
}}
.host-title {{
    font-weight: 800;
    font-size: 1.55em;
}}
.muted {{
    opacity: 0.55;
}}
.dirty-label {{
    color: #D98C0F;
}}
.status-row {{
    background-color: @theme_bg_color;
    border-top: 1px solid alpha(currentColor, 0.06);
}}
.status-row label {{
    opacity: 0.55;
    font-size: 0.88em;
}}

/* ---------- boxed lists (GNOME settings look) */
list.boxed {{
    background-color: @theme_base_color;
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 12px;
}}
list.boxed > row {{
    padding: 3px 6px 3px 14px;
    border-bottom: 1px solid alpha(currentColor, 0.06);
    min-height: 40px;
}}
list.boxed > row:last-child {{
    border-bottom: none;
}}
list.boxed > row:hover, list.boxed > row:selected {{
    background-color: transparent;
}}
list.boxed > row label.row-title {{
    opacity: 0.8;
}}
.boxed entry, .boxed combobox entry, .boxed spinbutton {{
    border-color: transparent;
    background-color: transparent;
    box-shadow: none;
}}
.boxed entry:focus, .boxed combobox entry:focus {{
    background-color: alpha({ACCENT_FROM}, 0.07);
    border-color: transparent;
    box-shadow: inset 0 0 0 1px alpha({ACCENT_FROM}, 0.45);
}}
.boxed combobox button {{
    border-color: transparent;
    background-color: transparent;
    background-image: none;
    box-shadow: none;
}}
scrolledwindow.boxed-frame {{
    background-color: @theme_base_color;
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 12px;
    padding: 4px;
}}
scrolledwindow.boxed-frame treeview.view, scrolledwindow.boxed-frame textview text {{
    background-color: transparent;
}}
scrolledwindow.boxed-frame treeview.view:selected, scrolledwindow.boxed-frame treeview.view:selected:focus {{
    background-color: alpha({ACCENT_FROM}, 0.16);
    color: @theme_fg_color;
}}
scrolledwindow.boxed-frame textview border.left, scrolledwindow.boxed-frame textview gutter {{
    background-color: alpha(currentColor, 0.04);
    color: alpha(currentColor, 0.45);
}}

/* ---------- lists */
treeview.view {{
    -GtkTreeView-horizontal-separator: 6;
}}
treeview.view:selected, treeview.view:selected:focus {{
    background-color: alpha({ACCENT_FROM}, 0.16);
    color: @theme_fg_color;
}}
treeview.view header button {{
    background: transparent;
    border: none;
    box-shadow: none;
    font-size: 0.85em;
    font-weight: 600;
    color: alpha(currentColor, 0.5);
    padding-top: 2px;
    padding-bottom: 2px;
}}
.sidebar treeview.view {{
    background-color: transparent;
}}
.sidebar treeview.view:selected, .sidebar treeview.view:selected:focus {{
    background-color: alpha({ACCENT_FROM}, 0.16);
    color: @theme_fg_color;
}}

/* ---------- pill tabs */
notebook.pills, notebook.pills > stack {{
    background-color: transparent;
    border: none;
    box-shadow: none;
}}
notebook.pills > header {{
    background-color: transparent;
    border: none;
    box-shadow: none;
    padding: 0 0 10px 0;
}}
notebook.pills > header tabs {{
    margin: 0;
}}
notebook.pills > header tab {{
    border: none;
    box-shadow: none;
    border-radius: 10px;
    padding: 5px 14px;
    margin: 0 4px 0 0;
    min-height: 0;
    background-color: transparent;
    color: alpha(currentColor, 0.65);
}}
notebook.pills > header tab:hover {{
    background-color: alpha(currentColor, 0.06);
    box-shadow: none;
}}
notebook.pills > header tab:checked {{
    background-color: alpha({ACCENT_FROM}, 0.14);
    color: {ACCENT_FROM};
    box-shadow: none;
}}
notebook.pills > header tab:checked label {{
    font-weight: 600;
}}

/* ---------- navigation rail */
.rail {{
    background-color: shade(@theme_bg_color, 0.97);
    border-right: 1px solid alpha(currentColor, 0.08);
    padding: 10px 8px;
}}
.rail button {{
    border-radius: 12px;
    padding: 8px 2px 6px 2px;
    min-width: 70px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: transparent;
    color: alpha(currentColor, 0.62);
    transition: background-color 120ms ease-out;
}}
.rail button:hover {{
    background-color: alpha(currentColor, 0.07);
    color: alpha(currentColor, 0.85);
}}
.rail button:checked {{
    background-color: alpha({ACCENT_FROM}, 0.15);
    color: {ACCENT_FROM};
}}
.rail button label.rail-label {{
    font-size: 0.78em;
    font-weight: 500;
}}
.rail button:checked label.rail-label {{
    font-weight: 700;
}}
label.badge {{
    background-color: {ACCENT_FROM};
    color: #FFFFFF;
    border-radius: 999px;
    padding: 0 5px;
    font-size: 0.68em;
    font-weight: 800;
    min-width: 10px;
}}
label.badge.ok {{
    background-color: #1E9E5A;
}}
label.badge.warn {{
    background-color: #D98C0F;
}}
.warn-bar {{
    background-color: alpha(#D98C0F, 0.10);
    border: 1px solid alpha(#D98C0F, 0.40);
    border-radius: 12px;
    padding: 8px 12px;
}}
.warn-bar image.warn-icon {{
    color: #D98C0F;
}}
label.badge.quiet {{
    background-color: #8A9099;
}}

/* ---------- buttons: calm, 10px radius */
button.suggested-action {{
    background-image: none;
    background-color: {ACCENT_FROM};
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 7px 16px;
    font-weight: 600;
    box-shadow: none;
    transition: background-color 120ms ease-out;
}}
button.suggested-action:hover {{
    background-color: shade({ACCENT_FROM}, 1.07);
}}
button.suggested-action:active {{
    background-color: shade({ACCENT_FROM}, 0.92);
}}
button.suggested-action:disabled {{
    background-color: alpha(currentColor, 0.07);
    color: alpha(currentColor, 0.35);
}}
button.pill {{
    border-radius: 10px;
    padding: 7px 14px;
    border: none;
    background-image: none;
    background-color: alpha(currentColor, 0.07);
    box-shadow: none;
    transition: background-color 120ms ease-out;
}}
button.pill:hover {{
    background-color: alpha(currentColor, 0.12);
}}
button.pill:active {{
    background-color: alpha(currentColor, 0.16);
}}
button.pill:disabled {{
    background-color: alpha(currentColor, 0.04);
}}
button.pill.suggested-action {{
    background-color: {ACCENT_FROM};
    color: #FFFFFF;
}}
button.pill.suggested-action:hover {{
    background-color: shade({ACCENT_FROM}, 1.07);
}}
button.pill.suggested-action:disabled {{
    background-color: alpha(currentColor, 0.07);
    color: alpha(currentColor, 0.35);
}}
/* accent-tinted secondary action ("Connect") */
button.tonal {{
    background-image: none;
    background-color: alpha({ACCENT_FROM}, 0.13);
    color: {ACCENT_FROM};
    font-weight: 600;
    border: none;
    box-shadow: none;
    border-radius: 10px;
    padding: 7px 14px;
}}
button.tonal:hover {{
    background-color: alpha({ACCENT_FROM}, 0.21);
}}
button.tonal:active {{
    background-color: alpha({ACCENT_FROM}, 0.28);
}}
button.tonal:disabled {{
    background-color: alpha(currentColor, 0.05);
    color: alpha(currentColor, 0.35);
}}

/* ---------- inputs & dropdowns */
entry, spinbutton:not(.vertical) {{
    border-radius: 10px;
    border: 1px solid alpha(currentColor, 0.15);
    background-image: none;
    background-color: @theme_base_color;
    box-shadow: none;
    min-height: 30px;
    transition: border-color 120ms ease-out, box-shadow 120ms ease-out;
}}
entry {{
    padding-left: 10px;
    padding-right: 10px;
}}
entry:focus, spinbutton:focus {{
    border-color: {ACCENT_FROM};
    box-shadow: 0 0 0 3px alpha({ACCENT_FROM}, 0.18);
}}
spinbutton:not(.vertical) entry {{
    border: none;
    box-shadow: none;
    background-color: transparent;
}}
spinbutton:not(.vertical) button {{
    border: none;
    border-left: 1px solid alpha(currentColor, 0.10);
    border-radius: 0;
    background-image: none;
    background-color: transparent;
    box-shadow: none;
}}
spinbutton:not(.vertical) button:hover {{
    background-color: alpha({ACCENT_FROM}, 0.10);
}}
button.combo {{
    border-radius: 10px;
    border: 1px solid alpha(currentColor, 0.15);
    background-image: none;
    background-color: @theme_base_color;
    box-shadow: none;
    min-height: 30px;
    padding: 2px 10px;
    transition: border-color 120ms ease-out, background-color 120ms ease-out;
}}
button.combo:hover {{
    border-color: alpha({ACCENT_FROM}, 0.60);
    background-color: alpha({ACCENT_FROM}, 0.04);
}}
button.combo:checked, button.combo:active {{
    border-color: {ACCENT_FROM};
    box-shadow: 0 0 0 3px alpha({ACCENT_FROM}, 0.18);
}}
button.combo arrow {{
    color: alpha(currentColor, 0.55);
}}
combobox box.linked > entry.combo {{
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
    border-right-width: 0;
}}
combobox box.linked > button.combo {{
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    padding: 2px 8px;
}}

/* ---------- menus: context menus, dropdown lists, popovers */
menu, .menu, .context-menu {{
    padding: 6px;
    border-radius: 12px;
    background-color: @theme_base_color;
    border: 1px solid alpha(currentColor, 0.12);
}}
menu menuitem {{
    padding: 7px 14px;
    border-radius: 8px;
    min-height: 18px;
    transition: background-color 80ms ease-out;
}}
menu menuitem:hover {{
    background-color: alpha({ACCENT_FROM}, 0.14);
    color: @theme_fg_color;
}}
menu menuitem:disabled {{
    color: alpha(currentColor, 0.45);
}}
menu separator {{
    margin: 4px 8px;
    min-height: 1px;
    background-color: alpha(currentColor, 0.10);
}}
menu menuitem arrow {{
    color: alpha(currentColor, 0.5);
}}
popover {{
    border-radius: 12px;
    padding: 4px;
}}
button.flat {{
    border-radius: 10px;
    border: none;
    box-shadow: none;
    background-image: none;
    transition: background-color 120ms ease-out;
}}
button.flat:hover {{
    background-color: alpha(currentColor, 0.08);
}}
button.destructive-action {{
    border-radius: 10px;
}}
headerbar button {{
    border-radius: 10px;
}}
headerbar button.titlebutton {{
    border-radius: 999px;
}}
.segmented button {{
    border-radius: 8px;
    padding: 3px 12px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: transparent;
    color: alpha(currentColor, 0.7);
}}
.segmented {{
    background-color: alpha(currentColor, 0.07);
    border-radius: 10px;
    padding: 2px;
}}
.segmented button:checked {{
    background-color: @theme_base_color;
    color: @theme_fg_color;
    box-shadow: 0 1px 2px alpha(black, 0.15);
}}
.ghost-button {{
    background-color: transparent;
    border: none;
    box-shadow: none;
}}
entry.search {{
    border-radius: 999px;
}}
.nav button, .nav radiobutton {{
    border-radius: 999px;
    padding: 4px 12px;
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: transparent;
    color: alpha(currentColor, 0.7);
}}
.nav button:hover {{
    background-color: alpha(currentColor, 0.07);
}}
.nav button:checked {{
    background-color: alpha({ACCENT_FROM}, 0.15);
    color: {ACCENT_FROM};
}}
.nav button:checked label {{
    font-weight: 600;
}}
.status-row:hover label {{
    opacity: 0.85;
}}

/* ---------- validation: soft, only after the field was left empty (after .boxed so it wins) */
entry.missing, spinbutton.missing, combobox.missing entry,
.boxed entry.missing, .boxed combobox entry.missing {{
    border-color: alpha(#D98C0F, 0.65);
    box-shadow: none;
    background-color: alpha(#D98C0F, 0.05);
}}
label.missing, list.boxed > row label.row-title.missing {{
    color: #B9770E;
    opacity: 1;
}}
"""

# Options that get a dedicated widget in the form; everything else goes to
# the "additional options" table.
FORM_KEYS = ["HostName", "User", "Port", "ProxyJump", "IdentityFile",
             "IdentitiesOnly", "PubkeyAuthentication", "ForwardAgent", "ConnectTimeout"]
YES_NO = ["", "yes", "no"]

PAGE_FORM, PAGE_TUNNELS, PAGE_TEXT, PAGE_EFFECTIVE = 0, 1, 2, 3

GROUPING_MODES = [("meta", 'Группы: метки'), ("prefix", 'Группы: по имени'), ("file", 'Группы: по файлам'),
                  ("none", 'Без групп')]


# ---------------------------------------------------------------- helpers

def icon_button(icon_name, label_text=None, tooltip=None):
    btn = Gtk.Button()
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.set_halign(Gtk.Align.CENTER)
    box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON), False, False, 0)
    if label_text:
        box.pack_start(Gtk.Label(label=label_text), False, False, 0)
    btn.add(box)
    if tooltip:
        btn.set_tooltip_text(tooltip)
    btn.get_style_context().add_class("flat" if not label_text else "pill")
    return btn


def rel_time(stamp):
    """'YYYY-MM-DD HH:MM' -> 'только что' / '5 мин' / '3 ч' / 'вчера' / '12 дн' / '10.03.25'."""
    try:
        dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""
    sec = (datetime.now() - dt).total_seconds()
    if sec < 90:
        return T('только что')
    if sec < 3600:
        return T('{0} мин').format(int(sec // 60))
    if sec < 86400 and dt.date() == datetime.now().date():
        return T('{0} ч').format(int(sec // 3600))
    days = (datetime.now().date() - dt.date()).days
    if days == 1:
        return T('вчера')
    if days < 30:
        return T('{0} дн').format(days)
    return dt.strftime("%d.%m.%y")


class BoxedForm:
    """Settings-style form: sections of rounded lists with 'label — widget' rows."""

    def __init__(self, label_width=16):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.label_width = label_width
        self.labels = {}
        self.list = None

    def section(self, title, extra=None):
        head = Gtk.Box(spacing=6)
        label = Gtk.Label(label=title.upper(), xalign=0)
        label.get_style_context().add_class("form-section")
        head.pack_start(label, True, True, 0)
        if extra is not None:
            head.pack_end(extra, False, False, 0)
        self.box.pack_start(head, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("boxed")
        self.box.pack_start(self.list, False, False, 0)
        return self.list

    def row(self, title, widget, extra=None, tooltip=None):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        hb = Gtk.Box(spacing=8)
        label = Gtk.Label(label=title, xalign=0)
        label.set_width_chars(self.label_width)
        label.get_style_context().add_class("row-title")
        if tooltip:
            label.set_tooltip_text(tooltip)
            widget.set_tooltip_text(tooltip)
        hb.pack_start(label, False, False, 0)
        widget.set_valign(Gtk.Align.CENTER)
        hb.pack_start(widget, True, True, 0)
        if extra is not None:
            extra.set_valign(Gtk.Align.CENTER)
            hb.pack_start(extra, False, False, 0)
        row.add(hb)
        self.list.add(row)
        self.labels[title] = label
        return widget

    def note(self, widget):
        widget.set_margin_start(6)
        widget.set_margin_top(6)
        self.box.pack_start(widget, False, False, 0)


def section_title(icon_name, text):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
    label = Gtk.Label(label=text, xalign=0)
    label.get_style_context().add_class("section-title")
    box.pack_start(label, False, False, 0)
    return box


def run_async(work, on_result=None, on_error=None):
    def target():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            if on_error:
                GLib.idle_add(on_error, exc)
            return
        if on_result:
            GLib.idle_add(on_result, result)
    threading.Thread(target=target, daemon=True).start()


def esc(text):
    return GLib.markup_escape_text(text or "")


def combo_entry(values=(), width=None):
    combo = Gtk.ComboBoxText.new_with_entry()
    for v in values:
        combo.append_text(v)
    if width:
        combo.get_child().set_width_chars(width)
    return combo


def combo_set_items(combo, values):
    text = combo.get_child().get_text()
    combo.remove_all()
    for v in values:
        combo.append_text(v)
    combo.get_child().set_text(text)


def combo_text(combo):
    return combo.get_child().get_text().strip()


def monospace_view(editable=True):
    view = Gtk.TextView()
    view.set_monospace(True)
    view.set_editable(editable)
    view.set_left_margin(6)
    view.set_top_margin(6)
    view.set_wrap_mode(Gtk.WrapMode.NONE)
    return view


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_lang_manager = None


def _languages():
    global _lang_manager
    if _lang_manager is None:
        _lang_manager = GtkSource.LanguageManager.get_default()
        _lang_manager.set_search_path(list(_lang_manager.get_search_path()) + [DATA_DIR])
    return _lang_manager


def _prefers_dark():
    st = Gtk.Settings.get_default()
    if os.environ.get("GTK_THEME"):
        return "dark" in os.environ["GTK_THEME"].lower()
    theme = (st.get_property("gtk-theme-name") or "").lower()
    return bool(st.get_property("gtk-application-prefer-dark-theme")) or "dark" in theme


def _scheme():
    sm = GtkSource.StyleSchemeManager.get_default()
    ids = sm.get_scheme_ids() or []
    prefs = (["Yaru-dark", "Adwaita-dark", "oblivion", "solarized-dark", "cobalt"] if _prefers_dark()
             else ["Yaru", "Adwaita", "tango", "classic", "solarized-light"])
    for sid in prefs:
        if sid in ids:
            return sm.get_scheme(sid)
    return None


_code_buffers = []


def theme_exists(name):
    if name in ("Adwaita", "HighContrast"):
        return True
    for base in ("/usr/share/themes", os.path.expanduser("~/.themes"), os.path.expanduser("~/.local/share/themes")):
        if os.path.isdir(os.path.join(base, name, "gtk-3.0")):
            return True
    return False


_orig_theme = None


def apply_theme(mode):
    """mode: system | light | dark. Changes only this app."""
    global _orig_theme
    st = Gtk.Settings.get_default()
    if _orig_theme is None:
        _orig_theme = (st.get_property("gtk-theme-name") or "Adwaita",
                       bool(st.get_property("gtk-application-prefer-dark-theme")))
    name, prefer = _orig_theme
    base = name[:-5] if name.lower().endswith("-dark") else name
    if mode == "dark":
        dark = base + "-dark"
        st.set_property("gtk-theme-name", dark if base != "Adwaita" and theme_exists(dark) else base)
        st.set_property("gtk-application-prefer-dark-theme", True)
    elif mode == "light":
        st.set_property("gtk-theme-name", base if theme_exists(base) else "Adwaita")
        st.set_property("gtk-application-prefer-dark-theme", False)
    else:
        st.set_property("gtk-theme-name", name)
        st.set_property("gtk-application-prefer-dark-theme", prefer)
    if HAVE_SOURCE:
        scheme = _scheme()
        for ref in list(_code_buffers):
            buf = ref()
            if buf is None:
                _code_buffers.remove(ref)
            elif scheme is not None:
                buf.set_style_scheme(scheme)


def set_language(buf, lang_id):
    if HAVE_SOURCE and isinstance(buf, GtkSource.Buffer):
        buf.set_language(_languages().get_language(lang_id) if lang_id else None)


def code_view(lang="sshconfig", editable=True, line_numbers=True):
    """Syntax-highlighted editor with line numbers (GtkSourceView);
    falls back to a plain monospace TextView when it is not installed."""
    if not HAVE_SOURCE:
        return monospace_view(editable)
    buf = GtkSource.Buffer()
    set_language(buf, lang)
    buf.set_highlight_syntax(True)
    buf.set_highlight_matching_brackets(False)
    scheme = _scheme()
    if scheme is not None:
        buf.set_style_scheme(scheme)
    import weakref
    _code_buffers.append(weakref.ref(buf))
    view = GtkSource.View.new_with_buffer(buf)
    view.set_monospace(True)
    view.set_editable(editable)
    view.set_cursor_visible(editable)
    view.set_show_line_numbers(line_numbers)
    view.set_highlight_current_line(editable)
    view.set_tab_width(2)
    view.set_insert_spaces_instead_of_tabs(True)
    view.set_auto_indent(True)
    view.set_left_margin(8)
    view.set_top_margin(6)
    view.set_bottom_margin(6)
    return view


def buffer_text(buf):
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)


def scrolled(child, min_height=None, boxed=False):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    if min_height:
        sw.set_min_content_height(min_height)
    if boxed:
        sw.get_style_context().add_class("boxed-frame")
    sw.add(child)
    return sw


def _apply_missing(widget, show, label):
    targets = [widget]
    if isinstance(widget, Gtk.ComboBox) and widget.get_has_entry():
        targets.append(widget.get_child())
    if label is not None:
        targets.append(label)
    for w in targets:
        ctx = w.get_style_context()
        if show:
            ctx.add_class("missing")
        else:
            ctx.remove_class("missing")


def set_missing(widget, missing, label=None, force=False):
    """Soft highlight of an empty / invalid required field. It is shown only
    after the user left the field (focus-out) or tried to save (force=True) —
    a fresh form never looks like it is complaining."""
    widget._hk_state = (missing, label)
    if force and missing:
        widget._hk_touched = True
    if not getattr(widget, "_hk_hooked", False):
        widget._hk_hooked = True
        target = widget.get_child() if isinstance(widget, Gtk.ComboBox) and widget.get_has_entry() else widget

        def on_blur(*_a):
            widget._hk_touched = True
            m, lbl = widget._hk_state
            _apply_missing(widget, m, lbl)
            return False
        target.connect("focus-out-event", on_blur)
    _apply_missing(widget, missing and getattr(widget, "_hk_touched", False), label)


def reset_touched(*widgets):
    for w in widgets:
        w._hk_touched = False
        state = getattr(w, "_hk_state", None)
        if state:
            _apply_missing(w, False, state[1])


def required_hint():
    label = Gtk.Label(xalign=0)
    label.set_markup(T('<span color="#5B8DEF">*</span> <small>— обязательные поля</small>'))
    label.get_style_context().add_class("muted")
    return label


def form_label(text, tooltip=None):
    label = Gtk.Label(label=text, xalign=1)
    label.get_style_context().add_class("muted")
    if tooltip:
        label.set_tooltip_text(tooltip)
    return label


# ---------------------------------------------------------------- dialogs

class NewHostDialog(Gtk.Dialog):
    """Create a host from a template."""

    def __init__(self, parent, templates, groups, aliases, keys, default_group="", default_template=1,
                 files=(), default_file=None):
        super().__init__(title=T('Новый хост'), transient_for=parent, modal=True)
        self.set_default_size(520, -1)
        self.templates = templates
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, T('Создать'), Gtk.ResponseType.OK)
        self.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        box = self.get_content_area()
        box.set_border_width(14)
        box.set_spacing(10)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.add(grid)

        self.template_combo = Gtk.ComboBoxText()
        for i, t in enumerate(templates):
            self.template_combo.append(str(i), ("" if t.get("builtin") else "★ ") + t.get("title", t["name"]))
        self.template_desc = Gtk.Label(xalign=0)
        self.template_desc.set_line_wrap(True)
        self.template_desc.set_max_width_chars(50)
        self.template_desc.get_style_context().add_class("muted")

        self.host_entry = Gtk.Entry(placeholder_text=T('например web-01.prod'))
        self.host_entry.set_activates_default(True)
        self.hostname_entry = Gtk.Entry(placeholder_text=T('IP-адрес или DNS-имя'))
        self.hostname_entry.set_activates_default(True)
        self.user_entry = Gtk.Entry()
        self.port_entry = Gtk.Entry(placeholder_text="22")
        self.port_entry.set_width_chars(6)
        self.group_combo = combo_entry(groups)
        self.group_combo.get_child().set_text(default_group or "")
        self.proxy_combo = combo_entry(aliases)
        self.key_combo = combo_entry(keys)
        self.file_combo = Gtk.ComboBoxText()
        for path, label in files:
            self.file_combo.append(path, label)
        if files:
            self.file_combo.set_active_id(default_file or files[0][0])
        self.file_combo.set_tooltip_text(T('В какой файл записать хост (основной конфиг или файл из Include)'))

        rows = [
            (T('Шаблон'), self.template_combo), ("", self.template_desc),
            ("Host *", self.host_entry), ("HostName", self.hostname_entry),
            ("User", self.user_entry), ("Port", self.port_entry),
            ("IdentityFile", self.key_combo), ("ProxyJump", self.proxy_combo),
            (T('Группа'), self.group_combo),
        ] + ([(T('Файл'), self.file_combo)] if len(files) > 1 else [])
        self.labels = {}
        for r, (title, widget) in enumerate(rows):
            if title:
                self.labels[widget] = form_label(title)
                grid.attach(self.labels[widget], 0, r, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, r, 1, 1)
        box.add(required_hint())

        self.template_combo.connect("changed", self._on_template_changed)
        for w in (self.host_entry, self.hostname_entry, self.proxy_combo.get_child()):
            w.connect("changed", self._validate)
        self.template_combo.set_active(min(default_template, len(templates) - 1))
        self.set_default_response(Gtk.ResponseType.OK)
        self.show_all()
        self.host_entry.grab_focus()

    def _on_template_changed(self, combo):
        t = self.selected_template()
        self.template_desc.set_text(t.get("desc", ""))
        opts = {k.lower(): v for k, v in t.get("options", [])}
        self.port_entry.set_text(opts.get("port", ""))
        self.user_entry.set_text(opts.get("user", self.user_entry.get_text()))
        if opts.get("identityfile"):
            self.key_combo.get_child().set_text(opts["identityfile"])
        self.proxy_combo.get_child().set_text(opts.get("proxyjump", ""))
        if t.get("group"):
            self.group_combo.get_child().set_text(t["group"])
        self._validate()

    def required(self):
        """Which fields are mandatory for the current template / input."""
        t = self.selected_template()
        patterns = backend.split_patterns(self.host_entry.get_text().strip())
        wildcard = any(backend.is_wildcard(p) for p in patterns) or t["name"] == "Подсеть / wildcard"
        return {
            self.host_entry: True,
            self.hostname_entry: not wildcard,
            self.proxy_combo: bool(t.get("builtin")) and t["name"].startswith("Через бастион"),
        }

    def missing(self):
        out = []
        for w, req in self.required().items():
            text = combo_text(w) if isinstance(w, Gtk.ComboBox) else w.get_text().strip()
            if req and not text:
                out.append(w)
        return out

    def _validate(self, *args):
        req = self.required()
        miss = self.missing()
        names = {self.host_entry: "Host", self.hostname_entry: "HostName", self.proxy_combo: "ProxyJump"}
        for w, name in names.items():
            self.labels[w].set_text(name + (" *" if req[w] else ""))
            set_missing(w, w in miss, self.labels[w])
        self.hostname_entry.set_placeholder_text(T('IP-адрес или DNS-имя') if req[self.hostname_entry]
                                                 else T('необязательно для шаблона-подсети'))
        self.proxy_combo.get_child().set_placeholder_text(T('бастион — обязательно для этого шаблона')
                                                          if req[self.proxy_combo] else "")
        btn = self.get_widget_for_response(Gtk.ResponseType.OK)
        if btn is not None:
            btn.set_sensitive(not miss)

    def selected_template(self):
        idx = self.template_combo.get_active_id()
        return self.templates[int(idx)] if idx is not None else self.templates[0]

    def result(self):
        return {
            "patterns": backend.split_patterns(self.host_entry.get_text().strip()),
            "hostname": self.hostname_entry.get_text().strip(),
            "user": self.user_entry.get_text().strip(),
            "port": self.port_entry.get_text().strip(),
            "identity": combo_text(self.key_combo),
            "proxy": combo_text(self.proxy_combo),
            "group": combo_text(self.group_combo),
            "template": self.selected_template(),
            "file": self.file_combo.get_active_id(),
        }


def page_header(title, subtitle=None, actions=()):
    """Big page title + muted subtitle + optional buttons on the right."""
    head = Gtk.Box(spacing=8)
    titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    t = Gtk.Label(label=title, xalign=0)
    t.get_style_context().add_class("host-title")
    titles.pack_start(t, False, False, 0)
    if subtitle:
        st = Gtk.Label(label=subtitle, xalign=0)
        st.set_line_wrap(True)
        st.get_style_context().add_class("muted")
        titles.pack_start(st, False, False, 0)
    head.pack_start(titles, True, True, 0)
    for a in reversed(list(actions)):
        a.set_valign(Gtk.Align.CENTER)
        head.pack_end(a, False, False, 0)
    return head


def page_box(title, subtitle, child, actions=()):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    box.set_border_width(20)
    box.get_style_context().add_class("content")
    box.pack_start(page_header(title, subtitle, actions), False, False, 0)
    box.pack_start(child, True, True, 0)
    return box


class TemplatesPage(Gtk.Box):
    """Manage host templates inline (built-in ones are read-only, can be copied)."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.win = win
        self.templates = []
        self.current = None
        self._loading = False

        # list
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(300, -1)
        self.store = Gtk.ListStore(str, int)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        r = Gtk.CellRendererText(ypad=5)
        r.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.view.append_column(Gtk.TreeViewColumn("", r, markup=0))
        self.view.get_selection().connect("changed", self._on_select)
        left.pack_start(scrolled(self.view, boxed=True), True, True, 0)
        btns = Gtk.Box(spacing=2)
        copy_btn = icon_button("edit-copy-symbolic", None, T('Сделать копию шаблона'))
        copy_btn.connect("clicked", self._on_copy)
        self.del_btn = icon_button("user-trash-symbolic", None, T('Удалить шаблон'))
        self.del_btn.connect("clicked", self._on_delete)
        add_btn = icon_button("list-add-symbolic", T('Новый шаблон'))
        add_btn.connect("clicked", lambda b: self.add())
        btns.pack_start(add_btn, False, False, 0)
        btns.pack_end(self.del_btn, False, False, 0)
        btns.pack_end(copy_btn, False, False, 0)
        left.pack_start(btns, False, False, 0)
        self.pack_start(left, False, False, 0)

        # editor
        form = BoxedForm(label_width=12)
        form.section(T('Шаблон'))
        self.name_entry = form.row(T('Название'), Gtk.Entry())
        self.desc_entry = form.row(T('Описание'), Gtk.Entry(placeholder_text=T('необязательно')))
        self.group_entry = form.row(T('Группа'), Gtk.Entry(placeholder_text=T('группа по умолчанию для новых хостов')))
        head = Gtk.Label(label=T('ПАРАМЕТРЫ'), xalign=0)
        head.get_style_context().add_class("form-section")
        form.box.pack_start(head, False, False, 0)
        self.opts_view = code_view(line_numbers=False)
        self.opts_buf = self.opts_view.get_buffer()
        sw = scrolled(self.opts_view, min_height=200, boxed=True)
        form.box.pack_start(sw, True, True, 0)
        hint = Gtk.Label(xalign=0, label=T('По одному параметру в строке: «Key value». {alias} заменится на имя хоста. Параметр без значения — поле, которое надо заполнить при создании.'))
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("muted")
        form.note(hint)
        self.readonly_label = Gtk.Label(xalign=0)
        self.readonly_label.get_style_context().add_class("dirty-label")
        form.note(self.readonly_label)
        bottom = Gtk.Box(spacing=6)
        bottom.set_margin_top(10)
        self.use_btn = icon_button("list-add-symbolic", T('Создать хост по шаблону'))
        self.use_btn.connect("clicked", lambda b: self.current is not None and
                             self.win.on_new_host(template_index=self.current))
        self.save_btn = icon_button("document-save-symbolic", T('Сохранить'))
        self.save_btn.get_style_context().add_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save)
        bottom.pack_start(self.use_btn, False, False, 0)
        bottom.pack_end(self.save_btn, False, False, 0)
        form.box.pack_start(bottom, False, False, 0)
        self.pack_start(form.box, True, True, 0)
        for w in (self.name_entry, self.desc_entry, self.group_entry):
            w.connect("changed", self._on_changed)
        self.opts_buf.connect("changed", self._on_changed)

    @property
    def dirty(self):
        return self.save_btn.get_sensitive() and self.current is not None \
            and not self.templates[self.current].get("builtin")

    def reload(self, select_name=None):
        self.templates = backend.load_templates()
        self.store.clear()
        for i, t in enumerate(self.templates):
            tag = T('  <small><span alpha="45%">встроенный</span></small>') if t.get("builtin") else ""
            desc = f'\n<small><span alpha="55%">{esc(t.get("desc", ""))}</span></small>' if t.get("desc") else ""
            self.store.append([f'<span weight="600">{esc(t.get("title", t["name"]))}</span>{tag}{desc}', i])
        target = 0
        if select_name:
            for i, t in enumerate(self.templates):
                if t["name"] == select_name and not t.get("builtin"):
                    target = i
        elif self.current is not None and self.current < len(self.templates):
            target = self.current
        if len(self.store):
            self.view.get_selection().select_path(Gtk.TreePath(target))

    def _on_select(self, selection):
        model, it = selection.get_selected()
        if it is None:
            return
        self.current = model[it][1]
        t = self.templates[self.current]
        self._loading = True
        self.name_entry.set_text(t.get("title", t["name"]))
        self.desc_entry.set_text(t.get("desc", ""))
        self.group_entry.set_text(t.get("group", ""))
        self.opts_buf.set_text("".join(f"{k} {v}\n" for k, v in t.get("options", [])))
        self._loading = False
        ro = bool(t.get("builtin"))
        for w in (self.name_entry, self.desc_entry, self.group_entry):
            w.set_sensitive(not ro)
        self.opts_view.set_editable(not ro)
        self.del_btn.set_sensitive(not ro)
        self.save_btn.set_sensitive(False)
        self.readonly_label.set_text(T('Встроенный шаблон нельзя изменить — сделайте копию ⧉') if ro else "")

    def _on_changed(self, *a):
        if not self._loading and self.current is not None and not self.templates[self.current].get("builtin"):
            self.save_btn.set_sensitive(bool(self.name_entry.get_text().strip()))

    def _unique_name(self, base):
        names = {t["name"] for t in self.templates}
        name, n = base, 2
        while name in names:
            name = f"{base} {n}"
            n += 1
        return name

    def add(self):
        t = {"name": self._unique_name(T('Мой шаблон')), "desc": "", "group": "",
             "options": [["Port", "22"], ["User", ""]], "builtin": False}
        self.templates.append(t)
        backend.save_user_templates(self.templates)
        self.reload(t["name"])
        self.name_entry.grab_focus()

    def _on_copy(self, _):
        if self.current is None:
            return
        src = self.templates[self.current]
        t = {"name": self._unique_name(src.get("title", src["name"]) + T(' (копия)')), "desc": src.get("desc", ""),
             "group": src.get("group", ""), "options": [list(o) for o in src.get("options", [])],
             "builtin": False}
        self.templates.append(t)
        backend.save_user_templates(self.templates)
        self.reload(t["name"])

    def _on_delete(self, _):
        if self.current is None or self.templates[self.current].get("builtin"):
            return
        name = self.templates[self.current]["name"]
        if not self.win._confirm(T('Удалить шаблон «{0}»?').format(name), ok_label=T('Удалить')):
            return
        del self.templates[self.current]
        backend.save_user_templates(self.templates)
        self.current = None
        self.reload()
        self.win.log(T('Шаблон «{0}» удалён').format(name))

    def _on_save(self, _):
        if self.current is None:
            return
        t = self.templates[self.current]
        name = self.name_entry.get_text().strip()
        if not name:
            return
        text = buffer_text(self.opts_buf)
        options = backend.parse_options_text(text)
        for raw in text.splitlines():   # keep "Key" lines with an empty value
            parts = raw.strip().split(None, 1)
            if len(parts) == 1 and parts[0][:1].isalpha() and not any(o[0] == parts[0] for o in options):
                options.append([parts[0], ""])
        t.update(name=name, desc=self.desc_entry.get_text().strip(),
                 group=self.group_entry.get_text().strip(), options=options)
        backend.save_user_templates(self.templates)
        self.reload(name)
        self.win.log(T('Шаблон «{0}» сохранён').format(name))
        self.win.set_status(T('Шаблон «{0}» сохранён').format(name))


class FilePage(Gtk.Box):
    """A config file as text (main config or any Include-d file)."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.win = win
        self._loading = False
        self.dirty = False
        self.loaded_from = None   # set by the backups page when it hands a backup over
        self.path = None          # file being edited

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.warn_box.set_no_show_all(True)
        left.pack_start(self.warn_box, False, False, 0)
        top = Gtk.Box(spacing=8)
        self.file_combo = Gtk.ComboBoxText()
        self.file_combo.set_tooltip_text(T('Основной конфиг и файлы, подключённые через Include'))
        self.file_combo.connect("changed", self._on_file_changed)
        flabel = Gtk.Label(label=T('Файл'))
        flabel.get_style_context().add_class("muted")
        top.pack_start(flabel, False, False, 0)
        top.pack_start(self.file_combo, False, False, 0)
        self.inc_label = Gtk.Label(xalign=0)
        self.inc_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.inc_label.get_style_context().add_class("muted")
        top.pack_start(self.inc_label, True, True, 4)
        left.pack_start(top, False, False, 0)
        self.view = code_view()
        self.buf = self.view.get_buffer()
        self.buf.connect("changed", self._on_changed)
        left.pack_start(scrolled(self.view, boxed=True), True, True, 0)
        bar = Gtk.Box(spacing=6)
        self.info = Gtk.Label(xalign=0)
        self.info.set_ellipsize(Pango.EllipsizeMode.END)
        self.info.set_width_chars(10)
        bar.pack_start(self.info, True, True, 0)
        self.check_btn = icon_button("emblem-ok-symbolic", T('Проверить'))
        self.check_btn.set_tooltip_text(T('Проверить текст через ssh -G, ничего не записывая'))
        self.check_btn.connect("clicked", lambda b: self.check())
        self.revert_btn = icon_button("edit-undo-symbolic", T('Отменить'))
        self.revert_btn.get_style_context().remove_class("pill")
        self.revert_btn.get_style_context().add_class("flat")
        self.revert_btn.connect("clicked", lambda b: self.load_current(force=True))
        self.save_btn = icon_button("document-save-symbolic", T('Сохранить'))
        self.save_btn.get_style_context().add_class("suggested-action")
        self.save_btn.set_tooltip_text(T('Проверить и записать файл (Ctrl+S). Текущая версия уйдёт в резервные копии'))
        self.save_btn.connect("clicked", lambda b: self.save())
        bar.pack_end(self.save_btn, False, False, 0)
        bar.pack_end(self.revert_btn, False, False, 0)
        bar.pack_end(self.check_btn, False, False, 0)
        copies_btn = icon_button("document-open-recent-symbolic", T('Резервные копии'))
        copies_btn.get_style_context().remove_class("pill")
        copies_btn.get_style_context().add_class("flat")
        copies_btn.connect("clicked", lambda b: self.win.show_page("backups"))
        bar.pack_end(copies_btn, False, False, 0)
        left.pack_start(bar, False, False, 0)
        self.pack_start(left, True, True, 0)

        self._set_dirty(False)

    def _set_dirty(self, dirty):
        self.dirty = dirty
        self.save_btn.set_sensitive(dirty)
        self.revert_btn.set_sensitive(dirty)
        if not dirty:
            self.loaded_from = None
            n = self.buf.get_line_count()
            self.info.set_markup(T('<span alpha="55%">{0} строк · сохранено</span>').format(n))

    def _on_changed(self, buf):
        if self._loading:
            return
        if not self.dirty:
            self._set_dirty(True)
        what = T('копия от {0}').format(self.loaded_from) if self.loaded_from else T('есть несохранённые изменения')
        self.info.set_markup(f'<span color="#D98C0F">● {esc(what)}</span>')

    def _files(self):
        return self.win.config.file_list()

    def _fill_files(self):
        cfgs = self._files()
        paths = [c.path for c in cfgs]
        if self.path not in paths:
            self.path = paths[0] if paths else self.win.config.path
        self._loading = True
        self.file_combo.remove_all()
        for c in cfgs:
            self.file_combo.append(c.path, self.win.config.label(c))
        self.file_combo.set_active_id(self.path)
        self._loading = False
        n = len(cfgs) - 1
        incs = self.win.config.includes
        missing = [v for _, v, res, _ in incs if not res]
        txt = []
        if n:
            txt.append(T('подключено через Include: {0} файл(ов)').format(n))
        if missing:
            txt.append(T('без совпадений: ') + ", ".join(missing))
        self.inc_label.set_text(" · ".join(txt))
        self.inc_label.set_tooltip_text("\n".join(f"{self.win.config.label(src)}: Include {v} → "
                                                   f"{', '.join(self.win.config.label(p) for p in res) or T('нет файлов')}"
                                                   + (T('  (внутри «{0}»)').format(blk) if blk else "")
                                                   for src, v, res, blk in incs) or None)

    def _on_file_changed(self, combo):
        if self._loading:
            return
        new = combo.get_active_id()
        if new == self.path:
            return
        if self.dirty and not self.win._confirm(T('Переключить файл?'), T('Несохранённые изменения пропадут.'),
                                                ok_label=T('Переключить')):
            self._loading = True
            combo.set_active_id(self.path)
            self._loading = False
            return
        self.path = new
        self.load_current(force=True)

    def open_file(self, path):
        self.path = path
        self.load_current(force=True)

    def current_cfg(self):
        real = os.path.realpath(self.path or self.win.config.path)
        return self.win.config.files.get(real, self.win.config.main)

    def load_current(self, force=False):
        if self.dirty and not force:
            return
        self._fill_files()
        self._loading = True
        self.buf.set_text(self.current_cfg().serialize())
        self._loading = False
        self._set_dirty(False)

    def check(self):
        try:
            backend.validate_text(buffer_text(self.buf), os.path.dirname(os.path.realpath(self.current_cfg().path)))
            self.info.set_markup(T('<span color="#1E9E5A">✔ ssh принимает этот конфиг</span>'))
        except ConfigError as exc:
            self.info.set_markup(f'<span color="#D64545">✖ {esc(str(exc).splitlines()[0])}</span>')
            self.info.set_tooltip_text(str(exc))

    def save(self):
        if not self.dirty:
            return True
        msg = T('Восстановлено из копии от {0}').format(self.loaded_from) if self.loaded_from else T('Файл сохранён целиком')
        if self.loaded_from and not self.win._confirm(T('Восстановить копию от {0}?').format(self.loaded_from),
                                                      T('Текущая версия файла сохранится в резервные копии.'),
                                                      ok_label=T('Восстановить')):
            return False
        if self.win.save_whole_text(buffer_text(self.buf), msg, self.current_cfg().path):
            self.load_current(force=True)
            return True
        return False


class BackupsPage(Gtk.Box):
    """Backups of the config files: list (per file), diff against the current
    file, restore, delete."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.win = win
        self._filling = False

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(320, -1)
        fbox = Gtk.Box(spacing=8)
        flabel = Gtk.Label(label=T('Файл'))
        flabel.get_style_context().add_class("muted")
        self.filter_combo = Gtk.ComboBoxText()
        self.filter_combo.set_tooltip_text(T('Показать копии одного файла'))
        self.filter_combo.connect("changed", lambda c: self._filling or self.refresh(keep_selection=False))
        fbox.pack_start(flabel, False, False, 0)
        fbox.pack_start(self.filter_combo, True, True, 0)
        left.pack_start(fbox, False, False, 0)
        self.store = Gtk.ListStore(str, str, str, str)   # markup, backup path, title, target file
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        r = Gtk.CellRendererText(ypad=5)
        r.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        self.view.append_column(Gtk.TreeViewColumn("", r, markup=0))
        self.view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.view.get_selection().connect("changed", lambda s: self.show_selected())
        self.view.connect("key-press-event", self._on_key)
        self.empty = Gtk.Label(label=T('Копий пока нет.\nКопия делается автоматически\nперед каждым сохранением.'),
                               justify=Gtk.Justification.CENTER)
        self.empty.get_style_context().add_class("muted")
        self.empty.set_no_show_all(True)
        ov = Gtk.Overlay()
        ov.add(scrolled(self.view, boxed=True))
        ov.add_overlay(self.empty)
        left.pack_start(ov, True, True, 0)
        lb = Gtk.Box(spacing=4)
        self.delete_btn = icon_button("user-trash-symbolic", T('Удалить'))
        self.delete_btn.set_tooltip_text(T('Удалить выбранные копии (Delete). Несколько — через Ctrl/Shift'))
        self.delete_btn.connect("clicked", lambda b: self.delete_selected())
        self.delete_all_btn = icon_button("edit-clear-all-symbolic", None, T('Удалить все копии выбранного файла'))
        self.delete_all_btn.connect("clicked", lambda b: self.delete_all_of_file())
        folder_btn = icon_button("folder-open-symbolic", None, T('Открыть папку с копиями'))
        folder_btn.connect("clicked", lambda b: self._open_folder())
        lb.pack_start(self.delete_btn, False, False, 0)
        lb.pack_end(folder_btn, False, False, 0)
        lb.pack_end(self.delete_all_btn, False, False, 0)
        left.pack_start(lb, False, False, 0)
        hint = Gtk.Label(xalign=0, label=T('Хранятся последние {0} копий каждого файла').format(backend.MAX_BACKUPS))
        hint.get_style_context().add_class("muted")
        left.pack_start(hint, False, False, 0)
        self.pack_start(left, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top = Gtk.Box(spacing=6)
        self.sel_title = Gtk.Label(xalign=0)
        self.sel_title.get_style_context().add_class("section-title")
        top.pack_start(self.sel_title, True, True, 0)
        mode = Gtk.Box(spacing=2)
        mode.get_style_context().add_class("segmented")
        self.diff_btn = Gtk.RadioButton.new_with_label_from_widget(None, T('Изменения'))
        self.full_btn = Gtk.RadioButton.new_with_label_from_widget(self.diff_btn, T('Весь файл'))
        for b in (self.diff_btn, self.full_btn):
            b.set_mode(False)
            b.connect("toggled", lambda b: b.get_active() and self.show_selected())
            mode.pack_start(b, False, False, 0)
        top.pack_end(mode, False, False, 0)
        right.pack_start(top, False, False, 0)
        self.text = code_view("diff", editable=False)
        self.buf = self.text.get_buffer()
        self.buf.create_tag("add", foreground="#1E9E5A", background="rgba(30,158,90,0.10)")
        self.buf.create_tag("del", foreground="#D64545", background="rgba(214,69,69,0.10)")
        self.buf.create_tag("hunk", foreground="#5B8DEF")
        self.buf.create_tag("dim", foreground="#9AA0A6")
        right.pack_start(scrolled(self.text, boxed=True), True, True, 0)
        bar = Gtk.Box(spacing=6)
        self.info = Gtk.Label(xalign=0)
        self.info.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_start(self.info, True, True, 0)
        self.restore_btn = icon_button("document-revert-symbolic", T('Восстановить эту копию'))
        self.restore_btn.get_style_context().add_class("suggested-action")
        self.restore_btn.set_tooltip_text(T('Записать копию в ~/.ssh/config. Текущая версия сохранится как новая копия'))
        self.restore_btn.connect("clicked", lambda b: self.restore())
        bar.pack_end(self.restore_btn, False, False, 0)
        right.pack_start(bar, False, False, 0)
        self.pack_start(right, True, True, 0)

    def _open_folder(self):
        os.makedirs(backend.BACKUP_DIR, exist_ok=True)
        backend.spawn_detached(["xdg-open", backend.BACKUP_DIR])

    def _selected_rows(self):
        model, paths = self.view.get_selection().get_selected_rows()
        return [(model[p][2], model[p][1], model[p][3]) for p in paths]

    def _selected(self):
        rows = self._selected_rows()
        return rows[0] if rows else None

    def _on_key(self, view, event):
        if event.keyval == Gdk.KEY_Delete:
            self.delete_selected()
            return True
        return False

    def _delete(self, items, title):
        listing = "\n".join(f"{self.win.config.label(t)} — {d}" for d, _, t in items[:15])
        if len(items) > 15:
            listing += T('\n… и ещё {0}').format(len(items) - 15)
        if not self.win._confirm(title, listing, ok_label=T('Удалить')):
            return
        n = 0
        for _, path, _ in items:
            try:
                backend.delete_backup(path)
                n += 1
            except (OSError, ConfigError) as exc:
                self.win._error_dialog(T('Не удалось удалить копию'), str(exc))
                break
        self.win.log(T('Удалено резервных копий: {0}').format(n))
        self.win.set_status(T('Удалено резервных копий: {0}').format(n))
        self.refresh(keep_selection=False)

    def delete_selected(self):
        items = self._selected_rows()
        if items:
            what = T('эту копию') if len(items) == 1 else T('выбранные копии ({0})').format(len(items))
            self._delete(items, T('Удалить {0}?').format(what))

    def delete_all_of_file(self):
        target = self.filter_combo.get_active_id()
        if not target:
            return
        items = [(r[2], r[1], r[3]) for r in self.store]
        if items:
            self._delete(items, T('Удалить все копии {0} ({1})?').format(self.win.config.label(target), len(items)))

    def _current_text(self, target):
        cfg = self.win.config.files.get(os.path.realpath(target))
        if cfg is not None:
            return cfg.serialize()
        try:
            return backend.read_text(target)
        except OSError:
            return ""

    def _fill_filter(self, all_backups):
        current = self.filter_combo.get_active_id()
        targets = []
        for bk in all_backups:
            if bk["target"] not in targets:
                targets.append(bk["target"])
        self._filling = True
        self.filter_combo.remove_all()
        self.filter_combo.append("", T('Все файлы ({0})').format(len(all_backups)))
        for t in targets:
            n = sum(1 for b in all_backups if b["target"] == t)
            self.filter_combo.append(t, f"{self.win.config.label(t)} ({n})")
        if not current or not self.filter_combo.set_active_id(current):
            self.filter_combo.set_active_id("")
        self._filling = False

    def refresh(self, keep_selection=True):
        sel = self._selected() if keep_selection else None
        self.store.clear()
        all_backups = backend.list_backups()
        self._fill_filter(all_backups)
        target = self.filter_combo.get_active_id()
        backups = [b for b in all_backups if not target or b["target"] == target]
        for bk in backups:
            dt = datetime.fromtimestamp(bk["mtime"])
            title = dt.strftime("%d.%m.%Y %H:%M:%S")
            try:
                same = backend.read_text(bk["path"]) == self._current_text(bk["target"])
            except OSError:
                same = False
            note = T(' · совпадает с текущим') if same else ""
            fname = esc(self.win.config.label(bk["target"]))
            self.store.append([T('<span weight="700">{0}</span>\n<small><span alpha="60%">{1} · {2} · {3} Б{4}</span></small>').format(fname, title, esc(rel_time(dt.strftime("%Y-%m-%d %H:%M"))), bk["size"], note),
                               bk["path"], title, bk["target"]])
        self.delete_all_btn.set_sensitive(bool(target) and bool(backups))
        self.empty.set_text(T('Копий пока нет.\nКопия делается автоматически\nперед каждым сохранением.')
                            if not all_backups else T('У этого файла копий нет'))
        self.empty.set_visible(not backups)
        target = None
        for row in self.store:
            if sel and row[1] == sel[1]:
                target = row.iter
        if target is None and len(self.store):
            target = self.store.get_iter_first()
        if target is not None:
            self.view.get_selection().select_iter(target)
        self.show_selected()
        self.win.update_backups_tab(len(all_backups))

    def show_selected(self):
        sel = self._selected()
        self.buf.set_text("")
        self.restore_btn.set_sensitive(sel is not None)
        self.delete_btn.set_sensitive(sel is not None)
        if sel is None:
            self.sel_title.set_text("")
            self.info.set_text("")
            return
        title, path, target = sel
        try:
            old = backend.read_text(path)
        except OSError as exc:
            self.info.set_text(T('Не удалось прочитать: {0}').format(exc))
            return
        cur = self._current_text(target)
        self.sel_title.set_markup(T('<b>{0}</b>  <span alpha="60%">копия от {1}</span>').format(esc(self.win.config.label(target)), esc(title)))
        self.sel_title.set_tooltip_text(T('Файл: {0}\nКопия: {1}').format(target, path))
        self.restore_btn.set_tooltip_text(T('Записать эту копию в {0}. Текущая версия сохранится как новая копия').format(target))
        old_l, cur_l = old.splitlines(), cur.splitlines()
        diff = list(difflib.unified_diff(cur_l, old_l, T('текущий'), T('копия'), n=2, lineterm=""))
        adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        it = self.buf.get_end_iter
        set_language(self.buf, "sshconfig" if self.full_btn.get_active() else "diff")
        if self.full_btn.get_active():
            self.buf.set_text(old)
        elif HAVE_SOURCE and diff:
            self.buf.set_text("\n".join(diff[2:]) + "\n")
        elif not diff:
            self.buf.insert_with_tags_by_name(it(), T('Копия совпадает с текущим файлом — восстанавливать нечего.'), "dim")
        else:
            for d in diff[2:]:
                tag = "add" if d.startswith("+") else "del" if d.startswith("-") else "hunk" if d.startswith("@@") else None
                if tag:
                    self.buf.insert_with_tags_by_name(it(), d + "\n", tag)
                else:
                    self.buf.insert(it(), d + "\n")
        if diff:
            self.info.set_markup(T('При восстановлении: <span color="#1E9E5A">+{0}</span> <span color="#D64545">−{1}</span> строк относительно текущего файла').format(adds, dels))
        else:
            self.info.set_markup(T('<span alpha="55%">Совпадает с текущим файлом</span>'))
        self.restore_btn.set_sensitive(bool(diff))

    def restore(self):
        sel = self._selected()
        if sel is None:
            return
        title, path, target = sel
        label = self.win.config.label(target)
        if not self.win._confirm(T('Восстановить копию от {0}?').format(title),
                                 T('{0} будет заменён этой копией. Текущая версия сохранится как новая резервная копия — откатить можно в любой момент.').format(label),
                                 ok_label=T('Восстановить')):
            return
        if self.win.save_whole_text(backend.read_text(path), T('{0}: восстановлено из копии от {1}').format(label, title), target):
            self.refresh()


class SettingsPage(Gtk.Box):
    """Applied immediately — no OK button."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        st = win.state.settings
        form = BoxedForm(label_width=22)
        form.section(T('Внешний вид'))
        self.theme_combo = Gtk.ComboBoxText()
        for tid, label in (("system", T('Как в системе')), ("light", T('Светлая')), ("dark", T('Тёмная'))):
            self.theme_combo.append(tid, label)
        self.theme_combo.set_active_id(st.get("theme") or "system")
        form.row(T('Тема'), self.theme_combo)
        self.lang_combo = Gtk.ComboBoxText()
        self.lang_combo.append("auto", T('Как в системе ({0})').format(i18n.LANGUAGES.get(i18n.system_language(), "English")))
        for code, name in i18n.LANGUAGES.items():
            self.lang_combo.append(code, name)
        self.lang_combo.set_active_id(st.get("language") or "auto")
        form.row(T('Язык'), self.lang_combo)
        form.section(T('Терминал'))
        self.term_combo = Gtk.ComboBoxText()
        auto = backend.auto_terminal()
        self.term_combo.append("auto", T('Автоматически ({0})').format(T(backend.TERMINALS[auto][0]) if auto else T('не найден')))
        for tid in backend.available_terminals():
            self.term_combo.append(tid, T(backend.TERMINALS[tid][0]))
        self.term_combo.append("custom", T('Своя команда…'))
        if not self.term_combo.set_active_id(st.get("terminal") or "auto"):
            self.term_combo.set_active_id("auto")
        form.row(T('Эмулятор терминала'), self.term_combo)
        self.custom_entry = form.row(T('Своя команда'), Gtk.Entry(placeholder_text=T('например: tilix -e {cmd}')),
                                     tooltip=T('{cmd} — команда ssh целиком, {title} — заголовок окна'))
        self.custom_entry.set_text(st.get("custom_terminal", ""))
        self.keep_open = Gtk.Switch()
        self.keep_open.set_halign(Gtk.Align.END)
        self.keep_open.set_active(st.get("keep_open", True))
        form.row(T('Не закрывать окно при ошибке ssh'), self.keep_open)

        form.section(T('Список хостов'))
        self.group_combo = Gtk.ComboBoxText()
        for mid, label in GROUPING_MODES:
            self.group_combo.append(mid, T(label).replace(T('Группы: '), "").capitalize())
        self.group_combo.set_active_id(win.grouping())
        form.row(T('Группировка'), self.group_combo)

        form.section(T('Файлы'))
        home = os.path.expanduser("~")
        short = lambda pth: "~" + pth[len(home):] if pth.startswith(home + os.sep) else pth   # noqa: E731
        cfg = Gtk.Label(label=short(backend.CONFIG_PATH), xalign=0, selectable=True)
        cfg.set_tooltip_text(backend.CONFIG_PATH)
        cfg_btn = icon_button("document-edit-symbolic", None, T('Открыть на странице «Конфиг»'))
        cfg_btn.connect("clicked", lambda b: self.win.show_page("file"))
        form.row(T('Конфигурация ssh'), cfg, extra=cfg_btn)
        data = Gtk.Label(label=short(backend.APP_DIR), xalign=0, selectable=True)
        data.set_tooltip_text(backend.APP_DIR)
        data_btn = icon_button("folder-open-symbolic", None, T('Открыть папку'))
        data_btn.connect("clicked", lambda b: backend.spawn_detached(["xdg-open", backend.APP_DIR]))
        form.row(T('Данные приложения'), data, extra=data_btn)
        form.note(Gtk.Label(xalign=0, label=""))
        saved = Gtk.Label(xalign=0, label=T('Изменения применяются сразу.'))
        saved.get_style_context().add_class("muted")
        form.note(saved)

        self.theme_combo.connect("changed", self._on_theme)
        self.lang_combo.connect("changed", self._on_lang)
        self.term_combo.connect("changed", self._apply)
        self.custom_entry.connect("changed", self._apply)
        self.keep_open.connect("notify::active", self._apply)
        self.group_combo.connect("changed", lambda c: self.win.grouping_combo.set_active_id(c.get_active_id()))
        self._sync_sensitive()
        clamp = Gtk.Box()
        form.box.set_size_request(640, -1)
        clamp.pack_start(form.box, False, False, 0)
        self.pack_start(clamp, False, False, 0)

    def _sync_sensitive(self):
        self.custom_entry.set_sensitive(self.term_combo.get_active_id() == "custom")

    def _on_theme(self, combo):
        mode = combo.get_active_id() or "system"
        self.win.state.settings["theme"] = mode
        self.win.state.save()
        apply_theme(mode)

    def _on_lang(self, combo):
        lang = combo.get_active_id() or "auto"
        effective = lang if lang != "auto" else i18n.system_language()
        if effective != i18n.LANG and not self.win.resolve_unsaved():
            combo.handler_block_by_func(self._on_lang)
            combo.set_active_id(self.win.state.settings.get("language") or "auto")
            combo.handler_unblock_by_func(self._on_lang)
            return
        self.win.state.settings["language"] = lang
        self.win.state.save()
        if effective != i18n.LANG:
            GLib.idle_add(lambda: self.win.get_application().switch_language(effective) or False)

    def _apply(self, *a):
        st = self.win.state.settings
        st["terminal"] = self.term_combo.get_active_id() or "auto"
        st["custom_terminal"] = self.custom_entry.get_text().strip()
        st["keep_open"] = self.keep_open.get_active()
        self.win.state.save()
        self._sync_sensitive()
        self.win.set_status(T('Настройки сохранены'))


# ---------------------------------------------------------------- tunnels UI

TUNNEL_STATE_MARKUP = {
    "up": ('#1E9E5A', "●", 'работает'),
    "starting": ('#D98C0F', "●", 'подключение'),
    "reconnecting": ('#D98C0F', "●", 'переподключение'),
    "error": ('#D64545', "●", 'ошибка'),
    "stopped": ('#9AA0A6', "○", 'остановлен'),
}
RESP_SAVE, RESP_SAVE_START = 1, 2


def tunnel_state_markup(state):
    color, dot, text = TUNNEL_STATE_MARKUP.get(state, TUNNEL_STATE_MARKUP["stopped"])
    text = T(text)
    return f'<span color="{color}">{dot}</span> {text}'


def spin(value=0):
    sb = Gtk.SpinButton.new_with_range(0, 65535, 1)
    sb.set_value(value)
    sb.set_numeric(True)
    sb.set_width_chars(7)
    return sb


class TunnelDialog(Gtk.Dialog):
    """Create / edit a tunnel preset."""

    def __init__(self, parent, tunnel, aliases, used_ports=(), config_forwards=None):
        is_new = not tunnel.get("id")
        super().__init__(title=T('Новый туннель') if is_new else T('Туннель'), transient_for=parent, modal=True)
        self.set_default_size(560, -1)
        self.used_ports = set(used_ports)
        self.config_forwards = config_forwards or (lambda alias: [])
        self.tunnel = backend.normalize_tunnel(tunnel)
        self._auto_name = not self.tunnel["name"]
        self._busy = False
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, T('Сохранить'), RESP_SAVE,
                         T('Сохранить и запустить'), RESP_SAVE_START)
        self.get_widget_for_response(RESP_SAVE_START).get_style_context().add_class("suggested-action")
        box = self.get_content_area()
        box.set_border_width(14)
        box.set_spacing(10)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.add(grid)

        self.host_combo = combo_entry(aliases)
        self.host_combo.get_child().set_text(self.tunnel["alias"])
        self.type_combo = Gtk.ComboBoxText()
        for tid, (label, _) in backend.TUNNEL_TYPES.items():
            self.type_combo.append(tid, T(label))
        self.type_desc = Gtk.Label(xalign=0)
        self.type_desc.get_style_context().add_class("muted")
        self.service_combo = Gtk.ComboBoxText()
        self.service_combo.append("", T('Свой — указать адрес и порты вручную'))
        for i, (name, port) in enumerate(backend.SERVICE_PRESETS):
            self.service_combo.append(str(i), f"{name}  ({port})")
        self.service_combo.set_active_id("")
        self.service_combo.set_tooltip_text(T('Типовой сервис только подставляет порты — любые значения можно ввести ниже вручную'))
        self.name_entry = Gtk.Entry(placeholder_text=T('по умолчанию: хост и порт'))
        self.name_entry.set_text(self.tunnel["name"])

        self.listen_title = Gtk.Label(xalign=0)
        self.listen_title.get_style_context().add_class("form-section")
        self.bind_entry = Gtk.Entry(placeholder_text="localhost")
        self.bind_entry.set_text(self.tunnel["bind"])
        self.bind_entry.set_tooltip_text(T('Пусто/localhost — доступно только с этого компьютера.\n0.0.0.0 — доступно из сети (для -R на сервере нужен GatewayPorts)'))
        self.listen_spin = spin(self.tunnel["listen_port"])
        free_btn = Gtk.Button(label=T('Свободный'))
        free_btn.set_tooltip_text(T('Подобрать свободный порт'))
        free_btn.connect("clicked", self._on_free_port)
        listen_box = Gtk.Box(spacing=6)
        listen_box.pack_start(self.listen_spin, False, False, 0)
        listen_box.pack_start(free_btn, False, False, 0)

        self.dest_title = Gtk.Label(xalign=0)
        self.dest_title.get_style_context().add_class("form-section")
        self.dest_entry = Gtk.Entry(placeholder_text="127.0.0.1")
        self.dest_entry.set_text(self.tunnel["dest_host"])
        self.dest_spin = spin(self.tunnel["dest_port"])
        self.dest_hint = Gtk.Label(xalign=0)
        self.dest_hint.set_line_wrap(True)
        self.dest_hint.get_style_context().add_class("muted")

        self.reconnect_check = Gtk.CheckButton(label=T('Переподключать при обрыве'))
        self.reconnect_check.set_active(self.tunnel["reconnect"])
        self.autostart_check = Gtk.CheckButton(label=T('Запускать вместе с приложением'))
        self.autostart_check.set_active(self.tunnel["autostart"])
        self.action_combo = Gtk.ComboBoxText()
        for aid, label in backend.OPEN_ACTIONS:
            self.action_combo.append(aid, T(label))
        self.action_combo.set_active_id(self.tunnel["open_action"])
        self.action_combo.set_tooltip_text(T('Что делать при двойном клике по туннелю в списке'))
        self.action_hint = Gtk.Label(xalign=0)
        self.action_hint.get_style_context().add_class("muted")

        self.preview = Gtk.Label(xalign=0)
        self.preview.set_line_wrap(True)
        self.preview.set_selectable(True)
        self.warning = Gtk.Label(xalign=0)
        self.warning.set_line_wrap(True)
        self.warning.set_max_width_chars(70)

        r = 0
        self.host_label = form_label(T('Хост *'))
        for title, widget in [(T('Хост'), self.host_combo), (T('Тип'), self.type_combo), ("", self.type_desc),
                              (T('Сервис'), self.service_combo), (T('Название'), self.name_entry)]:
            if title:
                grid.attach(self.host_label if widget is self.host_combo else form_label(title), 0, r, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, r, 1, 1)
            r += 1
        grid.attach(self.listen_title, 0, r, 2, 1); r += 1
        self.bind_label = form_label(T('Адрес'))
        grid.attach(self.bind_label, 0, r, 1, 1); grid.attach(self.bind_entry, 1, r, 1, 1); r += 1
        self.listen_label = form_label(T('Порт *'))
        grid.attach(self.listen_label, 0, r, 1, 1); grid.attach(listen_box, 1, r, 1, 1); r += 1
        self.dest_rows = [self.dest_title]
        grid.attach(self.dest_title, 0, r, 2, 1); r += 1
        l1, l2 = form_label(T('Адрес')), form_label(T('Порт *'))
        self.dest_port_label = l2
        grid.attach(l1, 0, r, 1, 1); grid.attach(self.dest_entry, 1, r, 1, 1); r += 1
        grid.attach(l2, 0, r, 1, 1); grid.attach(self.dest_spin, 1, r, 1, 1); r += 1
        grid.attach(self.dest_hint, 1, r, 1, 1); r += 1
        self.dest_rows += [l1, l2, self.dest_entry, self.dest_spin, self.dest_hint]
        grid.attach(self.reconnect_check, 1, r, 1, 1); r += 1
        grid.attach(self.autostart_check, 1, r, 1, 1); r += 1
        self.action_label = form_label(T('Двойной клик'))
        grid.attach(self.action_label, 0, r, 1, 1); grid.attach(self.action_combo, 1, r, 1, 1); r += 1
        grid.attach(self.action_hint, 1, r, 1, 1); r += 1
        grid.attach(required_hint(), 1, r, 1, 1); r += 1
        box.add(self.preview)
        box.add(self.warning)

        self.type_combo.connect("changed", self._update)
        self.action_combo.connect("changed", self._update)
        self.service_combo.connect("changed", self._on_service)
        self.name_entry.connect("changed", self._on_name_changed)
        for w in (self.host_combo.get_child(), self.bind_entry, self.dest_entry):
            w.connect("changed", self._update)
        for w in (self.listen_spin, self.dest_spin):
            w.connect("value-changed", self._update)
        self.dest_spin.connect("value-changed", self._on_dest_port_changed)
        self.type_combo.set_active_id(self.tunnel["type"])
        self.set_default_response(RESP_SAVE_START)
        self.show_all()
        self._update()

    def _on_name_changed(self, entry):
        if not self._busy:
            self._auto_name = not entry.get_text().strip()
        self._update()

    def _on_free_port(self, _):
        base = self.dest_spin.get_value_as_int() if self.type_combo.get_active_id() != "D" else 1080
        self.listen_spin.set_value(backend.suggest_local_port(base or 15000, self.used_ports))

    def _on_dest_port_changed(self, spin_btn):
        sid = self.service_combo.get_active_id()
        if sid and backend.SERVICE_PRESETS[int(sid)][1] != spin_btn.get_value_as_int():
            self.service_combo.handler_block_by_func(self._on_service)
            self.service_combo.set_active_id("")
            self.service_combo.handler_unblock_by_func(self._on_service)
            if self._auto_name:
                self._busy = True
                self.name_entry.set_text("")
                self._busy = False
                self._auto_name = True

    def _on_service(self, combo):
        sid = combo.get_active_id()
        if not sid:
            return
        name, port = backend.SERVICE_PRESETS[int(sid)]
        if self.type_combo.get_active_id() == "D":
            self.type_combo.set_active_id("L")
        self.dest_spin.set_value(port)
        if not self.dest_entry.get_text().strip():
            self.dest_entry.set_text("127.0.0.1")
        if self.type_combo.get_active_id() == "L":
            self.listen_spin.set_value(backend.suggest_local_port(port, self.used_ports))
        if self._auto_name:
            alias = combo_text(self.host_combo)
            self._busy = True
            self.name_entry.set_text(f"{name} @ {alias}" if alias else name)
            self._busy = False
            self._auto_name = True

    def result(self):
        t = dict(self.tunnel)
        t.update(alias=combo_text(self.host_combo), type=self.type_combo.get_active_id() or "L",
                 name=self.name_entry.get_text().strip(), bind=self.bind_entry.get_text().strip(),
                 listen_port=self.listen_spin.get_value_as_int(),
                 dest_host=self.dest_entry.get_text().strip() or "127.0.0.1",
                 dest_port=self.dest_spin.get_value_as_int(),
                 reconnect=self.reconnect_check.get_active(), autostart=self.autostart_check.get_active(),
                 open_action=self.action_combo.get_active_id() or "auto")
        return backend.normalize_tunnel(t)

    def _update(self, *args):
        typ = self.type_combo.get_active_id() or "L"
        if not self._busy and self.listen_spin.get_value_as_int() == 0:
            # pick a free listening port automatically
            base = 1080 if typ == "D" else self.dest_spin.get_value_as_int()
            if typ == "R":
                base = base or 8000
            if base:
                self._busy = True
                self.listen_spin.set_value(backend.suggest_local_port(base, self.used_ports))
                self._busy = False
        self.type_desc.set_text(T(backend.TUNNEL_TYPES[typ][1]))
        if typ == "R":
            self.listen_title.set_text(T('Открыть порт на сервере'))
            self.dest_title.set_text(T('Куда вести (адрес с точки зрения этого компьютера)'))
            self.dest_hint.set_text(T('127.0.0.1 — сервис на этом компьютере; можно IP машины в вашей локальной сети'))
        else:
            self.listen_title.set_text(T('Слушать на этом компьютере'))
            self.dest_title.set_text(T('Куда вести (адрес с точки зрения сервера)'))
            self.dest_hint.set_text(T('127.0.0.1 — сервис на самом сервере; или IP/имя другой машины в его сети (например, БД за бастионом)'))
        for w in self.dest_rows:
            w.set_visible(typ != "D")
        t = self.result()
        problems = backend.tunnel_problems(t)
        for w in (self.action_label, self.action_combo, self.action_hint):
            w.set_visible(typ == "L")
        if typ == "L" and t["listen_port"]:
            self.action_hint.set_text(T('→ откроется ') + backend.tunnel_url(t) if backend.tunnel_is_web(t)
                                      else T('→ скопируется {0}').format(backend.tunnel_local_address(t)))
        set_missing(self.host_combo, not t["alias"], self.host_label)
        set_missing(self.listen_spin, not 0 < t["listen_port"] < 65536, self.listen_label)
        set_missing(self.dest_spin, typ != "D" and not 0 < t["dest_port"] < 65536, self.dest_port_label)
        lines = []
        if not problems:
            lines.append(f"<b>{esc(backend.tunnel_summary(t))}</b>")
            lines.append(f'<tt><small>{esc(" ".join(backend.tunnel_ssh_argv(t)))}</small></tt>')
        self.preview.set_markup("\n".join(lines))
        warn = []
        if problems:
            warn.append(T('Не хватает: ') + ", ".join(problems))
        elif typ != "R" and t["listen_port"] in self.used_ports:
            warn.append(T('Порт {0} уже используется другим вашим туннелем').format(t['listen_port']))
        elif typ != "R" and t["listen_port"] and backend.port_in_use(t["listen_port"], t["bind"] or "127.0.0.1"):
            warn.append(T('Порт {0} сейчас занят на этом компьютере').format(t['listen_port']))
        if typ != "D" and t["listen_port"] and t["listen_port"] < 1024 and typ == "L":
            warn.append(T('Порты ниже 1024 требуют прав root — выберите порт ≥ 1024'))
        fw = self.config_forwards(t["alias"])
        if fw:
            warn.append(T('В конфиге этого хоста уже есть пробросы (') + "; ".join(fw) +
                        T(') — ssh откроет их вместе с этим туннелем'))
        self.warning.set_markup("\n".join(f'<span color="#D98C0F">⚠ {esc(w)}</span>' for w in warn))
        ok = not problems
        self.get_widget_for_response(RESP_SAVE).set_sensitive(ok)
        self.get_widget_for_response(RESP_SAVE_START).set_sensitive(ok)


class TunnelList(Gtk.Box):
    """List of tunnel presets with start/stop. alias=None → all hosts."""

    def __init__(self, win, alias=None, per_host=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.alias = alias
        self.per_host = per_host
        # status markup, title, host, summary, id, tooltip
        self.store = Gtk.ListStore(str, str, str, str, str, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_tooltip_column(5)
        self.view.set_tooltip_text(None)
        cols = [(T('Статус'), 0, 130, True), (T('Название'), 1, 150, False), (T('Хост'), 2, 120, False),
                (T('Откуда ⇒ где доступно'), 3, 200, False)]
        for title, idx, width, markup in cols:
            if per_host and idx == 2:
                continue
            r = Gtk.CellRendererText()
            if idx != 0:
                r.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, r, **({"markup": idx} if markup else {"text": idx}))
            col.set_resizable(True)
            col.set_min_width(width)
            if idx == 3:
                col.set_expand(True)
            self.view.append_column(col)
        self.view.get_selection().connect("changed", lambda s: self._update_buttons())
        self.view.connect("row-activated", lambda v, path, col: self.win.activate_tunnel(self.store[path][4]))
        self.view.connect("button-press-event", self._on_button)

        self.empty = Gtk.Label(justify=Gtk.Justification.CENTER)
        self.empty.get_style_context().add_class("muted")
        self.empty.set_no_show_all(True)
        overlay = Gtk.Overlay()
        overlay.add(scrolled(self.view, min_height=70, boxed=True))
        overlay.add_overlay(self.empty)
        self.pack_start(overlay, True, True, 0)

        self.info = Gtk.Label(xalign=0)
        self.info.set_line_wrap(True)
        self.info.get_style_context().add_class("muted")
        self.info.set_no_show_all(True)
        self.pack_start(self.info, False, False, 0)

        bb = Gtk.Box(spacing=6)
        self.toggle_btn = icon_button("media-playback-start-symbolic", T('Запустить'))
        self.toggle_btn.get_style_context().add_class("tonal")
        self.toggle_btn.connect("clicked", lambda b: self._on_toggle())
        self.add_btn = icon_button("list-add-symbolic", T('Туннель'))
        self.add_btn.set_tooltip_text(T('Новый проброс порта'))
        self.add_btn.connect("clicked", lambda b: self.win.edit_tunnel(None, alias=self.alias))
        self.edit_btn = icon_button("document-edit-symbolic", None, T('Изменить'))
        self.edit_btn.connect("clicked", lambda b: self._with_sel(self.win.edit_tunnel))
        self.del_btn = icon_button("user-trash-symbolic", None, T('Удалить'))
        self.del_btn.connect("clicked", lambda b: self._with_sel(self.win.delete_tunnel))
        self.copy_btn = icon_button("edit-copy-symbolic", None, T('Скопировать локальный адрес'))
        self.copy_btn.connect("clicked", lambda b: self._with_sel(self.win.copy_tunnel_address))
        self.web_btn = icon_button("web-browser-symbolic", None, T('Открыть в браузере'))
        self.web_btn.connect("clicked", lambda b: self._with_sel(self.win.open_tunnel_in_browser))
        bb.pack_start(self.toggle_btn, False, False, 0)
        bb.pack_start(self.add_btn, False, False, 0)
        for w in (self.web_btn, self.copy_btn, self.del_btn, self.edit_btn):
            bb.pack_end(w, False, False, 0)
        self.pack_start(bb, False, False, 0)
        self.refresh()

    def set_alias(self, alias):
        self.alias = alias
        self.add_btn.set_sensitive(alias is not None or not self.per_host)
        self.refresh()

    def selected_id(self):
        model, it = self.view.get_selection().get_selected()
        return model[it][4] if it is not None else None

    def _with_sel(self, fn):
        tid = self.selected_id()
        if tid:
            fn(tid)

    def _on_toggle(self):
        self._with_sel(self.win.toggle_tunnel)

    def _on_button(self, view, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            hit = view.get_path_at_pos(int(event.x), int(event.y))
            if not hit:
                return False
            view.get_selection().select_path(hit[0])
            tid = self.selected_id()
            active = self.win.tunnel_active(tid)
            menu = Gtk.Menu()
            t = self.win.state.tunnel(tid)
            items = []
            if t and backend.tunnel_is_web(t):
                items.append((T('Открыть в браузере'), self.win.activate_tunnel))
            for label, fn in items + [(T('Остановить') if active else T('Запустить'), self.win.toggle_tunnel),
                              (T('Изменить…'), self.win.edit_tunnel),
                              (T('Скопировать адрес'), self.win.copy_tunnel_address),
                              (T('Удалить…'), self.win.delete_tunnel)]:
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _i, f=fn: f(tid))
                menu.append(item)
            menu.show_all()
            menu.attach_to_widget(view, None)
            menu.popup_at_pointer(event)
            return True
        return False

    def refresh(self):
        sel = self.selected_id()
        self.store.clear()
        tunnels = [t for t in self.win.state.tunnels if not self.per_host or t["alias"] == self.alias]
        for t in tunnels:
            state, msg = self.win.tunnel_state(t["id"])
            hint = (T('Двойной клик — открыть в браузере') if backend.tunnel_is_web(t)
                    else T('Двойной клик — запустить и скопировать адрес') if t["type"] != "R"
                    else T('Двойной клик — запустить'))
            tip = backend.tunnel_summary(t) + (f"\n{msg}" if msg else "") + f"\n\n{hint}"
            self.store.append([tunnel_state_markup(state), backend.tunnel_title(t), t["alias"],
                               backend.tunnel_summary(t), t["id"], esc(tip)])
        if self.per_host and self.alias is None:
            self.empty.set_text(T('Туннели доступны только для конкретного хоста'))
        else:
            self.empty.set_text(T('Туннелей нет.\nНажмите «+ Туннель», чтобы пробросить порт'))
        self.empty.set_visible(not tunnels)
        if self.per_host:
            fw = self.win.config_forwards(self.alias) if self.alias else []
            self.info.set_text(T('В конфиге хоста заданы пробросы (открываются при каждом ssh к нему): ') +
                               "; ".join(fw) if fw else "")
            self.info.set_visible(bool(fw))
        for row in self.store:
            if row[4] == sel:
                self.view.get_selection().select_iter(row.iter)
        self._update_buttons()

    def _update_buttons(self):
        tid = self.selected_id()
        for w in (self.toggle_btn, self.edit_btn, self.del_btn, self.copy_btn, self.web_btn):
            w.set_sensitive(tid is not None)
        if tid is None:
            return
        active = self.win.tunnel_active(tid)
        box = self.toggle_btn.get_child()
        img, label = box.get_children()
        img.set_from_icon_name("media-playback-stop-symbolic" if active else "media-playback-start-symbolic",
                               Gtk.IconSize.BUTTON)
        label.set_text(T('Остановить') if active else T('Запустить'))
        t = self.win.state.tunnel(tid)
        self.copy_btn.set_sensitive(t is not None and t["type"] != "R")
        self.web_btn.set_sensitive(t is not None and t["type"] == "L")
        self.web_btn.set_tooltip_text(T('Открыть в браузере') + ("" if t is None or backend.tunnel_is_web(t)
                                                            else T(' (порт не похож на веб-сервис)')))



class SessionsList(Gtk.Box):
    """Active ssh client processes of this user (any terminal, not only ours)."""
    KIND_COLORS = {"сессия": "#1E9E5A", "туннель": "#5B8DEF", "команда": "#D98C0F", "ControlMaster": "#8E6CF0"}

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        # host markup, kind, server, started, duration, pid, tooltip, host
        self.store = Gtk.ListStore(str, str, str, str, str, int, str, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_tooltip_column(6)
        for title, idx, width, markup in [(T('Хост'), 0, 240, True), (T('Тип'), 1, 0, False),
                                          (T('Сервер'), 2, 200, False), (T('Начало'), 3, 0, False),
                                          (T('Длительность'), 4, 0, False), ("PID", 5, 0, False)]:
            r = Gtk.CellRendererText()
            if idx in (0, 2):   # long values: shrink with "…"; short ones always fully visible
                r.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, r, **({"markup": idx} if markup else {"text": idx}))
            col.set_resizable(True)
            col.set_min_width(width)
            if idx == 2:
                col.set_expand(True)
            self.view.append_column(col)
        self.view.get_selection().connect("changed", lambda s: self._update_buttons())
        self.view.connect("row-activated", lambda v, path, c: self.win.goto_host(self.store[path][7]))
        self.view.set_tooltip_text(None)
        self.empty = Gtk.Label(label=T('Нет активных ssh-подключений'), justify=Gtk.Justification.CENTER)
        self.empty.get_style_context().add_class("muted")
        self.empty.set_no_show_all(True)
        overlay = Gtk.Overlay()
        overlay.add(scrolled(self.view, min_height=70, boxed=True))
        overlay.add_overlay(self.empty)
        self.pack_start(overlay, True, True, 0)

        bb = Gtk.Box(spacing=6)
        self.goto_btn = icon_button("go-jump-symbolic", T('К хосту'))
        self.goto_btn.set_tooltip_text(T('Выбрать хост в списке (двойной клик)'))
        self.goto_btn.connect("clicked", lambda b: self._with_sel(lambda r: self.win.goto_host(r[7])))
        self.again_btn = icon_button("utilities-terminal-symbolic", T('Ещё одно подключение'))
        self.again_btn.connect("clicked", lambda b: self._with_sel(lambda r: self.win.connect_host(r[7])))
        self.kill_btn = icon_button("process-stop-symbolic", T('Завершить'))
        self.kill_btn.connect("clicked", lambda b: self._with_sel(self._on_kill))
        bb.pack_start(self.goto_btn, False, False, 0)
        bb.pack_start(self.again_btn, False, False, 0)
        bb.pack_end(self.kill_btn, False, False, 0)
        self.pack_start(bb, False, False, 0)
        self._update_buttons()

    def _with_sel(self, fn):
        model, it = self.view.get_selection().get_selected()
        if it is not None:
            fn(model[it])

    def _update_buttons(self):
        model, it = self.view.get_selection().get_selected()
        for w in (self.goto_btn, self.again_btn, self.kill_btn):
            w.set_sensitive(it is not None)

    def _on_kill(self, row):
        pid, host = row[5], row[7]
        if self.win._confirm(T('Завершить ssh-подключение к «{0}»?').format(host),
                             T('Процесс ssh PID {0} получит SIGTERM; сессия в терминале закроется.').format(pid),
                             ok_label=T('Завершить')):
            try:
                backend.terminate_process(pid)
                self.win.log(T('Завершено подключение к {0} (PID {1})').format(host, pid))
            except OSError as exc:
                self.win._error_dialog(T('Не удалось завершить процесс'), str(exc))
            GLib.timeout_add(500, lambda: self.win.refresh_sessions() or False)

    def update(self, sessions):
        model, it = self.view.get_selection().get_selected()
        sel_pid = model[it][5] if it is not None else None
        self.store.clear()
        now = time.time()
        for sess in sessions:
            color = self.KIND_COLORS.get(sess["kind"], "#9AA0A6")
            host = sess["host"] or "?"
            markup = f'<span color="{color}">●</span> {esc((sess["user"] + "@") if sess["user"] else "")}<b>{esc(host)}</b>'
            if sess["from_app"]:
                markup += ' <small><span alpha="55%">Hostkeep</span></small>'
            server = sess["peer"] or "—"
            if sess["via"]:
                server += T('  через {0}').format(sess['via'])
            started = datetime.fromtimestamp(sess["started"])
            start_s = started.strftime("%H:%M" if now - sess["started"] < 86400 else "%d.%m %H:%M")
            kind = T(sess["kind"])
            tip = esc(" ".join(sess["argv"]))
            if sess["command"]:
                tip += T('\nКоманда: {0}').format(esc(sess['command']))
            self.store.append([markup, kind, server, start_s, backend.fmt_duration(now - sess["started"]),
                               sess["pid"], tip, host])
        self.empty.set_visible(not sessions)
        for row in self.store:
            if row[5] == sel_pid:
                self.view.get_selection().select_iter(row.iter)
        self._update_buttons()


# ---------------------------------------------------------------- main window

class SSHManagerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, carry=None):
        super().__init__(application=app, title=APP_TITLE)
        self.set_default_size(1180, 720)
        self.state = backend.State()
        apply_theme(self.state.settings.get("theme", "system"))
        self.config = backend.ConfigSet.load()
        self.keys = backend.list_private_keys()
        self.test_results = {}      # alias -> (ok, message)
        self.collapsed = set()      # collapsed group names
        self.current_id = None      # block id shown in the editor
        self.work = None            # working copy of that block
        self.dirty = False
        self.form_dirty = False
        self.text_dirty = False
        self._loading = False
        self._rebuilding = False
        self._reverting = False
        self._warned_external = False
        self.runners = {}           # tunnel id -> backend.TunnelRunner
        self._timers = []
        self._on_up_action = {}     # tunnel id -> "browser" | "copy", run once the tunnel is up
        self.sessions = []          # active ssh client processes
        self.connected = {}         # block id -> number of interactive sessions
        self._sessions_busy = False
        if not self.state.settings.get("grouping"):
            has_meta = any(b.meta("group") for b in self.config.blocks())
            self.state.settings["grouping"] = "meta" if has_meta else "prefix"

        self._build_header()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        self.pages = Gtk.Stack()
        self.pages.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.pages.set_transition_duration(120)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(400)
        paned.pack1(self._build_hosts_pane(), False, False)
        paned.pack2(self._build_editor_pane(), True, False)
        self.pages.add_named(paned, "hosts")
        self._build_other_pages()
        self.pages.connect("notify::visible-child-name", self._on_page_changed)
        body = Gtk.Box()
        body.pack_start(self._build_rail(), False, False, 0)
        body.pack_start(self.pages, True, True, 0)
        root.pack_start(body, True, True, 0)

        status_ev = Gtk.EventBox()
        status_ev.set_tooltip_text(T('Открыть журнал'))
        status_ev.connect("button-press-event", lambda *a: self.show_page("log"))
        status_row = Gtk.Box()
        status_ev.add(status_row)
        status_row.get_style_context().add_class("status-row")
        self.status_label = Gtk.Label(label=T('Готово'), xalign=0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        for m in ("start", "top", "bottom"):
            getattr(self.status_label, f"set_margin_{m}")(6 if m != "start" else 12)
        status_row.pack_start(self.status_label, True, True, 0)
        self.path_label = Gtk.Label(label=backend.CONFIG_PATH.replace(os.path.expanduser("~"), "~", 1), xalign=1)
        self.path_label.set_margin_end(12)
        status_row.pack_end(self.path_label, False, False, 0)
        root.pack_start(status_ev, False, True, 0)

        self.connect("delete-event", self._on_delete_event)
        self.connect("key-press-event", self._on_key_press)
        self.show_all()
        self.nav_buttons["hosts"].set_active(True)
        self.refresh_include_warnings()
        self._update_tunnels_tab()
        self.update_backups_tab(len(backend.list_backups()))
        self._show_editor(None)
        self.rebuild_tree()
        self.log(T('Загружен {0}: {1} блоков в {2} файл(ах)').format(backend.CONFIG_PATH, len(self.config.blocks()), len(self.config.files)))
        self._timers.append(GLib.timeout_add_seconds(3, self._watch_file))
        self.refresh_sessions()
        self._timers.append(GLib.timeout_add_seconds(3, lambda: self.refresh_sessions() or True))
        if carry:
            self._adopt(carry)
            return
        for t in self.state.tunnels:
            if t.get("autostart"):
                self.start_tunnel(t["id"])

    # ---------- live rebuild (language switch)

    def snapshot(self):
        """State that must survive rebuilding the window."""
        cur = self.selected_block()
        return {"runners": self.runners, "on_up": self._on_up_action, "tests": self.test_results,
                "collapsed": self.collapsed, "page": self.current_page(), "host": cur.title if cur else None,
                "search": self.search.get_text(), "size": self.get_size(), "position": self.get_position(),
                "maximized": self.is_maximized(), "log": buffer_text(self.log_buffer)}

    def _adopt(self, c):
        self.runners = c["runners"]
        self._on_up_action = c["on_up"]
        for r in self.runners.values():          # re-route tunnel callbacks to this window
            r.on_state = lambda i, st, m: GLib.idle_add(self._on_tunnel_state, i, st, m)
            r.on_log = lambda i, line: GLib.idle_add(self._on_tunnel_log, i, line)
        self.test_results = c["tests"]
        self.collapsed = c["collapsed"]
        self.log_buffer.set_text(c["log"])
        self.resize(*c["size"])
        self.move(*c["position"])
        if c["maximized"]:
            self.maximize()
        self.search.set_text(c["search"])
        self.rebuild_tree()
        self.refresh_tunnels()
        if c["host"]:
            b = next((x for x in self.config.blocks() if x.title == c["host"]), None)
            if b is not None:
                self._select_row(b.id)
        self.show_page(c["page"] or "hosts")

    def dispose(self):
        for tid in self._timers:
            GLib.source_remove(tid)
        self._timers = []
        self.destroy()

    # ---------- construction

    def _build_header(self):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.add_btn.set_tooltip_text(T('Новый хост из шаблона (Ctrl+N)'))
        self.add_btn.get_style_context().add_class("flat")
        self.add_btn.connect("clicked", lambda b: self.on_add_clicked())
        header.pack_start(self.add_btn)
        title_box = Gtk.Box(spacing=8)
        title_box.pack_start(app_icon_image(), False, False, 0)
        self.header_title = Gtk.Label(label=APP_TITLE)
        self.header_title.get_style_context().add_class("section-title")
        title_box.pack_start(self.header_title, False, False, 0)
        header.set_custom_title(title_box)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text(T('Перечитать ~/.ssh/config'))
        refresh_btn.get_style_context().add_class("flat")
        refresh_btn.connect("clicked", lambda b: self.reload_config(ask=True))
        header.pack_end(refresh_btn)

    def _build_rail(self):
        """Vertical navigation: icon + caption, badges with counters."""
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rail.get_style_context().add_class("rail")
        self.nav_buttons = {}
        self.nav_badges = {}
        group = None
        items = [("hosts", "network-server-symbolic", T('Хосты')),
                 ("tunnels", "network-transmit-receive-symbolic", T('Туннели')),
                 ("sessions", "computer-symbolic", T('Сессии')),
                 ("templates", "edit-copy-symbolic", T('Шаблоны')),
                 ("file", "text-x-generic-symbolic", T('Конфиг')),
                 ("backups", "document-open-recent-symbolic", T('Копии')),
                 ("log", "utilities-terminal-symbolic", T('Журнал')),
                 (None, None, None),
                 ("settings", "emblem-system-symbolic", T('Настройки'))]
        tips = {"hosts": T('Хосты (Ctrl+1)'), "tunnels": T('Туннели (Ctrl+2)'), "sessions": T('Активные ssh-подключения (Ctrl+3)'),
                "templates": T('Шаблоны хостов (Ctrl+4)'), "file": T('~/.ssh/config целиком (Ctrl+5)'),
                "backups": T('Резервные копии (Ctrl+6)'), "log": T('Журнал (Ctrl+7)'), "settings": T('Настройки')}
        for name, icon, caption in items:
            if name is None:
                rail.pack_start(Gtk.Box(), True, True, 0)   # pushes settings to the bottom
                continue
            btn = Gtk.RadioButton.new_from_widget(group)
            group = group or btn
            btn.set_mode(False)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            ov = Gtk.Overlay()
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
            img.set_margin_start(14)
            img.set_margin_end(14)
            ov.add(img)
            badge = Gtk.Label()
            badge.get_style_context().add_class("badge")
            badge.set_halign(Gtk.Align.END)
            badge.set_valign(Gtk.Align.START)
            badge.set_no_show_all(True)
            ov.add_overlay(badge)
            v.pack_start(ov, False, False, 0)
            lbl = Gtk.Label(label=caption)
            lbl.get_style_context().add_class("rail-label")
            v.pack_start(lbl, False, False, 0)
            btn.add(v)
            btn.set_tooltip_text(tips[name])
            btn.connect("toggled", lambda b, n=name: b.get_active() and self.pages.set_visible_child_name(n))
            rail.pack_start(btn, False, False, 0)
            self.nav_buttons[name] = btn
            self.nav_badges[name] = badge
        return rail

    def set_badge(self, name, n, kind="ok"):
        badge = self.nav_badges[name]
        ctx = badge.get_style_context()
        for k in ("ok", "quiet", "warn"):
            ctx.remove_class(k)
        if kind:
            ctx.add_class(kind)
        badge.set_text(str(n))
        badge.set_visible(bool(n))

    def _build_hosts_pane(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class("sidebar")
        box.set_size_request(380, -1)

        top = Gtk.Box(spacing=6)
        top.set_margin_start(12)
        top.set_margin_end(12)
        top.set_margin_top(12)
        self.search = Gtk.SearchEntry(placeholder_text=T('Поиск хостов…'))
        self.search.set_tooltip_text(T('Имя, адрес, пользователь, группа. Enter — подключиться к первому найденному.\nCtrl+F — перейти к поиску'))
        self.search.connect("search-changed", lambda e: self.rebuild_tree())
        self.search.connect("activate", self._on_search_activate)
        top.pack_start(self.search, True, True, 0)

        # grouping: hidden combo keeps the state, a popover with radios is the UI
        self.grouping_combo = Gtk.ComboBoxText()
        for mid, label in GROUPING_MODES:
            self.grouping_combo.append(mid, T(label))
        self.grouping_combo.set_active_id(self.state.settings.get("grouping", "prefix"))
        self.grouping_combo.connect("changed", self._on_grouping_changed)
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pbox.set_border_width(8)
        head = Gtk.Label(label=T('ГРУППИРОВКА'), xalign=0)
        head.get_style_context().add_class("form-section")
        pbox.pack_start(head, False, False, 0)
        group_radio = None
        for mid, label in GROUPING_MODES:
            rb = Gtk.RadioButton.new_with_label_from_widget(group_radio, T(label).replace(T('Группы: '), "").capitalize())
            group_radio = group_radio or rb
            rb.set_active(mid == self.grouping_combo.get_active_id())
            rb.connect("toggled", lambda b, m=mid: b.get_active() and self.grouping_combo.set_active_id(m))
            pbox.pack_start(rb, False, False, 0)
        pbox.show_all()
        pop.add(pbox)
        group_btn = Gtk.MenuButton()
        group_btn.set_image(Gtk.Image.new_from_icon_name("view-list-symbolic", Gtk.IconSize.BUTTON))
        group_btn.set_tooltip_text(T('Группировка'))
        group_btn.set_popover(pop)
        group_btn.get_style_context().add_class("flat")
        top.pack_start(group_btn, False, False, 0)
        box.pack_start(top, False, False, 0)
        self.count_label = Gtk.Label()   # kept for compatibility, count is in the search placeholder

        # name markup (2 lines), address, user, via, right-side meta markup, block id, tooltip, is_group
        self.store = Gtk.TreeStore(str, str, str, str, str, int, str, bool)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_enable_search(False)
        self.view.set_headers_visible(False)
        self.view.set_tooltip_column(6)
        self.view.set_level_indentation(0)
        name_r = Gtk.CellRendererText(ypad=5)
        name_r.set_property("ellipsize", Pango.EllipsizeMode.END)
        name_col = Gtk.TreeViewColumn(T('Хост'), name_r, markup=0)
        name_col.set_expand(True)
        self.view.append_column(name_col)
        meta_r = Gtk.CellRendererText(xalign=1, xpad=8)
        self.view.append_column(Gtk.TreeViewColumn("", meta_r, markup=4))
        sel = self.view.get_selection()
        sel.set_select_function(lambda s, m, path, cur, *a: not m[path][7])
        sel.connect("changed", self._on_selection_changed)
        self.view.connect("row-activated", self._on_row_activated)
        self.view.connect("row-collapsed", self._on_row_toggled, True)
        self.view.connect("row-expanded", self._on_row_toggled, False)
        self.view.connect("button-press-event", self._on_tree_button)

        self.empty_label = Gtk.Label(label=T('Хостов нет\nНажмите «+», чтобы добавить'), justify=Gtk.Justification.CENTER)
        self.empty_label.set_halign(Gtk.Align.CENTER)
        self.empty_label.set_valign(Gtk.Align.CENTER)
        self.empty_label.get_style_context().add_class("muted")
        self.empty_label.set_no_show_all(True)
        overlay = Gtk.Overlay()
        overlay.add(scrolled(self.view))
        overlay.add_overlay(self.empty_label)
        box.pack_start(overlay, True, True, 0)

        btn_box = Gtk.Box(spacing=4)
        btn_box.set_border_width(12)
        btn_box.set_margin_top(0)
        self.connect_btn = icon_button("utilities-terminal-symbolic", T('Подключиться'))
        self.connect_btn.get_style_context().add_class("tonal")
        self.connect_btn.set_tooltip_text(T('Открыть ssh в терминале (двойной клик / Enter)'))
        self.connect_btn.connect("clicked", lambda b: self.connect_selected())
        btn_box.pack_start(self.connect_btn, True, True, 0)
        self.dup_btn = icon_button("edit-copy-symbolic", None, T('Дублировать хост'))
        self.dup_btn.connect("clicked", lambda b: self.on_duplicate())
        btn_box.pack_start(self.dup_btn, False, False, 0)
        self.del_btn = icon_button("user-trash-symbolic", None, T('Удалить хост (Delete)'))
        self.del_btn.connect("clicked", lambda b: self.on_delete())
        btn_box.pack_start(self.del_btn, False, False, 0)
        box.pack_start(btn_box, False, False, 0)
        return box

    def _build_editor_pane(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_border_width(20)
        outer.set_margin_bottom(8)
        outer.get_style_context().add_class("content")

        self.hosts_warn = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.hosts_warn.set_no_show_all(True)
        outer.pack_start(self.hosts_warn, False, False, 0)
        self.editor_stack = Gtk.Stack()
        self.editor_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.editor_stack.set_transition_duration(100)
        outer.pack_start(self.editor_stack, True, True, 0)

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty.set_valign(Gtk.Align.CENTER)
        empty_icon = Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.DIALOG)
        empty_icon.set_pixel_size(64)
        empty_icon.get_style_context().add_class("muted")
        empty_text = Gtk.Label(justify=Gtk.Justification.CENTER)
        empty_text.set_markup(T('<span size="large" weight="bold">Выберите хост</span>\n<span alpha="60%">или нажмите «+», чтобы добавить новый</span>'))
        empty.pack_start(empty_icon, False, False, 0)
        empty.pack_start(empty_text, False, False, 0)
        self.editor_stack.add_named(empty, "empty")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.editor_stack.add_named(box, "editor")

        # title + actions
        head = Gtk.Box(spacing=8)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.host_title = Gtk.Label(xalign=0)
        self.host_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.host_title.get_style_context().add_class("host-title")
        self.host_subtitle = Gtk.Label(xalign=0)
        self.host_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        self.host_subtitle.set_selectable(True)
        self.host_subtitle.get_style_context().add_class("muted")
        titles.pack_start(self.host_title, False, False, 0)
        titles.pack_start(self.host_subtitle, False, False, 0)
        head.pack_start(titles, True, True, 0)

        self.ed_connect_btn = icon_button("utilities-terminal-symbolic", T('Подключиться'))
        self.ed_connect_btn.get_style_context().add_class("tonal")
        self.ed_connect_btn.connect("clicked", lambda b: self.connect_selected())
        self.test_btn = icon_button("network-transmit-receive-symbolic", None,
                                    T('Проверить вход без пароля (BatchMode)'))
        self.test_btn.connect("clicked", lambda b: self.on_test())
        copy_btn = icon_button("edit-copy-symbolic", None, T('Скопировать команду ssh'))
        copy_btn.connect("clicked", lambda b: self.on_copy_command())

        more = Gtk.Menu()
        self.apply_tpl_item = Gtk.MenuItem(label=T('Применить шаблон'))
        self.apply_tpl_menu = Gtk.Menu()
        self.apply_tpl_item.set_submenu(self.apply_tpl_menu)
        more.append(self.apply_tpl_item)
        for label, cb in [(T('Пробросить порт (туннель)…'), self.on_new_tunnel),
                          (T('Сохранить как шаблон…'), self.on_save_as_template),
                          (T('Скопировать ключ на сервер (ssh-copy-id)'), self.on_copy_id),
                          (T('Открыть файлы по SFTP'), self.on_sftp),
                          (None, None),
                          (T('Дублировать…'), self.on_duplicate),
                          (T('Удалить…'), self.on_delete)]:
            if label is None:
                more.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, f=cb: f())
            more.append(item)
        more.show_all()
        more_btn = Gtk.MenuButton()
        more_btn.set_image(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        more_btn.set_tooltip_text(T('Ещё действия'))
        more_btn.get_style_context().add_class("flat")
        more_btn.set_popup(more)
        more.connect("show", lambda m: self._fill_apply_template_menu())
        for w in (more_btn, copy_btn, self.test_btn, self.ed_connect_btn):
            head.pack_end(w, False, False, 0)
        box.pack_start(head, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.get_style_context().add_class("pills")
        self.notebook.set_show_border(False)
        self.notebook.append_page(self._build_form(), Gtk.Label(label=T('Параметры')))
        self.host_tunnels = TunnelList(self, per_host=True)
        self.notebook.append_page(self.host_tunnels, Gtk.Label(label=T('Туннели')))
        self.text_view = code_view()
        self.text_buf = self.text_view.get_buffer()
        self.text_buf.connect("changed", self._on_text_changed)
        self.notebook.append_page(scrolled(self.text_view, boxed=True), Gtk.Label(label=T('Текст блока')))
        self.eff_view = code_view(editable=False, line_numbers=False)
        eff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        eff_hint = Gtk.Label(xalign=0, label=T('Что реально применит ssh (ssh -G) с учётом всех Host/Match-блоков и порядка — первое значение побеждает. По сохранённому файлу.'))
        eff_hint.set_line_wrap(True)
        eff_hint.get_style_context().add_class("muted")
        eff_hint.set_margin_top(6)
        eff_hint.set_margin_bottom(6)
        eff_box.pack_start(eff_hint, False, False, 0)
        eff_box.pack_start(scrolled(self.eff_view, boxed=True), True, True, 0)
        self.notebook.append_page(eff_box, Gtk.Label(label=T('Итог (ssh -G)')))
        self.notebook.connect("switch-page", self._on_switch_page)
        box.pack_start(self.notebook, True, True, 0)

        bottom = Gtk.Box(spacing=6)
        self.dirty_label = Gtk.Label(xalign=0)
        self.dirty_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.dirty_label.set_width_chars(10)
        self.dirty_label.get_style_context().add_class("dirty-label")
        bottom.pack_start(self.dirty_label, True, True, 0)
        self.revert_btn = icon_button("edit-undo-symbolic", T('Отменить'))
        self.revert_btn.get_style_context().remove_class("pill")
        self.revert_btn.get_style_context().add_class("flat")
        self.revert_btn.connect("clicked", lambda b: self.on_revert())
        self.save_btn = icon_button("document-save-symbolic", T('Сохранить'))
        self.save_btn.get_style_context().add_class("suggested-action")
        self.save_btn.set_tooltip_text(T('Проверить через ssh -G и записать (Ctrl+S)'))
        self.save_btn.connect("clicked", lambda b: self.on_save())
        bottom.pack_end(self.save_btn, False, False, 0)
        bottom.pack_end(self.revert_btn, False, False, 0)
        box.pack_start(bottom, False, False, 0)
        return outer

    def _build_form(self):
        form = BoxedForm()
        self.form_grid = form.box
        self._form_labels = form.labels
        add = form.row
        self.f = {}

        form.section(T('Хост'))
        self.f["Host"] = add("Host *", Gtk.Entry(placeholder_text=T('имя для «ssh имя»')),
                             tooltip=T('Имя (алиас) для «ssh имя». Можно несколько через пробел и шаблоны: 10.0.1.* , *.prod'))
        self.host_field_label = self._form_labels["Host *"]
        self.f["group"] = add(T('Группа'), combo_entry(), tooltip=T('Хранится комментарием «# @group: …» в блоке'))
        self.f["desc"] = add(T('Описание'), Gtk.Entry(placeholder_text=T('необязательно')),
                             tooltip=T('Хранится комментарием «# @desc: …» в блоке'))
        self.leading_label = Gtk.Label(xalign=0)
        self.leading_label.set_line_wrap(True)
        self.leading_label.get_style_context().add_class("muted")
        form.note(self.leading_label)

        form.section(T('Подключение'))
        self.f["HostName"] = add("HostName", Gtk.Entry(placeholder_text=T('IP или DNS-имя')))
        self.f["User"] = add("User", Gtk.Entry(placeholder_text=T('по умолчанию — ваш логин')))
        self.f["Port"] = add("Port", Gtk.Entry(placeholder_text="22"))
        self.f["ProxyJump"] = add("ProxyJump", combo_entry(), tooltip=T('Jump-хост (бастион); можно цепочку через запятую'))
        self.f["ConnectTimeout"] = add("ConnectTimeout", Gtk.Entry(placeholder_text=T('секунд')))

        form.section(T('Аутентификация'))
        browse = Gtk.Button.new_from_icon_name("document-open-symbolic", Gtk.IconSize.BUTTON)
        browse.set_tooltip_text(T('Выбрать файл ключа'))
        browse.get_style_context().add_class("flat")
        browse.connect("clicked", self._on_browse_key)
        self.f["IdentityFile"] = add("IdentityFile", combo_entry(self.keys), extra=browse)
        self.f["IdentitiesOnly"] = add("IdentitiesOnly", combo_entry(YES_NO))
        self.f["PubkeyAuthentication"] = add("PubkeyAuth", combo_entry(YES_NO), tooltip="PubkeyAuthentication")
        self.f["ForwardAgent"] = add("ForwardAgent", combo_entry(YES_NO))

        eb = Gtk.Box(spacing=2)
        add_btn = icon_button("list-add-symbolic", None, T('Добавить параметр'))
        add_btn.connect("clicked", self._on_extra_add)
        rm_btn = icon_button("list-remove-symbolic", None, T('Убрать выбранный параметр'))
        rm_btn.connect("clicked", self._on_extra_remove)
        eb.pack_start(add_btn, False, False, 0)
        eb.pack_start(rm_btn, False, False, 0)
        head = Gtk.Box(spacing=6)
        hl = Gtk.Label(label=T('ДОПОЛНИТЕЛЬНЫЕ ПАРАМЕТРЫ'), xalign=0)
        hl.get_style_context().add_class("form-section")
        head.pack_start(hl, True, True, 0)
        head.pack_end(eb, False, False, 0)
        form.box.pack_start(head, False, False, 0)
        self.extra_store = Gtk.ListStore(str, str)
        self.extra_view = Gtk.TreeView(model=self.extra_store)
        kw_model = Gtk.ListStore(str)
        for kw in backend.KNOWN_KEYWORDS:
            kw_model.append([kw])
        kr = Gtk.CellRendererCombo(model=kw_model, text_column=0, has_entry=True, editable=True)
        kr.connect("edited", self._on_extra_edited, 0)
        kc = Gtk.TreeViewColumn(T('Параметр'), kr, text=0)
        kc.set_min_width(180)
        kc.set_resizable(True)
        self.extra_view.append_column(kc)
        vr = Gtk.CellRendererText(editable=True)
        vr.connect("edited", self._on_extra_edited, 1)
        vc = Gtk.TreeViewColumn(T('Значение'), vr, text=1)
        vc.set_expand(True)
        self.extra_view.append_column(vc)
        sw = scrolled(self.extra_view, min_height=110, boxed=True)
        sw.set_hexpand(True)
        form.box.pack_start(sw, False, False, 0)
        form.note(required_hint())

        for key, w in self.f.items():
            target = w.get_child() if isinstance(w, Gtk.ComboBox) else w
            target.connect("changed", self._on_form_changed)
        for sig in ("row-changed", "row-deleted", "row-inserted"):
            self.extra_store.connect(sig, self._on_form_changed)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_end(12)
        outer.set_margin_bottom(12)
        outer.pack_start(form.box, False, False, 0)
        sc = scrolled(outer)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return sc

    def _build_other_pages(self):
        self.all_tunnels = TunnelList(self)
        self.pages.add_named(page_box(T('Туннели'), T('Проброс портов через ssh в фоне. Двойной клик — открыть в браузере или скопировать адрес.'), self.all_tunnels), "tunnels")
        self.sessions_list = SessionsList(self)
        self.pages.add_named(page_box(T('Активные сессии'), T('Все ssh-клиенты вашего пользователя — из Hostkeep и из любых терминалов. Обновляется каждые 3 секунды.'),
                                      self.sessions_list), "sessions")
        self.templates_page = TemplatesPage(self)
        self.pages.add_named(page_box(T('Шаблоны'), T('Заготовки для новых хостов. Встроенные можно скопировать и изменить копию.'), self.templates_page), "templates")
        self.file_page = FilePage(self)
        self.pages.add_named(page_box(T('Конфиг'), backend.CONFIG_PATH.replace(os.path.expanduser("~"), "~", 1) +
                                      T(' целиком. Перед записью файл проверяется ssh -G.'), self.file_page), "file")
        self.backups_page = BackupsPage(self)
        self.pages.add_named(page_box(T('Резервные копии'), T('Перед каждой записью файла конфига (и файлов из Include) делается его копия. Выберите копию, посмотрите изменения и восстановите.'),
                                      self.backups_page), "backups")
        self.log_view = monospace_view(editable=False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buffer = self.log_view.get_buffer()
        clear_btn = icon_button("edit-clear-all-symbolic", None, T('Очистить журнал'))
        clear_btn.connect("clicked", lambda b: self.log_buffer.set_text(""))
        sw = scrolled(self.log_view, boxed=True)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.pages.add_named(page_box(T('Журнал'), T('Что делало приложение: сохранения, подключения, туннели, ошибки.'),
                                      sw, actions=[clear_btn]), "log")
        self.settings_page = SettingsPage(self)
        self.pages.add_named(page_box(T('Настройки'), None, self.settings_page), "settings")
        self._update_tunnels_tab()
        self.update_backups_tab(len(backend.list_backups()))

    def update_backups_tab(self, n):
        if hasattr(self, "nav_badges"):
            self.set_badge("backups", n, "quiet")

    # ---------- Include diagnostics

    def _warning_row(self, text, button_label=None, on_click=None, tooltip=None):
        row = Gtk.Box(spacing=10)
        row.get_style_context().add_class("warn-bar")
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.BUTTON)
        icon.get_style_context().add_class("warn-icon")
        icon.set_valign(Gtk.Align.START)
        row.pack_start(icon, False, False, 0)
        label = Gtk.Label(xalign=0)
        label.set_markup(text)
        label.set_line_wrap(True)
        label.set_selectable(True)
        if tooltip:
            label.set_tooltip_text(tooltip)
        row.pack_start(label, True, True, 0)
        if button_label:
            btn = icon_button("emblem-ok-symbolic", button_label)
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda b: on_click())
            row.pack_end(btn, False, False, 0)
        row.show_all()
        return row

    def refresh_include_warnings(self):
        try:
            problems = self.config.include_problems()
        except Exception as exc:  # noqa: BLE001 - diagnostics must never break the UI
            problems = []
            self.log(T('Не удалось проверить Include: {0}').format(exc))
        boxes = [b for b in (getattr(self, "hosts_warn", None), getattr(getattr(self, "file_page", None), "warn_box", None))
                 if b is not None]
        for box in boxes:
            for child in box.get_children():
                box.remove(child)
        for p in problems:
            where = T('{0}, строка {1}').format(esc(self.config.label(p['file'])), p['lineno'])
            if p["kind"] == "inside":
                text = (T('<b>Include «{0}» стоит внутри блока «Host {1}»</b> ({2}).\nssh читает эти файлы только при подключении к {3}, для остальных хостов их нет. Include нужно ставить в начало файла, до первого Host.').format(esc(p['value']), esc(p['block']), where, esc(p['block'])))
                btn, cb = T('Перенести в начало файла'), (lambda p=p: self.fix_include_inside(p))
            elif p["lookalikes"]:
                def mark(name):   # highlight the look-alike letters
                    return "".join(f'<span color="#D64545" weight="bold" underline="single">{esc(c)}</span>'
                                   if backend.ascii_lookalike(c) != c else esc(c) for c in name)
                names = ", ".join(mark(os.path.basename(x)) for x in p["lookalikes"])
                fixed = ", ".join(backend.ascii_lookalike(os.path.basename(x)) for x in p["lookalikes"])
                text = (T('<b>Маска «{0}» не находит файлов</b> ({1}).\nФайл «{2}» почти подходит, но выделенные буквы — кириллица, похожая на латиницу. Для ssh это другое имя.').format(esc(p['value']), where, names))
                btn, cb = T('Переименовать в {0}').format(fixed), (lambda p=p: self.fix_lookalikes(p))
            else:
                text = (T('<b>По Include «{0}» не найдено ни одного файла</b> ({1}). Проверьте путь и маску: относительные пути считаются от ~/.ssh.').format(esc(p['value']), where))
                btn, cb = None, None
            for box in boxes:
                box.pack_start(self._warning_row(text, btn, cb), False, False, 0)
        for box in boxes:
            box.set_visible(bool(problems))
        if hasattr(self, "nav_badges"):
            self.set_badge("file", "!" if problems else 0, "warn")
        if problems and not getattr(self, "_include_warned", False):
            self._include_warned = True
            self.log(T('Проблемы с Include: {0} — подробности и исправление в разделе «Конфиг»').format(len(problems)))

    def fix_include_inside(self, p):
        if not self.resolve_unsaved():
            return
        new_cfg = self.config.copy()
        try:
            new_cfg.move_include_to_top(p["file"], p["lineno"])
        except ConfigError as exc:
            self._error_dialog(T('Не удалось перенести Include'), str(exc))
            return
        if self.commit(new_cfg, T('Include «{0}» перенесён в начало {1}').format(p['value'], self.config.label(p['file']))):
            self.reload_config(quiet=True)

    def fix_lookalikes(self, p):
        pairs = [(src, os.path.join(os.path.dirname(src), backend.ascii_lookalike(os.path.basename(src))))
                 for src in p["lookalikes"]]
        clash = [dst for _, dst in pairs if os.path.exists(dst)]
        if clash:
            self._error_dialog(T('Не удалось переименовать'), T('Уже существует: ') + ", ".join(clash))
            return
        listing = "\n".join(f"{os.path.basename(a)}  →  {os.path.basename(b)}" for a, b in pairs)
        if not self._confirm(T('Переименовать файл(ы)?'), listing, ok_label=T('Переименовать')):
            return
        try:
            for src, dst in pairs:
                os.rename(src, dst)
                self.log(T('Переименован {0} → {1}').format(src, dst))
        except OSError as exc:
            self._error_dialog(T('Не удалось переименовать'), str(exc))
        self.reload_config(quiet=True)

    def show_page(self, name):
        self.nav_buttons[name].set_active(True)

    def current_page(self):
        return self.pages.get_visible_child_name()

    def _on_page_changed(self, stack, _pspec):
        name = stack.get_visible_child_name()
        tips = {"hosts": T('Новый хост из шаблона (Ctrl+N)'), "tunnels": T('Новый туннель (Ctrl+N)'),
                "templates": T('Новый шаблон (Ctrl+N)')}
        self.add_btn.set_tooltip_text(tips.get(name, T('Новый хост из шаблона (Ctrl+N)')))
        if name == "templates" and not self.templates_page.dirty:
            self.templates_page.reload()
        elif name == "file":
            self.file_page.load_current()
        elif name == "backups":
            self.backups_page.refresh(keep_selection=False)   # newest first when the page opens
        elif name == "tunnels":
            self.all_tunnels.refresh()
        elif name == "log":
            self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0, False, 0, 0)

    def on_add_clicked(self):
        page = self.current_page()
        if page == "tunnels":
            self.edit_tunnel(None)
        elif page == "templates":
            self.templates_page.add()
        else:
            self.show_page("hosts")
            self.on_new_host()

    def save_whole_text(self, text, message, path=None):
        """Replace a whole file (main config by default) with `text`."""
        if not self.resolve_unsaved():
            return False
        path = path or self.config.path
        real = os.path.realpath(path)
        new_cfg = self.config.copy()
        old = new_cfg.files.get(real)
        parsed = backend.SSHConfig.parse(text, old.path if old else path, old.mtime if old else None)
        if old is None:          # e.g. restoring a backup of a file that is not included any more
            parsed.mtime = os.stat(path).st_mtime_ns if os.path.exists(path) else None
        if old is new_cfg.main or real == os.path.realpath(new_cfg.main.path):
            new_cfg.main = parsed
        new_cfg.files[real] = parsed
        new_cfg.reload_includes()
        if not self.commit(new_cfg, message):
            return False
        if real not in self.config.files:
            self.config = backend.ConfigSet.load()
        self._show_editor(None)
        self.rebuild_tree()
        return True

    # ---------- small helpers

    def log(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_buffer.insert(self.log_buffer.get_end_iter(), f"[{ts}] {text}\n")
        self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0, False, 0, 0)
        return False

    def set_status(self, text):
        self.status_label.set_text(text)
        return False

    def grouping(self):
        return self.grouping_combo.get_active_id() or "prefix"

    def selected_block(self):
        if self.current_id is None:
            return None
        try:
            return self.config.find(self.current_id)
        except ConfigError:
            return None

    def _ask_text(self, title, prompt, default_value=""):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.add(Gtk.Label(label=prompt, xalign=0))
        entry = Gtk.Entry()
        entry.set_text(default_value)
        entry.set_activates_default(True)
        box.add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        entry.grab_focus()
        response = dialog.run()
        value = entry.get_text().strip() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        return value

    def _confirm(self, text, secondary=None, ok_label=None):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE, text=text)
        if secondary:
            dialog.format_secondary_text(secondary)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, ok_label or "OK", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _error_dialog(self, title, text):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(str(text)[:1500])
        dialog.run()
        dialog.destroy()

    # ---------- tree

    def _haystack(self, b):
        parts = [b.title, b.get("HostName"), b.get("User"), b.get("ProxyJump"), b.meta("group"),
                 b.meta("desc"), backend.group_of(b, self.grouping())]
        return " ".join(p for p in parts if p).lower()

    def _row_for(self, b):
        alias = b.alias
        dot = ""
        if alias in self.test_results:
            ok, msg = self.test_results[alias]
            dot = f'<span color="{"#1E9E5A" if ok else "#D64545"}">●</span> '
        name = esc(b.title)
        if b.alias is None:
            name = f"<i>{name}</i>"
        desc = b.meta("desc")
        addr = b.get("HostName")
        port = b.get("Port")
        if port and port != "22":
            addr = f"{addr}:{port}" if addr else f":{port}"
        user = b.get("User")
        via = b.get("ProxyJump")
        line2 = (f"{user}@" if user and addr else "") + (addr or "")
        if via:
            line2 += T('  ·  через {0}').format(via)
        if b.alias is None:
            line2 = T('общее правило')
        src = getattr(b, "source", None)
        if src and os.path.realpath(src) != os.path.realpath(self.config.path) and self.grouping() != "file":
            line2 += f"  ·  {self.config.label(src)}"
        markup = f'{dot}<span weight="600">{name}</span>'
        if desc:
            markup += f'  <span alpha="50%">{esc(desc)}</span>'
        if line2:
            markup += f'\n<small><span alpha="55%">{esc(line2)}</span></small>'
        n_conn = self.connected.get(b.id, 0)
        n_tun = self.active_tunnels_for(alias) if alias else 0
        st = self.state.stats.get(alias or "", {})
        badges = []
        if n_conn:
            badges.append(f'<span color="#1E9E5A" weight="bold">●{n_conn if n_conn > 1 else ""}</span>')
        if n_tun:
            badges.append(f'<span color="{ACCENT_FROM}" weight="bold">⇄{n_tun if n_tun > 1 else ""}</span>')
        used = " ".join(badges)
        when = rel_time(st.get("last", ""))
        if when:
            used += ("\n" if used else "") + f'<small><span alpha="45%">{esc(when)}</span></small>'
        tip = [f"<b>{esc(b.title)}</b>"]
        if desc:
            tip.append(esc(desc))
        lead = self.config.leading_comments(b.id)
        if lead:
            tip.append(f'<span alpha="70%">{esc(chr(10).join(l.text().strip() for l in lead))}</span>')
        if st.get("count"):
            tip.append(T('Подключений: {0}, последнее: {1}').format(st['count'], st.get('last', '')))
        if alias in self.test_results:
            tip.append(T('Проверка: ') + esc(self.test_results[alias][1]))
        if alias is None:
            tip.append(T('Общее правило — применяется к подходящим хостам, подключиться к нему нельзя'))
        if alias and n_tun:
            tip.append(T('Активных туннелей: {0}').format(n_tun))
        if n_conn:
            tip.append(T('Открытых ssh-сессий: {0}').format(n_conn))
        return [markup, addr, b.get("User"), b.get("ProxyJump"), used, b.id, "\n".join(tip), False]

    def rebuild_tree(self):
        self._rebuilding = True
        try:
            self.store.clear()
            mode = self.grouping()
            query = self.search.get_text().strip().lower()
            words = query.split()
            groups = {}
            total = 0
            for b in self.config.blocks():
                if words:
                    hay = self._haystack(b)
                    if not all(w in hay for w in words):
                        continue
                total += 1
                groups.setdefault(backend.group_of(b, mode) if mode != "none" else "", []).append(b)

            def order(g):
                return (g == backend.RULES_GROUP, g == backend.NO_GROUP, g.startswith("IP "), g.lower())

            for g in sorted(groups, key=order):
                parent = None
                if mode != "none":
                    parent = self.store.append(None, [
                        (f'<small><span weight="bold" alpha="55%">{esc(g)}</span></small>' if mode == "file" else
                         f'<small><span weight="bold" alpha="55%" letter_spacing="1000">{esc(T(g).upper())}</span></small>'),
                        "", "", "", f'<small><span alpha="40%">{len(groups[g])}</span></small>', 0, esc(g), True])
                for b in groups[g]:
                    self.store.append(parent, self._row_for(b))
            if mode != "none":
                it = self.store.get_iter_first()
                while it is not None:
                    name = backend.group_of(self.config.find(self.store[self.store.iter_children(it)][5]), mode) \
                        if self.store.iter_has_child(it) else ""
                    path = self.store.get_path(it)
                    if words or name not in self.collapsed:
                        self.view.expand_row(path, True)
                    it = self.store.iter_next(it)
            n_all = len(self.config.blocks())
            self.count_label.set_text(T('{0} из {1}').format(total, n_all) if words else str(n_all))
            self.search.set_placeholder_text(T('Поиск среди {0} хостов…').format(n_all))
            self.empty_label.set_visible(n_all == 0)
            if self.current_id is not None:
                self._select_row(self.current_id)
        finally:
            self._rebuilding = False
        app = self.get_application()
        if app is not None and hasattr(app, "refresh_tray_menu"):
            app.refresh_tray_menu()

    def _iter_rows(self):
        def walk(it):
            while it is not None:
                yield it
                if self.store.iter_has_child(it):
                    yield from walk(self.store.iter_children(it))
                it = self.store.iter_next(it)
        yield from walk(self.store.get_iter_first())

    def _select_row(self, block_id):
        for it in self._iter_rows():
            if self.store[it][5] == block_id and not self.store[it][7]:
                path = self.store.get_path(it)
                if path.get_depth() > 1:
                    parent = path.copy()
                    parent.up()
                    self.view.expand_row(parent, False)
                self.view.get_selection().select_path(path)
                self.view.scroll_to_cell(path, None, False, 0, 0)
                return True
        return False

    def _update_row(self, block):
        for it in self._iter_rows():
            if self.store[it][5] == block.id and not self.store[it][7]:
                self.store[it] = self._row_for(block)

    def _on_row_toggled(self, view, it, path, collapsed):
        if self._rebuilding or not self.store.iter_has_child(it):
            return
        child = self.store.iter_children(it)
        try:
            name = backend.group_of(self.config.find(self.store[child][5]), self.grouping())
        except ConfigError:
            return
        if collapsed:
            self.collapsed.add(name)
        else:
            self.collapsed.discard(name)

    def _on_grouping_changed(self, combo):
        self.state.settings["grouping"] = combo.get_active_id()
        self.state.save()
        self.rebuild_tree()

    def _on_tree_button(self, view, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            hit = view.get_path_at_pos(int(event.x), int(event.y))
            if not hit or self.store[hit[0]][7]:
                return False
            view.get_selection().select_path(hit[0])
            menu = Gtk.Menu()
            for label, cb in [(T('Подключиться'), self.connect_selected), (T('Пробросить порт…'), self.on_new_tunnel),
                              (T('Проверить доступ'), self.on_test),
                              (T('Скопировать команду'), self.on_copy_command), (None, None),
                              (T('Дублировать…'), self.on_duplicate), (T('Удалить…'), self.on_delete)]:
                if label is None:
                    menu.append(Gtk.SeparatorMenuItem())
                    continue
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _i, f=cb: f())
                menu.append(item)
            menu.show_all()
            menu.attach_to_widget(view, None)
            menu.popup_at_pointer(event)
            return True
        return False

    def _on_row_activated(self, view, path, column):
        if self.store[path][7]:
            if view.row_expanded(path):
                view.collapse_row(path)
            else:
                view.expand_row(path, False)
            return
        self.connect_selected()

    def _on_search_activate(self, entry):
        for it in self._iter_rows():
            if not self.store[it][7]:
                try:
                    b = self.config.find(self.store[it][5])
                except ConfigError:
                    continue
                if b.alias:
                    self._select_row(b.id)
                    self.connect_block(b)
                    return

    def _on_selection_changed(self, selection):
        if self._rebuilding or self._reverting:
            return
        model, it = selection.get_selected()
        if it is None or model[it][7]:
            return
        block_id = model[it][5]
        if block_id == self.current_id:
            return
        prev = self.current_id
        if not self.resolve_unsaved():
            self._reverting = True
            try:
                self._select_row(prev)
            finally:
                self._reverting = False
            return
        try:
            self._show_editor(self.config.find(block_id))
        except ConfigError:
            self._show_editor(None)

    # ---------- editor

    def _show_editor(self, block):
        self._loading = True
        try:
            if block is None:
                self.current_id = None
                self.work = None
                self.editor_stack.set_visible_child_name("empty")
                for w in (self.connect_btn, self.dup_btn, self.del_btn):
                    w.set_sensitive(False)
                self.host_tunnels.set_alias(None)
                return
            self.current_id = block.id
            self.work = block.clone()
            self.work.id = block.id
            self.editor_stack.set_visible_child_name("editor")
            self._load_form(self.work)
            self.text_buf.set_text(self.work.text())
            self.eff_view.get_buffer().set_text("")
            is_host = block.kind == "host"
            self.form_grid.set_sensitive(is_host)
            if not is_host and self.notebook.get_current_page() == PAGE_FORM:
                self.notebook.set_current_page(PAGE_TEXT)
            can_connect = block.alias is not None
            for w in (self.connect_btn, self.ed_connect_btn, self.test_btn):
                w.set_sensitive(can_connect)
            self.dup_btn.set_sensitive(True)
            self.del_btn.set_sensitive(True)
            self.host_tunnels.set_alias(block.alias)
            if self.notebook.get_current_page() == PAGE_EFFECTIVE:
                self._load_effective()
        finally:
            self._loading = False
        self._set_dirty(False)
        self._update_title()

    def _load_form(self, b):
        reset_touched(*(self.f[k] for k in ("Host", "HostName", "Port", "ConnectTimeout")))
        self._loading = True
        try:
            combo_set_items(self.f["group"], self.config.groups())
            combo_set_items(self.f["ProxyJump"], [a for a in self.config.aliases() if a != b.alias])
            self.f["Host"].set_text(" ".join(b.patterns) if b.kind == "host" else "")
            self.f["group"].get_child().set_text(b.meta("group"))
            self.f["desc"].set_text(b.meta("desc"))
            lead = self.config.leading_comments(b.id) if self.current_id else []
            self.leading_label.set_text(T('Комментарий над блоком: ') + " / ".join(l.text().strip() for l in lead)
                                        if lead else "")
            self.leading_label.set_visible(bool(lead))
            used = {}
            extras = []
            for k, v in b.options():
                canon = next((fk for fk in FORM_KEYS if fk.lower() == k.lower()), None)
                if canon and canon not in used:
                    used[canon] = v
                else:
                    extras.append((k, v))
            for k in FORM_KEYS:
                w = self.f[k]
                (w.get_child() if isinstance(w, Gtk.ComboBox) else w).set_text(used.get(k, ""))
            self.extra_store.clear()
            for k, v in extras:
                self.extra_store.append([k, v])
        finally:
            self._loading = False

    def _form_to_block(self, b):
        if b.kind == "host":
            b.set_patterns(backend.split_patterns(self.f["Host"].get_text().strip()))
            b.set_meta("group", combo_text(self.f["group"]))
            b.set_meta("desc", self.f["desc"].get_text())
            desired = []
            for k in FORM_KEYS:
                w = self.f[k]
                val = combo_text(w) if isinstance(w, Gtk.ComboBox) else w.get_text().strip()
                desired.append((k, val))
            desired += [(r[0], r[1]) for r in self.extra_store]
            b.set_options(desired)

    def _sync_work(self):
        """Pulls pending edits (form or text tab) into self.work. Raises
        ConfigError on invalid text."""
        if self.work is None:
            return None
        page = self.notebook.get_current_page()
        if page == PAGE_TEXT and self.text_dirty:
            nb = backend.parse_block_text(buffer_text(self.text_buf))
            nb.id = self.work.id
            self.work = nb
        elif self.form_dirty:
            self._form_to_block(self.work)
        self.form_dirty = False
        self.text_dirty = False
        return self.work

    def _on_switch_page(self, notebook, page, page_num):
        if self.work is None or self._loading:
            return
        old = notebook.get_current_page()
        try:
            if old == PAGE_TEXT and self.text_dirty:
                self._sync_work()
                self._load_form(self.work)
            elif old == PAGE_FORM and self.form_dirty:
                self._sync_work()
        except ConfigError as exc:
            self._error_dialog(T('Ошибка в тексте блока'), str(exc))
            GLib.idle_add(notebook.set_current_page, PAGE_TEXT)
            return
        if page_num == PAGE_TEXT:
            self._loading = True
            self.text_buf.set_text(self.work.text())
            self._loading = False
        if page_num == PAGE_EFFECTIVE:
            self._load_effective()
        if page_num == PAGE_FORM:
            self._validate_form()
        self._update_title()

    def _load_effective(self):
        b = self.selected_block()
        buf = self.eff_view.get_buffer()
        if b is None or b.alias is None:
            buf.set_text(T('Недоступно для общих правил (wildcard / Match).'))
            return
        buf.set_text("…")
        alias = b.alias
        run_async(lambda: backend.effective_config(alias),
                  lambda out: buf.set_text(out) or False,
                  lambda exc: buf.set_text(T('Ошибка: {0}').format(exc)) or False)

    @staticmethod
    def _is_ip(text):
        try:
            ipaddress.ip_address(text.strip("[]"))
            return True
        except ValueError:
            return False

    def form_problems(self):
        """[(widget or None, message)] for the host form; empty when valid."""
        if self.work is None or self.work.kind != "host":
            return []
        out = []
        patterns = backend.split_patterns(self.f["Host"].get_text().strip())
        if not patterns:
            out.append((self.f["Host"], T('укажите Host')))
        needs_hostname = bool(patterns) and not any(backend.is_wildcard(p) or self._is_ip(p) for p in patterns)
        if needs_hostname and not self.f["HostName"].get_text().strip():
            out.append((self.f["HostName"], T('укажите HostName (адрес сервера)')))
        port = self.f["Port"].get_text().strip()
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            out.append((self.f["Port"], T('Port — число от 1 до 65535')))
        timeout = self.f["ConnectTimeout"].get_text().strip()
        if timeout and not timeout.isdigit():
            out.append((self.f["ConnectTimeout"], T('ConnectTimeout — число секунд')))
        for row in self.extra_store:
            key, value = row[0].strip(), row[1].strip()
            if key and not value:
                out.append((None, T('у параметра {0} нет значения').format(key)))
            elif value and not key:
                out.append((None, T('у значения «{0}» не указан параметр').format(value)))
        return out

    def _validate_form(self, force=False):
        problems = self.form_problems()
        bad = {w for w, _ in problems if w is not None}
        patterns = backend.split_patterns(self.f["Host"].get_text().strip())
        needs_hostname = (self.work is not None and self.work.kind == "host" and
                          not any(backend.is_wildcard(p) or self._is_ip(p) for p in patterns))
        self._form_labels["HostName"].set_text("HostName *" if needs_hostname else "HostName")
        self.f["HostName"].set_placeholder_text(T('IP или DNS-имя') if needs_hostname
                                                else T('необязательно: имя хоста — IP или шаблон'))
        for key, label in (("Host", "Host *"), ("HostName", "HostName"), ("Port", "Port"),
                           ("ConnectTimeout", "ConnectTimeout")):
            set_missing(self.f[key], self.f[key] in bad, self._form_labels[label], force=force)
        if problems:
            self.save_btn.set_sensitive(False)
            self.dirty_label.set_text("● " + "; ".join(m for _, m in problems))
            self.dirty_label.set_tooltip_text("\n".join("• " + m for _, m in problems))
        else:
            self.dirty_label.set_tooltip_text(None)
        return not problems

    def _on_form_changed(self, *args):
        self._validate_form()
        if self._loading or self.work is None:
            return
        self.form_dirty = True
        self._set_dirty(True)
        self._update_title()

    def _on_text_changed(self, buf):
        if self._loading or self.work is None:
            return
        self.text_dirty = True
        self._set_dirty(True)

    def _set_dirty(self, dirty):
        self.dirty = dirty
        if not dirty:
            self.form_dirty = False
            self.text_dirty = False
        self.dirty_label.set_text(T('● Есть несохранённые изменения') if dirty else "")
        self.save_btn.set_sensitive(dirty)
        self.revert_btn.set_sensitive(dirty)
        if self.work is not None and self.notebook.get_current_page() == PAGE_FORM:
            self._validate_form()

    def _update_title(self):
        b = self.work
        if b is None:
            return
        if self.notebook.get_current_page() == PAGE_FORM and b.kind == "host":
            title = self.f["Host"].get_text().strip() or T('(без имени)')
            host = self.f["HostName"].get_text().strip()
            user = self.f["User"].get_text().strip()
            port = self.f["Port"].get_text().strip()
            via = combo_text(self.f["ProxyJump"])
        else:
            title = b.title
            host, user, port, via = b.get("HostName"), b.get("User"), b.get("Port"), b.get("ProxyJump")
        self.host_title.set_text(title)
        src = getattr(self.selected_block(), "source", None) if self.current_id else None
        if b.alias is None:
            sub = T('Общее правило: параметры применяются ко всем подходящим хостам')
        else:
            sub = f"{user + '@' if user else ''}{host or b.alias}{':' + port if port and port != '22' else ''}"
            if via:
                sub += T('   через {0}').format(via)
        if src and os.path.realpath(src) != os.path.realpath(self.config.path):
            sub += T('   ·   файл {0}').format(self.config.label(src))
        self.host_subtitle.set_text(sub)

    def _on_browse_key(self, button):
        dialog = Gtk.FileChooserDialog(title=T('Файл приватного ключа'), transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        dialog.set_show_hidden(True)
        dialog.set_current_folder(os.path.expanduser("~/.ssh"))
        if dialog.run() == Gtk.ResponseType.OK and dialog.get_filename():
            path = dialog.get_filename()
            home = os.path.expanduser("~")
            if path.startswith(home + os.sep):
                path = "~" + path[len(home):]
            self.f["IdentityFile"].get_child().set_text(path)
        dialog.destroy()

    def _on_extra_edited(self, renderer, path, text, col):
        self.extra_store[path][col] = text.strip()

    def _on_extra_add(self, _):
        it = self.extra_store.append(["", ""])
        path = self.extra_store.get_path(it)
        self.extra_view.set_cursor(path, self.extra_view.get_column(0), True)

    def _on_extra_remove(self, _):
        model, it = self.extra_view.get_selection().get_selected()
        if it is not None:
            model.remove(it)

    # ---------- unsaved changes

    def resolve_unsaved(self):
        """Returns True when it is OK to drop the editor's current state."""
        if not self.dirty or self.work is None:
            return True
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text=T('Сохранить изменения в «{0}»?').format(self.work.title))
        dialog.add_buttons(T('Не сохранять'), 1, Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           T('Сохранить'), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        resp = dialog.run()
        dialog.destroy()
        if resp == 1:
            self._set_dirty(False)
            return True
        if resp == Gtk.ResponseType.OK:
            return self.on_save()
        return False

    # ---------- file I/O

    def commit(self, new_cfg, message):
        """Validates + writes new_cfg. On success adopts it (block ids stay
        stable) and returns True."""
        old_texts = self.config.texts()
        new_texts = new_cfg.texts()
        changed = [real for real, t in new_texts.items() if t != old_texts.get(real)]
        for real in changed:
            cfg = new_cfg.files[real]
            old = self.config.files.get(real)
            label = new_cfg.label(cfg)
            text = new_texts[real]
            try:
                mtime = backend.write_config(text, cfg.path, expected_mtime=old.mtime if old else None)
            except ExternalChangeError as exc:
                if not self._confirm(T('Файл {0} изменён извне').format(label), T('{0}\nПерезаписать его вашей версией? (старая версия попадёт в резервные копии)').format(exc),
                                     ok_label=T('Перезаписать')):
                    return False
                try:
                    mtime = backend.write_config(text, cfg.path, force=True)
                except (ConfigError, OSError) as exc2:
                    self._error_dialog(T('Не удалось сохранить'), str(exc2))
                    return False
            except ConfigError as exc:
                self._error_dialog(T('ssh отклонил {0} — файл не изменён').format(label), str(exc))
                self.log(T('Ошибка проверки {0}: {1}').format(label, exc))
                return False
            except OSError as exc:
                self._error_dialog(T('Не удалось записать {0}').format(label), str(exc))
                return False
            cfg.mtime = mtime
            if real in self.config.files:      # keep the pre-commit state consistent if a later file fails
                self.config.files[real].mtime = mtime
        self.config = new_cfg
        self._warned_external = False
        GLib.idle_add(lambda: self.refresh_include_warnings() or False)
        if hasattr(self, "file_page"):
            GLib.idle_add(lambda: self.file_page.load_current() or self.backups_page.refresh() or False)
        self.log(message)
        self.set_status(message)
        return True

    def on_save(self):
        if self.work is None:
            return True
        if self.notebook.get_current_page() != PAGE_TEXT or not self.text_dirty:
            problems = self.form_problems()
            if problems:
                self.notebook.set_current_page(PAGE_FORM)
                self._validate_form(force=True)
                self._error_dialog(T('Заполните обязательные поля'), "\n".join("• " + m for _, m in problems))
                return False
        try:
            work = self._sync_work()
        except ConfigError as exc:
            self._error_dialog(T('Ошибка в тексте блока'), str(exc))
            return False
        new_cfg = self.config.copy()
        try:
            new_cfg.replace_block(self.current_id, work.clone())
        except ConfigError as exc:
            self._error_dialog(T('Не удалось сохранить'), str(exc))
            return False
        if new_cfg.texts() == self.config.texts():
            self._set_dirty(False)
            return True
        old_alias = self.selected_block().alias if self.selected_block() else None
        if not self.commit(new_cfg, T('Сохранено: {0}').format(work.title)):
            return False
        new_alias = work.alias
        if old_alias and new_alias and old_alias != new_alias:
            moved = [t for t in self.state.tunnels if t["alias"] == old_alias]
            for t in moved:
                t["alias"] = new_alias
            if moved:
                self.state.save()
                self.log(T('Туннели ({0}) перенесены на новое имя хоста {1}').format(len(moved), new_alias))
                self.refresh_tunnels()
        self._show_editor(self.config.find(self.current_id))
        self.rebuild_tree()
        return True

    def on_revert(self):
        b = self.selected_block()
        self._show_editor(b)

    def reload_config(self, ask=False, quiet=False):
        if ask and not self.resolve_unsaved():
            return
        prev = self.selected_block()
        prev_index = self.config.blocks().index(prev) if prev else None
        prev_title = prev.title if prev else None
        try:
            self.config = backend.ConfigSet.load()
        except OSError as exc:
            self._error_dialog(T('Не удалось прочитать файл'), str(exc))
            return
        self.keys = backend.list_private_keys()
        combo_set_items(self.f["IdentityFile"], self.keys)
        target = None
        blocks = self.config.blocks()
        if prev_title is not None:
            target = next((b for b in blocks if b.title == prev_title), None)
            if target is None and prev_index is not None and prev_index < len(blocks):
                target = blocks[prev_index]
        self._show_editor(target)
        self.rebuild_tree()
        self.file_page.load_current()
        self.refresh_include_warnings()
        if not quiet:
            self.log(T('Перечитан {0}: {1} блоков в {2} файл(ах)').format(backend.CONFIG_PATH, len(blocks), len(self.config.files)))

    def _watch_file(self):
        try:
            stale = self.config.stale()
        except OSError:
            return True
        if stale:
            if not self.dirty:
                self.reload_config(quiet=True)
                self.log(T('Конфиг (или файл из Include) изменён другой программой — перечитан'))
            elif not self._warned_external:
                self._warned_external = True
                self.set_status(T('⚠ Файл изменён другой программой. При сохранении будет предложено перезаписать.'))
                self.log(T('Файл изменён другой программой, а в редакторе есть несохранённые правки'))
        return True

    # ---------- actions: hosts

    def _insert_position(self, cfg, block):
        """Insert a new block after the last block of the same group."""
        mode = self.grouping()
        if mode == "none":
            return None
        g = backend.group_of(block, mode)
        if g in (backend.NO_GROUP, backend.RULES_GROUP):
            return None
        same = [b for b in cfg.blocks() if backend.group_of(b, mode) == g]
        return same[-1].id if same else None

    def on_new_host(self, template_index=None):
        if not self.resolve_unsaved():
            return
        templates = backend.load_templates()
        cur = self.selected_block()
        default_group = cur.meta("group") if cur else ""
        dialog = NewHostDialog(self, templates, self.config.groups(), self.config.aliases(), self.keys,
                               default_group=default_group,
                               default_template=template_index if template_index is not None else 1,
                               files=[(c.path, self.config.label(c)) for c in self.config.file_list()],
                               default_file=getattr(cur, "source", None) if cur else None)
        while True:
            if dialog.run() != Gtk.ResponseType.OK:
                dialog.destroy()
                return
            r = dialog.result()
            problem = None
            if not r["patterns"]:
                problem = T('Укажите имя хоста (Host).')
            elif not r["hostname"] and not any(backend.is_wildcard(p) for p in r["patterns"]) \
                    and r["template"]["name"] != "Подсеть / wildcard":
                problem = T('Укажите HostName (адрес сервера).')
            elif r["proxy"] == "" and r["template"].get("builtin") \
                    and r["template"]["name"].startswith("Через бастион"):
                problem = T('Для этого шаблона укажите ProxyJump (бастион).')
            if problem:
                self._error_dialog(T('Не хватает данных'), problem)
                continue
            dup = [p for p in r["patterns"] if p in self.config.aliases()]
            if dup and not self._confirm(T('Хост «{0}» уже есть в конфиге').format(dup[0]),
                                         T('ssh использует первый подходящий блок. Всё равно добавить?'),
                                         ok_label=T('Добавить')):
                continue
            break
        dialog.destroy()

        alias = next((p for p in r["patterns"] if not backend.is_wildcard(p)), r["patterns"][0])
        options = [("HostName", r["hostname"]), ("User", r["user"]), ("Port", r["port"])]
        fields = {"hostname", "user", "port", "proxyjump", "identityfile"}
        options += [(k, v) for k, v in backend.template_options(r["template"], alias) if k.lower() not in fields]
        options += [("IdentityFile", r["identity"]), ("ProxyJump", r["proxy"])]
        # main fields first, then the template's own order
        first = ["hostname", "user", "port", "identityfile", "proxyjump"]
        order = [k.lower() for k, _ in r["template"].get("options", [])]
        options.sort(key=lambda kv: (0, first.index(kv[0].lower())) if kv[0].lower() in first else
                     (1, order.index(kv[0].lower())) if kv[0].lower() in order else (2, 0))
        block = backend.new_host_block(r["patterns"], options, group=r["group"])
        new_cfg = self.config.copy()
        new_cfg.insert_block(block, after_id=self._insert_position(new_cfg, block), target=r.get("file"))
        if self.commit(new_cfg, T('Добавлен хост {0} (шаблон «{1}»)').format(block.title, r['template'].get('title', r['template']['name']))):
            self.show_page("hosts")
            self.current_id = None
            self._show_editor(self.config.find(block.id))
            self.rebuild_tree()

    def on_duplicate(self):
        if not self.resolve_unsaved():
            return
        src = self.selected_block()
        if src is None or src.kind != "host":
            return
        base = src.alias or src.patterns[0]
        name = self._ask_text(T('Дублировать хост'), T('Имя нового хоста (копия «{0}»):').format(src.title), base + "-copy")
        if not name:
            return
        clone = src.clone()
        clone.set_patterns(backend.split_patterns(name))
        new_cfg = self.config.copy()
        new_cfg.insert_block(clone, after_id=src.id)
        if self.commit(new_cfg, T('Создана копия {0} → {1}').format(src.title, clone.title)):
            self._show_editor(self.config.find(clone.id))
            self.rebuild_tree()
            self.notebook.set_current_page(PAGE_FORM)
            self.f["HostName"].grab_focus()

    def on_delete(self):
        b = self.selected_block()
        if b is None:
            return
        lead = self.config.leading_comments(b.id)
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text=T('Удалить «{0}» из конфига?').format(b.title))
        dialog.format_secondary_text(T('Будут удалены строки:'))
        area = dialog.get_message_area()
        view = monospace_view(editable=False)
        view.get_buffer().set_text(b.text().rstrip("\n"))
        sw = scrolled(view)
        sw.set_min_content_height(120)
        sw.set_min_content_width(460)
        area.pack_start(sw, True, True, 0)
        lead_check = None
        if lead:
            lead_text = "\n".join(l.text() for l in lead)
            lead_check = Gtk.CheckButton(label=T('Также удалить комментарий над блоком:\n') + lead_text)
            lead_check.set_active(not any(l.text().lstrip("# ").lower().startswith("host ") for l in lead))
            area.pack_start(lead_check, False, False, 0)
        area.show_all()
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, T('Удалить'), Gtk.ResponseType.OK)
        dialog.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("destructive-action")
        resp = dialog.run()
        with_lead = bool(lead_check and lead_check.get_active())
        dialog.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        new_cfg = self.config.copy()
        new_cfg.remove_block(b.id, with_leading_comments=with_lead)
        if self.commit(new_cfg, T('Удалён {0}').format(b.title)):
            self._set_dirty(False)
            self._show_editor(None)
            self.rebuild_tree()

    # ---------- actions: templates

    def _fill_apply_template_menu(self):
        for child in self.apply_tpl_menu.get_children():
            self.apply_tpl_menu.remove(child)
        for t in backend.load_templates():
            if not t.get("options"):
                continue
            item = Gtk.MenuItem(label=("" if t.get("builtin") else "★ ") + t.get("title", t["name"]))
            item.set_tooltip_text(t.get("desc", "") + "\n\n" + "\n".join(f"{k} {v}" for k, v in t["options"]))
            item.connect("activate", lambda _i, tpl=t: self.on_apply_template(tpl))
            self.apply_tpl_menu.append(item)
        self.apply_tpl_menu.show_all()
        self.apply_tpl_item.set_sensitive(self.work is not None and self.work.kind == "host")

    def on_apply_template(self, template):
        if self.work is None:
            return
        try:
            work = self._sync_work()
        except ConfigError as exc:
            self._error_dialog(T('Ошибка в тексте блока'), str(exc))
            return
        opts = list(work.options())
        for k, v in backend.template_options(template, work.alias or ""):
            if not v:
                continue
            idx = next((i for i, (ok, _) in enumerate(opts) if ok.lower() == k.lower()), None)
            if idx is None:
                opts.append((k, v))
            else:
                opts[idx] = (opts[idx][0], v)
        work.set_options(opts)
        if template.get("group") and not work.meta("group"):
            work.set_meta("group", template["group"])
        self._load_form(work)
        self._loading = True
        self.text_buf.set_text(work.text())
        self._loading = False
        self._set_dirty(True)
        self.log(T('Применён шаблон «{0}» к {1} — проверьте и сохраните').format(template.get('title', template['name']), work.title))

    def on_save_as_template(self):
        if self.work is None:
            return
        try:
            work = self._sync_work()
        except ConfigError as exc:
            self._error_dialog(T('Ошибка в тексте блока'), str(exc))
            return
        name = self._ask_text(T('Сохранить как шаблон'), T('Название шаблона (HostName не сохраняется):'),
                              T('Как {0}').format(work.alias or work.title))
        if not name:
            return
        templates = backend.load_templates()
        options = [[k, v] for k, v in work.options() if k.lower() != "hostname"]
        existing = next((t for t in templates if t["name"] == name and not t.get("builtin")), None)
        if existing:
            existing["options"] = options
        else:
            templates.append({"name": name, "desc": T('На основе {0}').format(work.title), "group": work.meta("group"),
                              "options": options, "builtin": False})
        backend.save_user_templates(templates)
        self.log(T('Шаблон «{0}» сохранён').format(name))

    def on_templates(self):
        self.show_page("templates")

    # ---------- actions: connect & co

    def connect_selected(self):
        b = self.selected_block()
        if b is not None:
            self.connect_block(b)

    def connect_alias(self, alias):
        b = next((x for x in self.config.blocks() if x.alias == alias), None)
        if b:
            self.connect_block(b)

    def connect_block(self, b):
        alias = b.alias
        if alias is None:
            self.set_status(T('Это общее правило (wildcard/Match) — к нему нельзя подключиться'))
            return
        if self.dirty and b.id == self.current_id:
            self.log(T('Внимание: в редакторе есть несохранённые изменения — подключение по сохранённому файлу'))
        self._run_in_terminal(alias, backend.ssh_command(alias))
        self.state.record_use(alias)
        self._update_row(b)
        GLib.timeout_add(2500, lambda: self.refresh_sessions() or False)
        app = self.get_application()
        if app is not None and hasattr(app, "refresh_tray_menu"):
            app.refresh_tray_menu()

    def _run_in_terminal(self, title, argv, hold="ssh"):
        try:
            term_argv, proc = backend.open_in_terminal(self.state.settings, title, argv, hold)
        except (ConfigError, OSError) as exc:
            self._error_dialog(T('Не удалось открыть терминал'), str(exc))
            return False
        self.log(T('Терминал: ') + " ".join(argv))
        self.set_status(T('Открыт терминал: {0}').format(title))

        def check():
            code = proc.poll() if proc is not None else None
            if code not in (None, 0):
                self.log(T('Терминал завершился с кодом {0}: {1}… — проверьте настройки терминала').format(code, ' '.join(term_argv[:4])))
                self._error_dialog(T('Терминал не запустился'),
                                   T('Команда «{0}» завершилась с кодом {1}.\nВыберите другой терминал в ⚙ Настройки.').format(term_argv[0], code))
            return False
        GLib.timeout_add(1500, check)
        return True

    def on_test(self):
        b = self.selected_block()
        if b is None or b.alias is None:
            return
        alias = b.alias
        self.set_status(T('Проверка {0}…').format(alias))
        self.log(T('Проверка входа без пароля: {0}').format(alias))

        def done(result):
            ok, msg = result
            self.test_results[alias] = result
            self.log(f"{alias}: {T('доступен') if ok else T('ошибка')} — {msg}")
            self.set_status(f"{alias}: {'OK' if ok else msg}")
            for x in self.config.blocks():
                if x.alias == alias:
                    self._update_row(x)
            return False

        run_async(lambda: backend.test_connection(alias), done,
                  lambda exc: self.log(f"{alias}: {exc}"))

    def on_copy_command(self):
        b = self.selected_block()
        if b is None or b.alias is None:
            return
        cmd = " ".join(backend.ssh_command(b.alias))
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(cmd, -1)
        self.set_status(T('Скопировано: {0}').format(cmd))

    def on_copy_id(self):
        b = self.selected_block()
        if b is None or b.alias is None:
            return
        self._run_in_terminal(f"ssh-copy-id {b.alias}",
                              backend.ssh_copy_id_command(b.alias, b.get("IdentityFile")), hold="always")

    def on_sftp(self):
        b = self.selected_block()
        if b is None or b.alias is None:
            return
        try:
            backend.spawn_detached(["xdg-open", f"sftp://{b.alias}/"])
            self.log(T('Открыт sftp://{0}/ в файловом менеджере').format(b.alias))
        except OSError as exc:
            self._error_dialog(T('Не удалось открыть SFTP'), str(exc))

    # ---------- whole-file / backups / settings

    def on_edit_whole_file(self):
        self.show_page("file")

    def on_backups(self):
        self.show_page("backups")

    def on_settings(self):
        self.show_page("settings")

    # ---------- active ssh sessions

    def refresh_sessions(self):
        if self._sessions_busy:
            return
        self._sessions_busy = True
        pids = [r._proc.pid for r in self.runners.values() if r._proc is not None]

        def done(sessions):
            self._sessions_busy = False
            self._on_sessions(sessions)
            return False

        def failed(exc):
            self._sessions_busy = False
            return False
        run_async(lambda: backend.list_ssh_sessions(pids), done, failed)

    def block_for_host(self, host):
        blocks = self.config.blocks()
        return (next((b for b in blocks if host in b.patterns and b.alias), None)
                or next((b for b in blocks if b.alias and b.get("HostName") == host), None))

    def _on_sessions(self, sessions):
        self.sessions = sessions
        self.sessions_list.update(sessions)
        connected = {}
        for sess in sessions:
            if sess["kind"] == "сессия":
                b = self.block_for_host(sess["host"])
                if b is not None:
                    connected[b.id] = connected.get(b.id, 0) + 1
        changed = set(connected) ^ set(self.connected) | {k for k in connected if connected[k] != self.connected.get(k)}
        self.connected = connected
        for bid in changed:
            try:
                self._update_row(self.config.find(bid))
            except ConfigError:
                pass
        n = sum(1 for s in sessions if s["kind"] == "сессия")
        self.set_badge("sessions", n, "ok")

    def goto_host(self, host):
        b = self.block_for_host(host)
        if b is None:
            self.set_status(T('Хоста «{0}» нет в конфиге').format(host))
            return
        self.show_page("hosts")
        if self.search.get_text():
            self.search.set_text("")
            self.rebuild_tree()
        self._select_row(b.id)

    def connect_host(self, host):
        b = self.block_for_host(host)
        if b is not None:
            self.connect_block(b)
        else:
            self._run_in_terminal(host, backend.ssh_command(host))

    # ---------- tunnels

    def config_forwards(self, alias):
        out = []
        for b in self.config.blocks():
            if b.alias == alias:
                for k, v in b.options():
                    if k.lower() in ("localforward", "remoteforward", "dynamicforward"):
                        out.append(f"{k} {v}")
        return out

    def tunnel_state(self, tid):
        r = self.runners.get(tid)
        return (r.state, r.message) if r else ("stopped", "")

    def tunnel_active(self, tid):
        r = self.runners.get(tid)
        return bool(r and r.active)

    def active_tunnels_for(self, alias):
        return sum(1 for r in self.runners.values() if r.active and r.tunnel["alias"] == alias)

    def active_tunnel_count(self):
        return sum(1 for r in self.runners.values() if r.active)

    def start_tunnel(self, tid):
        t = self.state.tunnel(tid)
        if t is None or self.tunnel_active(tid):
            return
        problems = backend.tunnel_problems(t)
        if problems:
            self._error_dialog(T('Туннель не настроен'), ", ".join(problems))
            return
        if t["alias"] not in self.config.aliases():
            self.log(T('Внимание: хоста «{0}» нет в конфиге — ssh попробует подключиться к нему напрямую').format(t['alias']))
        runner = backend.TunnelRunner(
            t, lambda i, st, m: GLib.idle_add(self._on_tunnel_state, i, st, m),
            lambda i, line: GLib.idle_add(self._on_tunnel_log, i, line))
        self.runners[tid] = runner
        runner.start()

    def activate_tunnel(self, tid):
        """Double click on a tunnel: use it (open in browser / copy address),
        starting it first if needed — never stops it."""
        t = self.state.tunnel(tid)
        if t is None:
            return
        action = "browser" if backend.tunnel_is_web(t) else ("copy" if t["type"] != "R" else None)
        state, _ = self.tunnel_state(tid)
        if state == "up":
            self._run_up_action(tid, action)
            return
        if action:
            self._on_up_action[tid] = action
        if not self.tunnel_active(tid):
            self.start_tunnel(tid)
        self.set_status(T('Туннель «{0}» запускается…').format(backend.tunnel_title(t)) +
                        (T(' откроется в браузере, как только заработает') if action == "browser" else ""))

    def _run_up_action(self, tid, action):
        if action == "browser":
            self.open_tunnel_in_browser(tid)
        elif action == "copy":
            self.copy_tunnel_address(tid)
        else:
            t = self.state.tunnel(tid)
            self.set_status(T('Туннель «{0}» уже работает').format(backend.tunnel_title(t)))

    def stop_tunnel(self, tid):
        self._on_up_action.pop(tid, None)
        r = self.runners.get(tid)
        if r:
            r.stop()

    def toggle_tunnel(self, tid):
        if self.tunnel_active(tid):
            self.stop_tunnel(tid)
        else:
            self.start_tunnel(tid)

    def stop_all_tunnels(self):
        for r in self.runners.values():
            r.stop()

    def confirm_stop_tunnels(self):
        n = self.active_tunnel_count()
        if n and not self._confirm(T('Остановить активные туннели ({0}) и выйти?').format(n), ok_label=T('Выйти')):
            return False
        self.stop_all_tunnels()
        return True

    def _on_tunnel_state(self, tid, state, message):
        t = self.state.tunnel(tid)
        title = backend.tunnel_title(t) if t else tid
        text = {"up": T('работает'), "starting": T('подключение…'), "reconnecting": message,
                "error": T('ошибка: {0}').format(message), "stopped": T('остановлен')}.get(state, state)
        if state != "starting":
            self.log(T('Туннель «{0}»: {1}').format(title, text))
        if state == "up" and t:
            addr = backend.tunnel_local_address(t)
            self.set_status(T('Туннель «{0}» работает').format(title) + (f" — {addr}" if addr else ""))
            action = self._on_up_action.pop(tid, None)
            if action:
                self._run_up_action(tid, action)
        elif state == "error":
            self._on_up_action.pop(tid, None)
            self.set_status(T('Туннель «{0}»: {1}').format(title, message))
        self.refresh_tunnels()
        return False

    def _on_tunnel_log(self, tid, line):
        t = self.state.tunnel(tid)
        self.log(f"[{backend.tunnel_title(t) if t else tid}] {line}")
        return False

    def _update_tunnels_tab(self):
        if hasattr(self, "nav_badges"):
            self.set_badge("tunnels", self.active_tunnel_count(), "ok")

    def refresh_tunnels(self):
        self.all_tunnels.refresh()
        self.host_tunnels.refresh()
        self._update_tunnels_tab()
        for b in self.config.blocks():
            if b.alias:
                self._update_row(b)
        app = self.get_application()
        if app is not None and hasattr(app, "refresh_tray_menu"):
            app.refresh_tray_menu()

    def on_new_tunnel(self):
        b = self.selected_block()
        self.edit_tunnel(None, alias=b.alias if b else None)

    def edit_tunnel(self, tid, alias=None):
        existing = self.state.tunnel(tid) if tid else None
        tunnel = dict(existing) if existing else {"alias": alias or "", "type": "L", "dest_host": "127.0.0.1"}
        used = [t["listen_port"] for t in self.state.tunnels if t["id"] != (tid or "") and t["type"] != "R"]
        dialog = TunnelDialog(self, tunnel, self.config.aliases(), used, self.config_forwards)
        resp = dialog.run()
        result = dialog.result()
        dialog.destroy()
        if resp not in (RESP_SAVE, RESP_SAVE_START):
            return
        if backend.tunnel_problems(result):
            self._error_dialog(T('Туннель не сохранён'), T('Не хватает: ') + ", ".join(backend.tunnel_problems(result)))
            return
        was_active = bool(existing) and self.tunnel_active(existing["id"])
        changed = existing is not None and backend.normalize_tunnel(existing) != result
        saved = self.state.upsert_tunnel(result)
        self.log(T('Туннель «{0}» сохранён: {1}').format(backend.tunnel_title(saved), backend.tunnel_summary(saved)))
        if was_active and changed:
            self.stop_tunnel(saved["id"])
            GLib.timeout_add(800, lambda: self.start_tunnel(saved["id"]) or False)
        elif resp == RESP_SAVE_START:
            self.start_tunnel(saved["id"])
        self.refresh_tunnels()

    def delete_tunnel(self, tid):
        t = self.state.tunnel(tid)
        if t is None:
            return
        if not self._confirm(T('Удалить туннель «{0}»?').format(backend.tunnel_title(t)), backend.tunnel_summary(t),
                             ok_label=T('Удалить')):
            return
        self.stop_tunnel(tid)
        self.runners.pop(tid, None)
        self.state.remove_tunnel(tid)
        self.log(T('Туннель «{0}» удалён').format(backend.tunnel_title(t)))
        self.refresh_tunnels()

    def copy_tunnel_address(self, tid):
        t = self.state.tunnel(tid)
        addr = backend.tunnel_local_address(t) if t else None
        if addr:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(addr, -1)
            self.set_status(T('Скопировано: {0}').format(addr))

    def open_tunnel_in_browser(self, tid):
        t = self.state.tunnel(tid)
        addr = backend.tunnel_local_address(t) if t else None
        if not addr:
            return
        url = backend.tunnel_url(t)
        backend.spawn_detached(["xdg-open", url])
        self.log(T('Открыто в браузере: {0}').format(url))
        self.set_status(T('Открыто в браузере: {0}').format(url))

    # ---------- window events

    def _on_key_press(self, widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        key = Gdk.keyval_to_lower(event.keyval)
        pages = {Gdk.KEY_1: "hosts", Gdk.KEY_2: "tunnels", Gdk.KEY_3: "sessions",
                 Gdk.KEY_4: "templates", Gdk.KEY_5: "file", Gdk.KEY_6: "backups", Gdk.KEY_7: "log"}
        if ctrl and key in pages:
            self.show_page(pages[key])
            return True
        if ctrl and key == Gdk.KEY_f:
            self.show_page("hosts")
            self.search.grab_focus()
            return True
        if ctrl and key == Gdk.KEY_n:
            self.on_add_clicked()
            return True
        if ctrl and key == Gdk.KEY_s:
            page = self.current_page()
            if page == "file":
                self.file_page.save()
            elif page == "templates":
                if self.templates_page.save_btn.get_sensitive():
                    self.templates_page._on_save(None)
            elif self.dirty:
                self.on_save()
            return True
        if key == Gdk.KEY_Delete and self.view.has_focus() and self.current_page() == "hosts":
            self.on_delete()
            return True
        if key == Gdk.KEY_Escape and self.search.has_focus() and self.search.get_text():
            self.search.set_text("")
            return True
        return False

    def _on_delete_event(self, *args):
        if not self.resolve_unsaved():
            return True
        if HAVE_INDICATOR:
            self.hide()
            return True
        return not self.confirm_stop_tunnels()


class SSHManagerApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        Gtk.Window.set_default_icon_name(ICON_NAME)
        self.window = None
        self.indicator = None
        self.tray_menu = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        if not icon_installed():
            Gtk.Window.set_default_icon_from_file(ICON_FILE)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def switch_language(self, lang):
        """Re-create the window in another language; tunnels keep running."""
        i18n.set_language(lang)
        old = self.window
        carry = old.snapshot()
        self.window = SSHManagerWindow(self, carry=carry)
        old.dispose()
        self.window.log(T('Язык интерфейса: {0}').format(i18n.LANGUAGES.get(lang, lang)))
        self.window.present()
        self.refresh_tray_menu()

    def do_activate(self):
        if self.window is None:
            self.window = SSHManagerWindow(self)
            if HAVE_INDICATOR:
                self._setup_tray()
        self.window.present()

    def _setup_tray(self):
        indicator = AppIndicator3.Indicator.new(ICON_NAME, ICON_NAME if icon_installed() else ICON_FILE,
                                                AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        indicator.set_title(APP_TITLE)
        self.tray_menu = Gtk.Menu()
        indicator.set_menu(self.tray_menu)
        self.indicator = indicator
        self.refresh_tray_menu()

    def refresh_tray_menu(self):
        if self.indicator is None or self.window is None:
            return
        menu = self.tray_menu
        for child in menu.get_children():
            menu.remove(child)
        win = self.window
        blocks = [b for b in win.config.blocks() if b.alias]
        aliases = {b.alias for b in blocks}

        recent = [a for a in win.state.recent(6) if a in aliases]
        if recent:
            head = Gtk.MenuItem(label=T('Недавние'))
            head.set_sensitive(False)
            menu.append(head)
            for a in recent:
                item = Gtk.MenuItem(label=f"▶ {a}")
                item.connect("activate", lambda _i, al=a: self.window.connect_alias(al))
                menu.append(item)
            menu.append(Gtk.SeparatorMenuItem())

        mode = win.grouping()
        groups = {}
        for b in blocks:
            groups.setdefault(backend.group_of(b, mode) if mode != "none" else T('Все хосты'), []).append(b)
        for g in sorted(groups, key=lambda g: (g == backend.NO_GROUP, g.startswith("IP "), g.lower())):
            sub_item = Gtk.MenuItem(label=f"{T(g)}  ({len(groups[g])})")
            sub = Gtk.Menu()
            for b in groups[g]:
                item = Gtk.MenuItem(label=b.alias + (f"  —  {b.get('HostName')}" if b.get("HostName") else ""))
                item.connect("activate", lambda _i, al=b.alias: self.window.connect_alias(al))
                sub.append(item)
            sub_item.set_submenu(sub)
            menu.append(sub_item)
        if groups:
            menu.append(Gtk.SeparatorMenuItem())

        if win.state.tunnels:
            n = win.active_tunnel_count()
            tun_item = Gtk.MenuItem(label=T('Туннели  ({0} активно)').format(n) if n else T('Туннели'))
            tun_menu = Gtk.Menu()
            for t in win.state.tunnels:
                active = win.tunnel_active(t["id"])
                item = Gtk.MenuItem(label=(T('■ Остановить: ') if active else T('▶ Запустить: ')) +
                                    f"{backend.tunnel_title(t)}  —  {backend.tunnel_summary(t)}")
                item.connect("activate", lambda _i, tid=t["id"]: self.window.toggle_tunnel(tid))
                tun_menu.append(item)
                if backend.tunnel_is_web(t):
                    web = Gtk.MenuItem(label=T('    🌐 Открыть в браузере: {0}').format(backend.tunnel_title(t)))
                    web.connect("activate", lambda _i, tid=t["id"]: self.window.activate_tunnel(tid))
                    tun_menu.append(web)
            if n:
                tun_menu.append(Gtk.SeparatorMenuItem())
                stop_all = Gtk.MenuItem(label=T('Остановить все'))
                stop_all.connect("activate", lambda *_: self.window.stop_all_tunnels())
                tun_menu.append(stop_all)
            tun_item.set_submenu(tun_menu)
            menu.append(tun_item)
            menu.append(Gtk.SeparatorMenuItem())

        show_item = Gtk.MenuItem(label=T('Открыть окно'))
        show_item.connect("activate", lambda *_: self.window.present())
        menu.append(show_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label=T('Выход'))
        quit_item.connect("activate", lambda *_: self._quit())
        menu.append(quit_item)
        menu.show_all()

    def _quit(self):
        self.window.present()
        if self.window.resolve_unsaved() and self.window.confirm_stop_tunnels():
            self.quit()

    def do_shutdown(self):
        if self.window is not None:
            self.window.stop_all_tunnels()
        Gtk.Application.do_shutdown(self)


def main():
    GLib.set_prgname("hostkeep")          # WM_CLASS / StartupWMClass
    GLib.set_application_name(APP_TITLE)
    app = SSHManagerApplication()
    app.run()


if __name__ == "__main__":
    main()
