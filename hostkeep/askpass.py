#!/usr/bin/env python3
"""SSH_ASKPASS helper: shows a GTK dialog when a background ssh (tunnel)
needs a passphrase / password / host-key confirmation. Prints the answer to
stdout; exit code 1 means "cancelled"."""
import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import T  # noqa: E402


def main():
    prompt = " ".join(sys.argv[1:]).strip() or T('ssh запрашивает ввод')
    tunnel = os.environ.get("HOSTKEEP_TUNNEL", "")
    title = f"Hostkeep — {tunnel}" if tunnel else "Hostkeep"
    if os.environ.get("SSH_ASKPASS_PROMPT") == "confirm":
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, text=title)
        d.format_secondary_text(prompt)
        d.set_keep_above(True)
        ok = d.run() == Gtk.ResponseType.YES
        sys.exit(0 if ok else 1)

    d = Gtk.Dialog(title=title)
    d.set_keep_above(True)
    d.set_default_size(420, -1)
    d.add_buttons(T('Отмена'), Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
    box = d.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    if tunnel:
        head = Gtk.Label(xalign=0)
        head.set_markup(T('<b>Туннель:</b> {0}').format(GLibEscape(tunnel)))
        box.add(head)
    label = Gtk.Label(label=prompt, xalign=0)
    label.set_line_wrap(True)
    label.set_max_width_chars(60)
    box.add(label)
    entry = Gtk.Entry()
    entry.set_activates_default(True)
    low = prompt.lower()
    entry.set_visibility("yes/no" in low or "fingerprint" in low)
    box.add(entry)
    d.set_default_response(Gtk.ResponseType.OK)
    d.show_all()
    entry.grab_focus()
    if d.run() != Gtk.ResponseType.OK:
        sys.exit(1)
    sys.stdout.write(entry.get_text() + "\n")
    sys.exit(0)


def GLibEscape(text):
    from gi.repository import GLib
    return GLib.markup_escape_text(text)


if __name__ == "__main__":
    main()
