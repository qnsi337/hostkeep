#!/usr/bin/env python3
"""Records docs/demo.gif (or docs/demo-<lang>.gif) — a short scripted tour of
Hostkeep on the demo config (examples/demo-ssh) in a throw-away $HOME.

    xvfb-run -a -s "-screen 0 1400x900x24" python3 tools/demo_gif.py [--lang=ru]

Needs Pillow (python3-pil). A fake mouse pointer and click ripples are drawn
onto the frames, so the viewer can follow what is clicked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screenshots as demo  # noqa: E402  (sets up the fake HOME, demo data, fake sessions)

from PIL import Image, ImageDraw  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

A = demo.A
OUT = os.path.join(demo.ROOT, "docs", "demo.gif" if demo.LANG == "en" else f"demo-{demo.LANG}.gif")
W, H = 1180, 720          # window size
SCALE = 0.75              # GIF is scaled down to keep it small
FRAME_MS = 70

frames = []               # (PIL.Image, duration_ms)
cursor = [W // 2, H // 2]

POINTER = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]


def grab(win):
    demo.pump(4)
    gw = win.get_window()
    pb = demo.Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    img = Image.frombytes("RGBA" if pb.get_has_alpha() else "RGB", (pb.get_width(), pb.get_height()),
                          pb.get_pixels(), "raw", "RGBA" if pb.get_has_alpha() else "RGB", pb.get_rowstride())
    return img.convert("RGB")


def draw_cursor(img, pos, ripple=0):
    img = img.copy()
    d = ImageDraw.Draw(img)
    x, y = pos
    if ripple:
        r = 10 + ripple * 6
        d.ellipse([x - r, y - r, x + r, y + r], outline=(91, 141, 239), width=3)
    pts = [(x + px * 1.3, y + py * 1.3) for px, py in POINTER]
    d.polygon(pts, fill=(255, 255, 255), outline=(20, 20, 30))
    return img


def add(win, ms=FRAME_MS, ripple=0, img=None):
    frames.append((draw_cursor(img or grab(win), cursor, ripple), ms))


def hold(win, ms):
    add(win, ms)


def move_to(win, x, y, steps=10):
    base = grab(win)
    sx, sy = cursor
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)                    # ease in-out
        cursor[0], cursor[1] = int(sx + (x - sx) * t), int(sy + (y - sy) * t)
        frames.append((draw_cursor(base, cursor), 30))


def click(win, action=None, double=False):
    base = grab(win)
    for r in (1, 2) if not double else (1, 2, 1, 2):
        frames.append((draw_cursor(base, cursor, ripple=r), 60))
    if action:
        action()
    add(win, 120)


def center_of(win, widget):
    alloc = widget.get_allocation()
    x, y = widget.translate_coordinates(win, alloc.width // 2, alloc.height // 2)
    return x, y


def row_center(win, view, path, col=0):
    area = view.get_cell_area(path, view.get_column(col))
    bx, by = view.convert_bin_window_to_widget_coords(area.x + 80, area.y + area.height // 2)
    return view.translate_coordinates(win, bx, by)


def type_into(win, entry, text, ms=90):
    for i in range(1, len(text) + 1):
        entry.set_text(text[:i])
        entry.set_position(-1)
        add(win, ms)


def scenario():
    app = demo.app
    win = app.window
    win.resize(W, H)
    yield
    for t, st in zip(win.state.tunnels, ("up", "up", "stopped", "stopped")):
        win.runners[t["id"]] = demo.FakeRunner(t, st, "")
    win.refresh_tunnels()
    win.refresh_sessions()
    win.rebuild_tree()
    yield
    hold(win, 1400)

    # 1. search
    move_to(win, *center_of(win, win.search))
    click(win, lambda: win.search.grab_focus())
    type_into(win, win.search, "db", 160)
    hold(win, 700)

    # 2. open a host
    db = next(b for b in win.config.blocks() if b.alias == "db-01.prod")
    path = next(win.store.get_path(it) for it in win._iter_rows() if win.store[it][5] == db.id)
    move_to(win, *row_center(win, win.view, path))
    click(win, lambda: win._select_row(db.id))
    hold(win, 1200)

    # 3. edit + save
    desc = win.f["desc"]
    move_to(win, *center_of(win, desc))
    click(win, lambda: desc.grab_focus())
    type_into(win, desc, desc.get_text() + " · read-write" if demo.LANG == "en" else desc.get_text() + " · основной",
              60)
    hold(win, 600)
    move_to(win, *center_of(win, win.save_btn))
    click(win, lambda: win.on_save())
    hold(win, 1300)

    # 4. tunnels: double click a running one -> address copied
    win.search.set_text("")
    move_to(win, *center_of(win, win.nav_buttons["tunnels"]))
    click(win, lambda: win.show_page("tunnels"))
    hold(win, 900)
    lst = win.all_tunnels
    move_to(win, *row_center(win, lst.view, Gtk.TreePath(0), col=1))
    click(win, lambda: win.activate_tunnel(lst.store[0][4]), double=True)
    hold(win, 1500)

    # 5. backups with a diff
    move_to(win, *center_of(win, win.nav_buttons["backups"]))
    click(win, lambda: win.show_page("backups"))
    win.backups_page.view.get_selection().unselect_all()
    win.backups_page.view.get_selection().select_path(Gtk.TreePath(len(win.backups_page.store) - 1))
    hold(win, 2200)

    # 6. dark theme
    move_to(win, *center_of(win, win.nav_buttons["settings"]))
    click(win, lambda: win.show_page("settings"))
    hold(win, 500)
    combo = win.settings_page.theme_combo
    move_to(win, *center_of(win, combo))
    click(win, lambda: combo.set_active_id("dark"))
    hold(win, 900)
    move_to(win, *center_of(win, win.nav_buttons["hosts"]))
    click(win, lambda: win.show_page("hosts"))
    hold(win, 2200)
    app.quit()


def save():
    out = []
    for img, ms in frames:
        if SCALE != 1:
            img = img.resize((int(img.width * SCALE), int(img.height * SCALE)), Image.LANCZOS)
        out.append((img.convert("P", palette=Image.ADAPTIVE, colors=128), ms))
    out[0][0].save(OUT, save_all=True, append_images=[f for f, _ in out[1:]],
                   duration=[ms for _, ms in out], loop=0, optimize=True, disposal=1)
    print(f"saved {OUT}: {len(out)} frames, {sum(ms for _, ms in out) / 1000:.1f}s, "
          f"{os.path.getsize(OUT) / 1024:.0f} KiB")


it = scenario()


def tick():
    try:
        next(it)
        return True
    except StopIteration:
        return False
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        demo.app.quit()
        return False


GLib.timeout_add(400, tick)
demo.app.run([])
save()
