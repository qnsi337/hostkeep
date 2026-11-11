"""Backend tests: lossless ~/.ssh/config editing, tunnels, sessions parsing.

Run:  python3 -m unittest discover -s tests -v
No GTK needed. Tests that call the real `ssh` binary are skipped if it is missing.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOSTKEEP_LANG"] = "ru"          # expectations below use the source language

from hostkeep import backend as b  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sample_config")
HAVE_SSH = shutil.which("ssh") is not None


def load_text():
    with open(FIXTURE, encoding="utf-8") as fh:
        return fh.read()


def block(cfg, alias):
    return next(x for x in cfg.blocks() if x.alias == alias)


class RoundTrip(unittest.TestCase):
    def test_parse_serialize_is_byte_identical(self):
        text = load_text()
        self.assertFalse(text.endswith("\n"), "fixture must keep its missing final newline")
        self.assertEqual(b.SSHConfig.parse(text).serialize(), text)

    def test_blocks_and_aliases(self):
        cfg = b.SSHConfig.parse(load_text())
        titles = [x.title for x in cfg.blocks()]
        self.assertIn("db-01.prod", titles)            # indented "  Host" header
        self.assertNotIn("old.prod", titles)           # commented-out host is just a comment
        self.assertIn("Match host *.internal exec \"true\"", titles)
        self.assertIsNone(block_by_title(cfg, "*").alias)
        self.assertEqual(block(cfg, "legacy").get("HostName"), "192.0.2.7")   # Key=value form

    def test_noop_edit_changes_nothing(self):
        text = load_text()
        cfg = b.SSHConfig.parse(text)
        for x in cfg.blocks():
            x.set_options(x.options())
            x.set_meta("group", "")
            if x.kind == "host":
                x.set_patterns(x.patterns)
        self.assertEqual(cfg.serialize(), text)


def block_by_title(cfg, title):
    return next(x for x in cfg.blocks() if x.title == title)


class Editing(unittest.TestCase):
    def setUp(self):
        self.text = load_text()
        self.cfg = b.SSHConfig.parse(self.text)

    def changed_lines(self, new_text):
        old, new = self.text.splitlines(), new_text.splitlines()
        return [line for line in new if line not in old], [line for line in old if line not in new]

    def test_edit_touches_only_changed_lines(self):
        x = block(self.cfg, "web-01.prod")
        opts = [(k, "2222" if k == "Port" else v) for k, v in x.options()]
        x.set_options(opts + [("ConnectTimeout", "10")])
        added, removed = self.changed_lines(self.cfg.serialize())
        self.assertEqual(removed, ["  Port 22"])
        self.assertEqual(added, ["  Port 2222", "  ConnectTimeout 10"])

    def test_indentation_of_block_is_kept(self):
        x = block(self.cfg, "db-01.prod")
        x.set_options(x.options() + [("Compression", "yes")])
        self.assertIn("    Compression yes\n", x.text())

    def test_repeated_keys_are_matched_in_order(self):
        x = block(self.cfg, "web-01.prod")
        x.set_options(x.options() + [("IdentityFile", "~/.ssh/second")])
        self.assertEqual(x.get_all("IdentityFile"), ["~/.ssh/id_ed25519", "~/.ssh/second"])

    def test_metadata_written_only_when_set(self):
        x = block(self.cfg, "web-01.prod")
        x.set_meta("group", "Production")
        x.set_meta("desc", "Main API")
        self.assertEqual(x.meta("group"), "Production")
        self.assertIn("  # @group: Production\n", x.text())
        x.set_meta("group", "")
        self.assertEqual(x.meta("group"), "")

    def test_insert_after_and_at_end(self):
        nb = b.new_host_block(["new.host"], [("HostName", "192.0.2.50"), ("User", "root")])
        self.cfg.insert_block(nb, after_id=block(self.cfg, "bastion.prod").id)
        self.cfg.insert_block(b.new_host_block(["tail.host"], [("HostName", "192.0.2.51")]))
        out = self.cfg.serialize()
        self.assertLess(out.index("Host new.host"), out.index("Host 10.0.1.*"))
        self.assertTrue(out.rstrip().endswith("HostName 192.0.2.51"))
        # the line that had no newline got one, nothing else changed
        self.assertIn("HostKeyAlgorithms +ssh-rsa\n", out)
        reparsed = b.SSHConfig.parse(out)
        self.assertEqual(reparsed.serialize(), out)

    def test_remove_with_and_without_leading_comment(self):
        web = block(self.cfg, "web-01.prod")
        self.assertEqual([l.text() for l in self.cfg.leading_comments(web.id)], ["# главный веб-сервер"])
        cfg2 = self.cfg.copy()
        cfg2.remove_block(web.id, with_leading_comments=True)
        out = cfg2.serialize()
        self.assertNotIn("web-01.prod", out)
        self.assertNotIn("главный", out)
        self.assertIn("### PRODUCTION", out)          # section comment survives
        self.assertIn("# Host old.prod", out)         # commented-out host survives
        cfg3 = self.cfg.copy()
        cfg3.remove_block(block(cfg3, "web-01.prod").id)
        self.assertIn("# главный веб-сервер", cfg3.serialize())

    def test_parse_block_text(self):
        x = b.parse_block_text("Host a b\n  HostName 192.0.2.1\n")
        self.assertEqual(x.patterns, ["a", "b"])
        with self.assertRaises(b.ConfigError):
            b.parse_block_text("HostName nope\n")
        with self.assertRaises(b.ConfigError):
            b.parse_block_text("Host a\nHost b\n")


@unittest.skipUnless(HAVE_SSH, "ssh binary not installed")
class Validation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_valid_config_passes(self):
        b.validate_text(load_text(), self.dir)

    def test_unknown_keyword_and_bad_value_are_rejected(self):
        for bad in ("Host x\n  NoSuchOption 1\n", "Host x\n  Port abc\n"):
            with self.assertRaises(b.ConfigError):
                b.validate_text(bad, self.dir)

    def test_write_config_backs_up_and_keeps_mode(self):
        path = os.path.join(self.dir, "config")
        with open(path, "w") as fh:
            fh.write("Host a\n  HostName 192.0.2.1\n")
        os.chmod(path, 0o600)
        old_backup_dir = b.BACKUP_DIR
        b.BACKUP_DIR = os.path.join(self.dir, "backups")
        try:
            mtime = b.write_config("Host a\n  HostName 192.0.2.2\n", path, expected_mtime=os.stat(path).st_mtime_ns)
            self.assertEqual(os.stat(path).st_mtime_ns, mtime)
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            backups = b.list_backups()
            self.assertEqual(len(backups), 1)
            self.assertIn("192.0.2.1", b.read_text(backups[0]["path"]))
            with self.assertRaises(b.ExternalChangeError):
                b.write_config("Host a\n", path, expected_mtime=1)
            with self.assertRaises(b.ConfigError):     # ssh rejects -> file untouched
                b.write_config("Host a\n  Port abc\n", path, expected_mtime=mtime)
            self.assertIn("192.0.2.2", b.read_text(path))
        finally:
            b.BACKUP_DIR = old_backup_dir


class Backups(unittest.TestCase):
    def test_ordered_by_creation_time_from_name(self):
        d = tempfile.mkdtemp()
        old = b.BACKUP_DIR
        b.BACKUP_DIR = d
        try:
            for name in ("config-20260101-120000", "config-20260101-120000-2", "config-20251231-235959"):
                with open(os.path.join(d, name), "w") as fh:
                    fh.write(name)
            os.utime(os.path.join(d, "config-20251231-235959"), (2e9, 2e9))   # newest content mtime
            self.assertEqual([x["name"] for x in b.list_backups()],
                             ["config-20260101-120000-2", "config-20260101-120000", "config-20251231-235959"])
        finally:
            b.BACKUP_DIR = old
            shutil.rmtree(d, ignore_errors=True)


class Tunnels(unittest.TestCase):
    def test_specs_and_summaries(self):
        local = b.normalize_tunnel({"alias": "db", "type": "L", "listen_port": 15432,
                                    "dest_host": "10.0.1.20", "dest_port": 5432})
        self.assertEqual(b.tunnel_spec(local), "15432:10.0.1.20:5432")
        self.assertEqual(b.tunnel_summary(local), "10.0.1.20:5432 ⇒ localhost:15432  (через db)")
        socks = b.normalize_tunnel({"alias": "x", "type": "D", "bind": "127.0.0.1", "listen_port": 1080})
        self.assertEqual(b.tunnel_spec(socks), "127.0.0.1:1080")
        remote = b.normalize_tunnel({"alias": "x", "type": "R", "listen_port": 8080, "dest_port": 3000})
        self.assertEqual(b.tunnel_spec(remote), "8080:127.0.0.1:3000")
        v6 = b.normalize_tunnel({"alias": "x", "listen_port": 1, "dest_host": "::1", "dest_port": 2})
        self.assertEqual(b.tunnel_spec(v6), "1:[::1]:2")
        argv = b.tunnel_ssh_argv(local, path=b.DEFAULT_CONFIG)
        self.assertEqual(argv[-3:], ["-L", "15432:10.0.1.20:5432", "db"])
        self.assertIn("ExitOnForwardFailure=yes", argv)

    def test_problems_and_web_detection(self):
        self.assertTrue(b.tunnel_problems(b.normalize_tunnel({})))
        pg = b.normalize_tunnel({"alias": "x", "listen_port": 15432, "dest_port": 5432})
        ui = b.normalize_tunnel({"alias": "x", "name": "console-ui", "listen_port": 25000, "dest_port": 7001})
        forced = dict(pg, open_action="https")
        self.assertFalse(b.tunnel_is_web(pg))
        self.assertTrue(b.tunnel_is_web(ui))
        self.assertEqual(b.tunnel_url(forced), "https://127.0.0.1:15432/")

    def test_parse_forward_option(self):
        t = b.parse_forward_option("LocalForward", "15432 127.0.0.1:5432")
        self.assertEqual((t["type"], t["listen_port"], t["dest_port"]), ("L", 15432, 5432))


class Sessions(unittest.TestCase):
    def test_parse_ssh_argv(self):
        p = b.parse_ssh_argv(["ssh", "-p", "2222", "-luser", "-At", "root@host", "uptime", "-a"])
        self.assertEqual((p["host"], p["user"], p["command"]), ("host", "root", ["uptime", "-a"]))
        self.assertEqual(b.parse_ssh_argv(["ssh", "-N", "-L", "1:a:2", "db"])["flags"], {"N"})
        self.assertEqual(b.parse_ssh_argv(["ssh", "-W", "[10.0.0.1]:22", "bastion"])["host"], "bastion")

    def test_fmt_duration(self):
        self.assertEqual(b.fmt_duration(65), "1м 05с")
        self.assertEqual(b.fmt_duration(3 * 3600 + 120), "3ч 02м")
        self.assertEqual(b.fmt_duration(2 * 86400 + 3600), "2д 1ч")

    def test_list_sessions_runs(self):
        self.assertIsInstance(b.list_ssh_sessions(), list)


if __name__ == "__main__":
    unittest.main()


class Includes(unittest.TestCase):
    """Include resolution follows OpenSSH: globs sorted, nested, cycles ignored."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "conf.d"))
        self.w(f"config", f"Include {self.d}/conf.d/*.conf\n\nHost main-host\n  HostName 192.0.2.1\n\nHost *\n  User fallback\n")
        self.w("conf.d/10-work.conf", f"Host work-1\n  HostName 198.51.100.1\nInclude {self.d}/nested.conf\n")
        self.w("conf.d/20-home.conf", "Host home-nas\n  HostName 192.0.2.50\n")
        self.w("conf.d/ignored.txt", "Host must-not-load\n")
        self.w("nested.conf", "Host nested-1\n  HostName 203.0.113.7\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def w(self, rel, text):
        with open(os.path.join(self.d, rel), "w") as fh:
            fh.write(text)

    def test_blocks_in_ssh_reading_order(self):
        cs = b.ConfigSet.load(os.path.join(self.d, "config"))
        self.assertEqual([x.title for x in cs.blocks()], ["work-1", "nested-1", "home-nas", "main-host", "*"])
        self.assertEqual(len(cs.files), 4)          # config, 10-work, 20-home, nested
        self.assertNotIn("must-not-load", cs.aliases())
        self.assertEqual(os.path.basename(cs.find(next(x.id for x in cs.blocks() if x.alias == "home-nas")).source),
                         "20-home.conf")

    def test_edits_go_to_the_owning_file_only(self):
        cs = b.ConfigSet.load(os.path.join(self.d, "config"))
        before = cs.texts()
        nas = next(x for x in cs.blocks() if x.alias == "home-nas")
        work = cs.copy()
        nb = work.find(nas.id)
        nb.set_options(nb.options() + [("User", "admin")])
        changed = [p for p, t in work.texts().items() if t != before[p]]
        self.assertEqual([os.path.basename(p) for p in changed], ["20-home.conf"])
        # new block next to a block of an included file lands in that file
        work.insert_block(b.new_host_block(["home-pi"], [("HostName", "192.0.2.51")]), after_id=nas.id)
        self.assertIn("home-pi", work.files[os.path.realpath(os.path.join(self.d, "conf.d/20-home.conf"))].serialize())
        # explicit target file
        work.insert_block(b.new_host_block(["x"], [("HostName", "192.0.2.9")]), target=os.path.join(self.d, "config"))
        self.assertIn("Host x", work.main.serialize())

    def test_cycle_does_not_hang(self):
        self.w("nested.conf", f"Host nested-1\n  HostName 203.0.113.7\nInclude {self.d}/config\n")
        cs = b.ConfigSet.load(os.path.join(self.d, "config"))
        self.assertEqual(len(cs.files), 4)
        self.assertEqual(len(cs.blocks()), 5)       # every block once; ssh itself rejects such a cycle

    def test_stale_when_new_file_matches_glob(self):
        cs = b.ConfigSet.load(os.path.join(self.d, "config"))
        self.assertFalse(cs.stale())
        self.w("conf.d/30-new.conf", "Host fresh\n  HostName 192.0.2.77\n")
        self.assertTrue(cs.stale())
        self.assertIn("fresh", b.ConfigSet.load(os.path.join(self.d, "config")).aliases())

    @unittest.skipUnless(HAVE_SSH, "ssh binary not installed")
    def test_ssh_agrees_with_resolution(self):
        import subprocess
        out = subprocess.run(["ssh", "-G", "-F", os.path.join(self.d, "config"), "home-nas"],
                             capture_output=True, text=True).stdout
        self.assertIn("hostname 192.0.2.50", out)
        self.assertIn("user fallback", out)

    def test_backups_are_per_file(self):
        old = b.BACKUP_DIR
        b.BACKUP_DIR = os.path.join(self.d, "bk")
        try:
            b.make_backup(os.path.join(self.d, "config"))
            b.make_backup(os.path.join(self.d, "conf.d/20-home.conf"))
            items = b.list_backups()
            self.assertEqual(len(items), 2)
            self.assertEqual({os.path.realpath(x["target"]) for x in items},
                             {os.path.realpath(os.path.join(self.d, "config")),
                              os.path.realpath(os.path.join(self.d, "conf.d/20-home.conf"))})
            self.assertEqual(len(b.list_backups(os.path.join(self.d, "config"))), 1)
        finally:
            b.BACKUP_DIR = old


class IncludeDiagnostics(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "conf.d"))
        with open(os.path.join(self.d, "conf.d", "bridge.сonf"), "w") as fh:     # Cyrillic "с"
            fh.write("Host bridge\n  HostName 192.0.2.5\n")
        self.cfg = os.path.join(self.d, "config")
        with open(self.cfg, "w") as fh:
            fh.write(f"Host *\n  User x\n\nHost mds\n  HostName 192.0.2.9\n\nInclude {self.d}/conf.d/*.conf\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_detects_include_inside_block_and_lookalike_name(self):
        cs = b.ConfigSet.load(self.cfg)
        kinds = {p["kind"]: p for p in cs.include_problems()}
        self.assertEqual(kinds["inside"]["block"], "mds")
        self.assertEqual([os.path.basename(x) for x in kinds["nomatch"]["lookalikes"]], ["bridge.сonf"])
        self.assertEqual(b.ascii_lookalike("bridge.сonf"), "bridge.conf")

    def test_move_include_to_top_changes_only_that_line(self):
        cs = b.ConfigSet.load(self.cfg)
        p = next(x for x in cs.include_problems() if x["kind"] == "inside")
        cs.move_include_to_top(p["file"], p["lineno"])
        text = cs.main.serialize()
        self.assertTrue(text.startswith(f"Include {self.d}/conf.d/*.conf\n\nHost *\n"))
        self.assertEqual(text.count("Include"), 1)
        self.assertNotIn("inside", [x["kind"] for x in cs.include_problems()])
        os.rename(os.path.join(self.d, "conf.d", "bridge.сonf"), os.path.join(self.d, "conf.d", "bridge.conf"))
        self.assertIn("bridge", b.ConfigSet.load(self.cfg).aliases())

    def test_include_inside_host_star_is_not_reported(self):
        with open(self.cfg, "w") as fh:
            fh.write(f"Host *\n  User x\n  Include {self.d}/conf.d/*.conf\n")
        self.assertNotIn("inside", [x["kind"] for x in b.ConfigSet.load(self.cfg).include_problems()])


class DeleteBackups(unittest.TestCase):
    def test_delete_only_inside_backup_dir(self):
        d = tempfile.mkdtemp()
        old = b.BACKUP_DIR
        b.BACKUP_DIR = os.path.join(d, "bk")
        try:
            src = os.path.join(d, "config")
            with open(src, "w") as fh:
                fh.write("Host a\n")
            bk = b.make_backup(src)
            with self.assertRaises(b.ConfigError):
                b.delete_backup(src)                      # the real config is never "a backup"
            b.delete_backup(bk)
            self.assertEqual(b.list_backups(), [])
            self.assertTrue(os.path.exists(src))
        finally:
            b.BACKUP_DIR = old
            shutil.rmtree(d, ignore_errors=True)
