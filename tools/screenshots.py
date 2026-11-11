#!/usr/bin/env python3
"""Regenerates docs/screenshots/*.png from examples/demo-ssh.

Runs Hostkeep against a throw-away fake $HOME, so no real hosts, paths, ssh
sessions or tunnels can end up in the pictures. Needs Xvfb:

    xvfb-run -a -s "-screen 0 1400x900x24" python3 tools/screenshots.py [--lang=ru]
    GTK_THEME=Adwaita:dark xvfb-run -a -s "-screen 0 1400x900x24" python3 tools/screenshots.py --dark [--lang=ru]
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DARK = "--dark" in sys.argv
LANG = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--lang=")), "en")
os.environ["HOSTKEEP_LANG"] = LANG
OUT = os.path.join(ROOT, "docs", "screenshots", *([] if LANG == "en" else [LANG]))

# ---- fake home with the demo config (must happen before importing hostkeep)
HOME = tempfile.mkdtemp(prefix="hostkeep-shots-")
os.environ["HOME"] = HOME
os.environ.pop("HOSTKEEP_CONFIG", None)
os.environ.pop("HOSTKEEP_DATA", None)
os.environ.pop("XDG_CONFIG_HOME", None)
SSH = os.path.join(HOME, ".ssh")
shutil.copytree(os.path.join(ROOT, "examples", "demo-ssh"), SSH)
os.chmod(SSH, 0o700)
DATA = os.path.join(HOME, ".config", "hostkeep")
os.makedirs(os.path.join(DATA, "backups"))


def ago(minutes):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - minutes * 60))


state = {
    "settings": {"grouping": "meta", "terminal": "auto", "keep_open": True},
    "stats": {"db-01.prod": {"count": 14, "last": ago(7)}, "bastion.prod": {"count": 40, "last": ago(55)},
              "nas": {"count": 5, "last": ago(60 * 26)}, "web-01.stage": {"count": 3, "last": ago(60 * 24 * 4)}},
    "tunnels": [
        {"id": "t-pg", "alias": "db-01.prod", "type": "L", "name": "PostgreSQL prod", "listen_port": 15432,
         "dest_host": "127.0.0.1", "dest_port": 5432, "reconnect": True},
        {"id": "t-graf", "alias": "grafana.stage", "type": "L", "name": "Grafana stage", "listen_port": 13000,
         "dest_host": "127.0.0.1", "dest_port": 3000, "reconnect": True, "open_action": "http"},
        {"id": "t-k8s", "alias": "bastion.prod", "type": "L", "name": "Kubernetes API", "listen_port": 16443,
         "dest_host": "10.10.3.5", "dest_port": 6443},
        {"id": "t-socks", "alias": "bastion.stage", "type": "D", "name": "SOCKS stage", "listen_port": 11080},
    ],
}
with open(os.path.join(DATA, "state.json"), "w") as fh:
    json.dump(state, fh)

# two older versions of the config as backups
cfg_text = open(os.path.join(SSH, "config")).read()
older = cfg_text.replace("  Port 2222\n", "").replace("# @desc: PostgreSQL 16 primary", "# @desc: PostgreSQL 15 primary")
oldest = older.split("Host k8s-master.prod")[0] + "Host *\n  AddKeysToAgent yes\n"
for minutes, text in ((180, oldest), (35, older)):
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - minutes * 60))
    with open(os.path.join(DATA, "backups", f"config-{stamp}"), "w") as fh:
        fh.write(text)

sys.path.insert(0, ROOT)
from hostkeep import backend, app as A  # noqa: E402
from gi.repository import GLib, Gtk, Gdk, Gio  # noqa: E402

now = time.time()
DEMO_SESSIONS = [
    {"pid": 48211, "host": "db-01.prod", "user": "", "kind": "сессия", "from_app": True, "command": "",
     "started": now - 7 * 60, "peer": "198.51.100.10:2222", "via": "bastion.prod", "argv": ["ssh", "db-01.prod"]},
    {"pid": 47720, "host": "nas", "user": "", "kind": "сессия", "from_app": False, "command": "",
     "started": now - 26 * 3600, "peer": "192.0.2.50:22", "via": "", "argv": ["ssh", "nas"]},
    {"pid": 48302, "host": "db-01.prod", "user": "", "kind": "туннель", "from_app": True, "app_tunnel": True,
     "command": "", "started": now - 40 * 60, "peer": "198.51.100.10:2222", "via": "bastion.prod",
     "argv": ["ssh", "-N", "-L", "15432:127.0.0.1:5432", "db-01.prod"]},
    {"pid": 48390, "host": "grafana.stage", "user": "", "kind": "туннель", "from_app": True, "app_tunnel": True,
     "command": "", "started": now - 12 * 60, "peer": "203.0.113.20:22", "via": "bastion.stage",
     "argv": ["ssh", "-N", "-L", "13000:127.0.0.1:3000", "grafana.stage"]},
    {"pid": 48455, "host": "acme-app", "user": "support", "kind": "команда", "from_app": False,
     "command": "journalctl -fu app", "started": now - 3 * 60, "peer": "203.0.113.80:2200", "via": "",
     "argv": ["ssh", "support@acme-app", "journalctl", "-fu", "app"]},
]
backend.list_ssh_sessions = lambda tunnel_pids=(): [dict(s) for s in DEMO_SESSIONS]


class FakeRunner:
    def __init__(self, t, state, message=""):
        self.tunnel, self.id, self.state, self.message, self._proc = t, t["id"], state, message, None

    @property
    def active(self):
        return self.state in ("starting", "up", "reconnecting")

    def stop(self):
        pass


app = A.SSHManagerApplication()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
suffix = "-dark" if DARK else ""


def pump(n=25):
    for _ in range(n):
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.02)


def shot(widget, name):
    pump()
    gw = widget.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    pb.savev(os.path.join(OUT, f"{name}{suffix}.png"), "png", [], [])
    print("saved", f"{name}{suffix}.png")


def steps():
    win = app.window
    win.resize(1280, 800)
    yield
    for t, st in zip(win.state.tunnels, ("up", "up", "stopped", "stopped")):
        win.runners[t["id"]] = FakeRunner(t, st, "работает" if st == "up" else "")
    win.test_results["bastion.prod"] = (True, "OK")
    win.refresh_tunnels()
    win.refresh_sessions()
    yield
    db = next(b for b in win.config.blocks() if b.alias == "db-01.prod")
    win.rebuild_tree()
    win._select_row(db.id)
    yield
    shot(win, "hosts")
    if DARK:
        app.quit()
        return
    web = next(b for b in win.config.blocks() if b.alias == "web-01.stage")
    win._select_row(web.id)
    yield
    shot(win, "hosts-include")
    win.show_page("tunnels")
    yield
    shot(win, "tunnels")
    win.show_page("sessions")
    yield
    shot(win, "sessions")
    win.show_page("file")
    yield
    shot(win, "config")
    win.show_page("backups")
    yield
    win.backups_page.view.get_selection().unselect_all()
    win.backups_page.view.get_selection().select_path(Gtk.TreePath(1))
    yield
    shot(win, "backups")
    win.show_page("templates")
    yield
    shot(win, "templates")
    win.show_page("hosts")
    yield
    d = A.TunnelDialog(win, dict(win.state.tunnel("t-pg")), win.config.aliases(), [13000, 16443, 11080],
                       win.config_forwards)
    shot(d, "tunnel-dialog")
    d.destroy()
    app.quit()


def main():
    it = steps()

    def tick():
        try:
            next(it)
            return True
        except StopIteration:
            return False
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            app.quit()
            return False

    os.makedirs(OUT, exist_ok=True)
    GLib.timeout_add(400, tick)
    app.run([])
    shutil.rmtree(HOME, ignore_errors=True)


if __name__ == "__main__":
    main()
