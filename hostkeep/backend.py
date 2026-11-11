"""Lossless ~/.ssh/config model + helpers for templates, settings and
launching ssh in a native terminal. No GTK imports here.

Design rule: the file is kept as a list of raw lines. Anything the user did
not touch is written back byte-for-byte (comments, indentation, odd spacing,
missing final newline, Cyrillic text...). Only lines that were actually
edited are regenerated.
"""
import copy
import datetime
import glob
import itertools
import json
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import uuid

from .i18n import T

DEFAULT_CONFIG = os.path.expanduser("~/.ssh/config")
# Overridable for testing so development never touches the real file.
CONFIG_PATH = os.path.expanduser(os.environ.get("HOSTKEEP_CONFIG", DEFAULT_CONFIG))
_XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME", "~/.config")
APP_DIR = os.path.expanduser(os.environ.get("HOSTKEEP_DATA", os.path.join(_XDG_CONFIG, "hostkeep")))
# Data of the pre-release name of the project; copied over once (never moved).
_LEGACY_APP_DIR = os.path.expanduser(os.path.join(_XDG_CONFIG, "ssh-manager"))
BACKUP_DIR = os.path.join(APP_DIR, "backups")
STATE_FILE = os.path.join(APP_DIR, "state.json")
TEMPLATES_FILE = os.path.join(APP_DIR, "templates.json")
MAX_BACKUPS = 30

WILDCARD_CHARS = set("*?!")


class ConfigError(RuntimeError):
    pass


class ExternalChangeError(ConfigError):
    pass


# ---------------------------------------------------------------- lines

_KW_RE = re.compile(r"^(\s*)([A-Za-z][A-Za-z0-9]*)(?:\s*=\s*|\s+)(.*?)\s*$")
_KW_ONLY_RE = re.compile(r"^(\s*)([A-Za-z][A-Za-z0-9]*)\s*$")
# Metadata understood by this app, stored as harmless comments inside a block:
#   # @group: Production
#   # @desc: Main API server
_META_RE = re.compile(r"^\s*#\s*@([A-Za-z_]+)\s*:\s?(.*?)\s*$")


def _eol(raw):
    if raw.endswith("\r\n"):
        return "\r\n"
    if raw.endswith("\n"):
        return "\n"
    return ""


class Line:
    """One physical line. kind: blank | comment | meta | option."""
    __slots__ = ("raw", "kind", "key", "value", "indent")

    def __init__(self, raw):
        self.raw = raw
        self.key = None
        self.value = None
        self.indent = ""
        body = raw.rstrip("\r\n")
        stripped = body.strip()
        if not stripped:
            self.kind = "blank"
            return
        if stripped.startswith("#"):
            m = _META_RE.match(body)
            if m:
                self.kind = "meta"
                self.key = m.group(1).lower()
                self.value = m.group(2)
            else:
                self.kind = "comment"
            self.indent = body[:len(body) - len(body.lstrip())]
            return
        m = _KW_RE.match(body) or _KW_ONLY_RE.match(body)
        if m:
            self.kind = "option"
            self.indent = m.group(1)
            self.key = m.group(2)
            self.value = m.group(3) if m.lastindex >= 3 else ""
        else:  # garbage ssh would reject; keep it verbatim
            self.kind = "comment"

    @classmethod
    def option(cls, indent, key, value, eol="\n"):
        return cls(f"{indent}{key} {value}{eol}")

    @classmethod
    def meta(cls, indent, key, value, eol="\n"):
        return cls(f"{indent}# @{key}: {value}{eol}")

    def text(self):
        return self.raw.rstrip("\r\n")


# ---------------------------------------------------------------- blocks

_ids = itertools.count(1)


def split_patterns(value):
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def is_wildcard(pattern):
    return any(c in WILDCARD_CHARS for c in pattern)


class Trivia:
    """Comments / blank lines / global options that are not inside a block."""
    def __init__(self, lines):
        self.lines = lines


class Block:
    """A `Host ...` or `Match ...` section: header line + body lines."""

    def __init__(self, header, body=None):
        self.id = next(_ids)
        self.header = header
        self.body = body or []

    # --- basic properties
    @property
    def kind(self):
        return "match" if self.header.key.lower() == "match" else "host"

    @property
    def patterns(self):
        return split_patterns(self.header.value) if self.kind == "host" else []

    @property
    def alias(self):
        """First connectable alias, or None for pure wildcard/Match blocks."""
        for p in self.patterns:
            if not is_wildcard(p):
                return p
        return None

    @property
    def title(self):
        if self.kind == "match":
            return "Match " + self.header.value
        return " ".join(self.patterns) or T('(пусто)')

    def lines(self):
        return [self.header] + self.body

    def text(self):
        return "".join(line.raw for line in self.lines())

    def indent(self):
        for line in self.body:
            if line.kind in ("option", "meta") and line.indent:
                return line.indent
        return "  "

    # --- reading
    def options(self):
        return [(line.key, line.value) for line in self.body if line.kind == "option"]

    def get(self, key, default=""):
        k = key.lower()
        for line in self.body:
            if line.kind == "option" and line.key.lower() == k:
                return line.value
        return default

    def get_all(self, key):
        k = key.lower()
        return [line.value for line in self.body if line.kind == "option" and line.key.lower() == k]

    def meta(self, name, default=""):
        for line in self.body:
            if line.kind == "meta" and line.key == name:
                return line.value
        return default

    # --- writing (only touched lines get regenerated)
    def _anchor_end(self):
        """Index right after the last option/meta line in the body."""
        pos = 0
        for i, line in enumerate(self.body):
            if line.kind in ("option", "meta"):
                pos = i + 1
        return pos

    def set_patterns(self, patterns):
        patterns = [p for p in patterns if p]
        if not patterns:
            raise ConfigError(T('Не указано имя хоста (Host)'))
        if patterns == self.patterns:
            return
        joined = " ".join(shlex.quote(p) if " " in p else p for p in patterns)
        self.header = Line(f"{self.header.indent}{self.header.key} {joined}{_eol(self.header.raw) or chr(10)}")

    def set_meta(self, name, value):
        value = (value or "").strip()
        name = name.lower()
        for i, line in enumerate(self.body):
            if line.kind == "meta" and line.key == name:
                if not value:
                    del self.body[i]
                elif value != line.value:
                    self.body[i] = Line.meta(line.indent, name, value, _eol(line.raw) or "\n")
                return
        if not value:
            return
        # insert after header and any leading meta lines
        pos = 0
        while pos < len(self.body) and self.body[pos].kind == "meta":
            pos += 1
        self.body.insert(pos, Line.meta(self.indent(), name, value))

    def set_options(self, desired):
        """Makes the block's options equal to `desired` [(key, value), ...]
        while preserving untouched lines, comments and ordering. Keys are
        matched case-insensitively, occurrence by occurrence (so repeated
        keys such as IdentityFile / LocalForward work)."""
        indent = self.indent()
        want = [(k.strip(), str(v).strip()) for k, v in desired if k and k.strip() and str(v).strip() != ""]
        used = [False] * len(want)
        new_body = []
        for line in self.body:
            if line.kind != "option":
                new_body.append(line)
                continue
            idx = next((i for i, (k, _) in enumerate(want)
                        if not used[i] and k.lower() == line.key.lower()), None)
            if idx is None:
                continue  # option removed
            used[idx] = True
            value = want[idx][1]
            if value != line.value:
                line = Line.option(line.indent or indent, line.key, value, _eol(line.raw) or "\n")
            new_body.append(line)
        extra = [Line.option(indent, k, v) for i, (k, v) in enumerate(want) if not used[i]]
        if extra:
            pos = 0
            for i, line in enumerate(new_body):
                if line.kind in ("option", "meta"):
                    pos = i + 1
            new_body[pos:pos] = extra
        self.body = new_body

    def clone(self):
        b = copy.deepcopy(self)
        b.id = next(_ids)
        return b


def new_host_block(patterns, options=(), group="", desc=""):
    header = Line("Host " + " ".join(patterns) + "\n")
    block = Block(header, [])
    if group:
        block.set_meta("group", group)
    if desc:
        block.set_meta("desc", desc)
    block.set_options(list(options))
    return block


def parse_block_text(text):
    """Parses the text of a single Host/Match block (as edited in the raw
    tab). Lines after the header all stay in the block."""
    lines = [Line(raw) for raw in text.splitlines(keepends=True)]
    while lines and lines[0].kind == "blank":
        lines.pop(0)
    if not lines or lines[0].kind != "option" or lines[0].key.lower() not in ("host", "match"):
        raise ConfigError(T('Текст должен начинаться со строки «Host …» или «Match …»'))
    for line in lines[1:]:
        if line.kind == "option" and line.key.lower() in ("host", "match"):
            raise ConfigError(T('В тексте блока может быть только одна строка Host/Match'))
    while len(lines) > 1 and lines[-1].kind == "blank":
        lines.pop()
    if not lines[-1].raw.endswith("\n"):
        lines[-1] = Line(lines[-1].raw + "\n")
    block = Block(lines[0], lines[1:])
    if block.kind == "host" and not block.patterns:
        raise ConfigError(T('После Host нужно указать хотя бы одно имя'))
    return block


# ---------------------------------------------------------------- whole file

_SECTION_OR_CODE_RE = re.compile(r"^\s*(##|#\s*(Host|Match)\b)", re.I)


class SSHConfig:
    def __init__(self, segments, path=None, mtime=None):
        self.segments = segments
        self.path = path
        self.mtime = mtime

    @classmethod
    def parse(cls, text, path=None, mtime=None):
        segments = []
        trivia = []
        cur = None

        def close(block):
            pos = block._anchor_end()
            tail = block.body[pos:]
            block.body = block.body[:pos]
            segments.append(block)
            return tail

        for raw in text.splitlines(keepends=True):
            line = Line(raw)
            if line.kind == "option" and line.key.lower() in ("host", "match"):
                if cur is not None:
                    trivia = close(cur)
                if trivia:
                    segments.append(Trivia(trivia))
                    trivia = []
                cur = Block(line)
            elif cur is None:
                trivia.append(line)
            else:
                cur.body.append(line)
        if cur is not None:
            trivia = close(cur)
        if trivia:
            segments.append(Trivia(trivia))
        return cls(segments, path, mtime)

    @classmethod
    def load(cls, path=None):
        path = path or CONFIG_PATH
        if not os.path.exists(path):
            return cls([], path, None)
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as fh:
            text = fh.read()
        return cls.parse(text, path, os.stat(path).st_mtime_ns)

    def all_lines(self):
        for seg in self.segments:
            if isinstance(seg, Trivia):
                yield from seg.lines
            else:
                yield from seg.lines()

    def serialize(self):
        raws = [line.raw for line in self.all_lines()]
        # Every line but the very last must end with a newline (edited or
        # moved lines might not); the last one is left as the user had it.
        for i in range(len(raws) - 1):
            if not raws[i].endswith("\n"):
                raws[i] += "\n"
        return "".join(raws)

    def copy(self):
        return copy.deepcopy(self)

    # --- lookup
    def blocks(self):
        return [s for s in self.segments if isinstance(s, Block)]

    def _index(self, block_id):
        for i, seg in enumerate(self.segments):
            if isinstance(seg, Block) and seg.id == block_id:
                return i
        raise ConfigError(T('Блок не найден (файл изменился?)'))

    def find(self, block_id):
        return self.segments[self._index(block_id)]

    def groups(self):
        return sorted({b.meta("group") for b in self.blocks() if b.meta("group")}, key=str.lower)

    def aliases(self):
        out = []
        for b in self.blocks():
            for p in b.patterns:
                if not is_wildcard(p) and p not in out:
                    out.append(p)
        return out

    def leading_comments(self, block_id):
        """Comment lines sitting directly above a block's header (no blank
        line in between) — usually a description of that host."""
        i = self._index(block_id)
        if i == 0 or not isinstance(self.segments[i - 1], Trivia):
            return []
        lines = self.segments[i - 1].lines
        out = []
        for line in reversed(lines):
            if line.kind != "comment" or _SECTION_OR_CODE_RE.match(line.text()):
                break   # section headers ("## …") and commented-out blocks are not a host description
            out.insert(0, line)
        return out

    # --- mutation
    def replace_block(self, block_id, new_block):
        i = self._index(block_id)
        new_block.id = block_id
        self.segments[i] = new_block

    def insert_block(self, block, after_id=None):
        if after_id is not None:
            i = self._index(after_id) + 1
            self.segments[i:i] = [Trivia([Line("\n")]), block]
            return
        last = list(self.all_lines())
        if last and last[-1].kind != "blank":
            self.segments.append(Trivia([Line("\n")]))
        self.segments.append(block)

    def remove_block(self, block_id, with_leading_comments=False):
        n_lead = len(self.leading_comments(block_id)) if with_leading_comments else 0
        i = self._index(block_id)
        del self.segments[i]
        prev = self.segments[i - 1] if i > 0 else None
        nxt = self.segments[i] if i < len(self.segments) else None
        if n_lead and isinstance(prev, Trivia):
            del prev.lines[-n_lead:]   # exactly the lines shown in the delete dialog
        # Merge the surrounding trivia and avoid piling up blank lines.
        if isinstance(prev, Trivia) and isinstance(nxt, Trivia):
            nl = list(nxt.lines)
            if prev.lines and prev.lines[-1].kind == "blank":
                while nl and nl[0].kind == "blank":
                    nl.pop(0)
            prev.lines.extend(nl)
            del self.segments[i]
            nxt = self.segments[i] if i < len(self.segments) else None
        if isinstance(prev, Trivia) and not prev.lines:
            self.segments.remove(prev)
        if nxt is None and self.segments and isinstance(self.segments[-1], Trivia):
            # don't leave a growing tail of blank lines at EOF
            tl = self.segments[-1].lines
            while len(tl) > 1 and tl[-1].kind == "blank" and tl[-2].kind == "blank":
                tl.pop()


# ---------------------------------------------------------------- Include support

MAX_INCLUDE_DEPTH = 16   # same limit as OpenSSH


def include_patterns(value):
    return split_patterns(value)


def resolve_include(pattern):
    """OpenSSH rules for user configs: '~' expanded, relative paths are
    relative to ~/.ssh, glob patterns sorted alphabetically."""
    pat = os.path.expanduser(pattern)
    if not os.path.isabs(pat):
        pat = os.path.join(SSH_DIR, pat)
    if any(c in pat for c in "*?["):
        return sorted(p for p in glob.glob(pat) if os.path.isfile(p))
    return [pat] if os.path.isfile(pat) else []


def file_label(path, main_path=None):
    """Short name of a config file: relative to the main config's folder
    (or ~/.ssh), absolute otherwise."""
    real = os.path.realpath(path)
    for base in (os.path.dirname(os.path.realpath(main_path or CONFIG_PATH)), os.path.realpath(SSH_DIR)):
        if real.startswith(base + os.sep):
            return os.path.relpath(real, base)
    home = os.path.realpath(os.path.expanduser("~"))
    return "~" + real[len(home):] if real.startswith(home + os.sep) else real


# Cyrillic / Greek letters that look exactly like Latin ones (a classic cause
# of "my *.conf file is ignored": bridge.сonf with a Cyrillic "с").
_CONFUSABLES = str.maketrans("аАвВеЕкКмМнНоОрРсСтТуУхХіІјЈѕЅοΟρΡαΑεΕτΤκΚνΝ",
                             "aABBeEkKmMHHoOpPcCTTyYxXiIjJsSoOpPaAeETTkKvN")


def ascii_lookalike(name):
    return name.translate(_CONFUSABLES)


def lookalike_matches(pattern):
    """Files that do not match `pattern` only because of look-alike letters."""
    import fnmatch
    pat = os.path.expanduser(pattern)
    if not os.path.isabs(pat):
        pat = os.path.join(SSH_DIR, pat)
    directory, mask = os.path.split(pat)
    if any(c in directory for c in "*?[") or not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        fixed = ascii_lookalike(name)
        if fixed != name and fnmatch.fnmatchcase(fixed, mask) and os.path.isfile(os.path.join(directory, name)):
            out.append(os.path.join(directory, name))
    return out


class ConfigSet:
    """The main config plus every file pulled in with `Include`, presented
    with the same API as a single SSHConfig. Every block keeps living in its
    own file; edits are written back to that file only."""

    def __init__(self, main):
        self.main = main
        self.files = {}          # real path -> SSHConfig
        self.includes = []       # (from_path, directive value, [resolved paths], inside_block_title or None)
        self._add(main)

    # --- loading
    @classmethod
    def load(cls, path=None):
        cs = cls(SSHConfig.load(path or CONFIG_PATH))
        cs._load_includes(cs.main, 0)
        return cs

    def _add(self, cfg):
        self.files[os.path.realpath(cfg.path)] = cfg

    def _directives(self, cfg):
        """(line, inside_block or None) for every Include line of a file."""
        for seg in cfg.segments:
            if isinstance(seg, Trivia):
                for line in seg.lines:
                    if line.kind == "option" and line.key.lower() == "include":
                        yield line, None
            else:
                for line in seg.body:
                    if line.kind == "option" and line.key.lower() == "include":
                        yield line, seg

    def _load_includes(self, cfg, depth):
        if depth >= MAX_INCLUDE_DEPTH:
            return
        for line, inside in self._directives(cfg):
            resolved = []
            for pat in include_patterns(line.value):
                resolved += resolve_include(pat)
            self.includes.append((cfg.path, line.value, resolved, inside.title if inside else None))
            for path in resolved:
                real = os.path.realpath(path)
                if real in self.files:
                    continue              # already loaded (or a cycle)
                try:
                    sub = SSHConfig.load(path)
                except OSError:
                    continue
                self._add(sub)
                self._load_includes(sub, depth + 1)

    def reload_includes(self):
        """After the text of a file changed: re-resolve all Include lines,
        keeping already loaded (possibly edited) files."""
        keep = dict(self.files)
        self.files = {}
        self.includes = []
        self._add(self.main)
        self._reload_from(self.main, 0, keep)

    def _reload_from(self, cfg, depth, keep):
        if depth >= MAX_INCLUDE_DEPTH:
            return
        for line, inside in self._directives(cfg):
            resolved = []
            for pat in include_patterns(line.value):
                resolved += resolve_include(pat)
            self.includes.append((cfg.path, line.value, resolved, inside.title if inside else None))
            for path in resolved:
                real = os.path.realpath(path)
                if real in self.files:
                    continue
                sub = keep.get(real)
                if sub is None:
                    try:
                        sub = SSHConfig.load(path)
                    except OSError:
                        continue
                self._add(sub)
                self._reload_from(sub, depth + 1, keep)

    # --- the SSHConfig-like API
    @property
    def path(self):
        return self.main.path

    @property
    def mtime(self):
        return self.main.mtime

    def file_list(self):
        """Main first, then includes in the order ssh reads them."""
        order = [os.path.realpath(self.main.path)]
        for _, _, resolved, _ in self.includes:
            for p in resolved:
                rp = os.path.realpath(p)
                if rp in self.files and rp not in order:
                    order.append(rp)
        return [self.files[p] for p in order]

    def label(self, cfg_or_path):
        path = cfg_or_path if isinstance(cfg_or_path, str) else cfg_or_path.path
        return file_label(path, self.main.path)

    def blocks(self):
        """All Host/Match blocks in ssh's reading order (Include expanded in place)."""
        out = []
        seen = set()

        def walk(cfg, depth):
            real = os.path.realpath(cfg.path)
            if real in seen or depth > MAX_INCLUDE_DEPTH:
                return
            seen.add(real)

            def expand(line):
                for pat in include_patterns(line.value):
                    for path in resolve_include(pat):
                        sub = self.files.get(os.path.realpath(path))
                        if sub is not None:
                            walk(sub, depth + 1)

            for seg in cfg.segments:
                if isinstance(seg, Trivia):
                    for line in seg.lines:
                        if line.kind == "option" and line.key.lower() == "include":
                            expand(line)
                else:
                    seg.source = cfg.path
                    out.append(seg)
                    for line in seg.body:
                        if line.kind == "option" and line.key.lower() == "include":
                            expand(line)
        walk(self.main, 0)
        # files not reachable any more (e.g. Include removed in memory) are skipped
        return out

    def file_of(self, block_id):
        for cfg in self.files.values():
            for seg in cfg.segments:
                if isinstance(seg, Block) and seg.id == block_id:
                    return cfg
        raise ConfigError(T('Блок не найден (файл изменился?)'))

    def find(self, block_id):
        return self.file_of(block_id).find(block_id)

    def groups(self):
        return sorted({b.meta("group") for b in self.blocks() if b.meta("group")}, key=str.lower)

    def aliases(self):
        out = []
        for b in self.blocks():
            for p in b.patterns:
                if not is_wildcard(p) and p not in out:
                    out.append(p)
        return out

    def leading_comments(self, block_id):
        return self.file_of(block_id).leading_comments(block_id)

    def serialize(self):
        return self.main.serialize()

    def texts(self):
        return {real: cfg.serialize() for real, cfg in self.files.items()}

    def copy(self):
        return copy.deepcopy(self)

    def replace_block(self, block_id, new_block):
        new_block.source = self.file_of(block_id).path
        self.file_of(block_id).replace_block(block_id, new_block)

    def insert_block(self, block, after_id=None, target=None):
        """target: path of the file to put the block in (default: the file of
        after_id, else the main config)."""
        if target is not None:
            cfg = self.files[os.path.realpath(target)]
            if after_id is not None and self.file_of(after_id) is not cfg:
                after_id = None
        elif after_id is not None:
            cfg = self.file_of(after_id)
        else:
            cfg = self.main
        block.source = cfg.path
        cfg.insert_block(block, after_id=after_id)

    def remove_block(self, block_id, with_leading_comments=False):
        self.file_of(block_id).remove_block(block_id, with_leading_comments)

    # --- diagnostics: Include lines that do not do what the user expects
    @staticmethod
    def _include_lines(cfg):
        """(line number, Line, enclosing Block or None) for each Include of a file."""
        n = 0
        for seg in cfg.segments:
            if isinstance(seg, Trivia):
                for line in seg.lines:
                    n += 1
                    if line.kind == "option" and line.key.lower() == "include":
                        yield n, line, None
            else:
                n += 1                                   # header
                for line in seg.body:
                    n += 1
                    if line.kind == "option" and line.key.lower() == "include":
                        yield n, line, seg

    def include_problems(self):
        """List of dicts: kind = 'inside' (Include inside a Host/Match block,
        so ssh applies it only to that host) or 'nomatch' (pattern finds no
        file; `lookalikes` holds files that only differ by look-alike letters)."""
        out = []
        for cfg in self.file_list():
            for lineno, line, block in self._include_lines(cfg):
                if block is not None and block.title.strip() != "*":
                    out.append({"kind": "inside", "file": cfg.path, "lineno": lineno, "value": line.value,
                                "block": block.title})
                for pat in include_patterns(line.value):
                    if resolve_include(pat):
                        continue
                    out.append({"kind": "nomatch", "file": cfg.path, "lineno": lineno, "value": pat,
                                "lookalikes": lookalike_matches(pat)})
        return out

    def move_include_to_top(self, path, lineno):
        """Moves the Include on `lineno` of file `path` out of its block to the
        very top of that file (before the first Host/Match)."""
        cfg = self.files[os.path.realpath(path)]
        for n, line, block in self._include_lines(cfg):
            if n != lineno:
                continue
            if block is not None:
                block.body.remove(line)
            else:
                for seg in cfg.segments:
                    if isinstance(seg, Trivia) and line in seg.lines:
                        seg.lines.remove(line)
            new = Line(line.raw.lstrip())
            if not new.raw.endswith("\n"):
                new = Line(new.raw + "\n")
            if cfg.segments and isinstance(cfg.segments[0], Trivia):
                lines = cfg.segments[0].lines
                pos = 0                                   # keep a leading comment header on top
                while pos < len(lines) and lines[pos].kind == "comment":
                    pos += 1
                lines[pos:pos] = [new]
                if pos + 1 < len(lines) and lines[pos + 1].kind != "blank":
                    lines.insert(pos + 1, Line("\n"))
            else:
                cfg.segments.insert(0, Trivia([new, Line("\n")]))
            self.reload_includes()
            return True
        raise ConfigError(T('Строка {0} с Include не найдена').format(lineno))

    def mtimes_on_disk(self):
        out = {}
        for real, cfg in self.files.items():
            try:
                out[real] = os.stat(cfg.path).st_mtime_ns
            except OSError:
                out[real] = None
        return out

    def stale(self):
        """True when any file changed on disk or the Include globs resolve
        to a different set of files."""
        for real, cfg in self.files.items():
            try:
                if os.stat(cfg.path).st_mtime_ns != cfg.mtime:
                    return True
            except OSError:
                if cfg.mtime is not None:
                    return True
        if not os.path.exists(self.main.path) and self.main.mtime is None:
            return False
        current = set()
        for _, value, _, _ in self.includes:
            for pat in include_patterns(value):
                current.update(os.path.realpath(p) for p in resolve_include(pat))
        known = {os.path.realpath(p) for _, _, res, _ in self.includes for p in res}
        return current != known


# ---------------------------------------------------------------- ssh helpers

def ssh_base_args(path=None):
    path = path or CONFIG_PATH
    args = ["ssh"]
    if os.path.realpath(path) != os.path.realpath(DEFAULT_CONFIG):
        args += ["-F", path]
    return args


def validate_text(text, directory):
    """Asks ssh itself to parse the whole file (`ssh -G`). Raises
    ConfigError with ssh's message on any problem."""
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".hostkeep-check-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        try:
            proc = subprocess.run(["ssh", "-G", "-F", tmp, "hostkeep-validate.invalid"],
                                  capture_output=True, text=True, timeout=15)
        except FileNotFoundError as exc:
            raise ConfigError(T('ssh не найден в PATH')) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConfigError(T('ssh -G не ответил за 15с')) from exc
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip().replace(tmp, "config")
            raise ConfigError(msg or T('ssh -G: код возврата {0}').format(proc.returncode))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


SSH_DIR = os.path.expanduser("~/.ssh")


def backup_key(path):
    """Stable, readable file key for backup names: path relative to ~/.ssh
    ('config', 'conf.d%work.conf'); files elsewhere get their absolute path
    ('%etc%ssh%ssh_config')."""
    real = os.path.realpath(path)
    ssh_dir = os.path.realpath(SSH_DIR)
    if real.startswith(ssh_dir + os.sep):
        rel = os.path.relpath(real, ssh_dir)
    else:
        rel = real
    return rel.replace(os.sep, "%")


def backup_target(key):
    """Inverse of backup_key()."""
    rel = key.replace("%", os.sep)
    return rel if os.path.isabs(rel) else os.path.join(SSH_DIR, rel)


def make_backup(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    key = backup_key(path)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"{key}-{ts}")
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(BACKUP_DIR, f"{key}-{ts}-{n}")
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    for old in [b for b in list_backups() if b["key"] == key][MAX_BACKUPS:]:   # limit per file
        try:
            os.unlink(old["path"])
        except OSError:
            pass
    return dest


def delete_backup(path):
    """Removes one backup file; refuses anything outside the backup folder."""
    real = os.path.realpath(path)
    if os.path.dirname(real) != os.path.realpath(BACKUP_DIR) or not _BACKUP_NAME_RE.match(os.path.basename(real)):
        raise ConfigError(T('Это не резервная копия: {0}').format(path))
    os.unlink(real)


_BACKUP_NAME_RE = re.compile(r"^(?P<key>.+)-(?P<ts>\d{8}-\d{6})(?:-(?P<seq>\d+))?$")


def list_backups(target=None):
    """Newest first. Each item: path, name, key, target (file it belongs to),
    created (when the copy was taken), size. `target` filters by file."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    want = os.path.realpath(target) if target else None
    out = []
    for name in os.listdir(BACKUP_DIR):
        m = _BACKUP_NAME_RE.match(name)
        if not m:
            continue
        p = os.path.join(BACKUP_DIR, name)
        try:
            st = os.stat(p)
            if not stat.S_ISREG(st.st_mode):
                continue
        except OSError:
            continue
        # The copy keeps the source's mtime (shutil.copy2), so the moment the
        # backup was taken comes from its name.
        try:
            created = datetime.datetime.strptime(m.group("ts"), "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            created = st.st_mtime
        tgt = backup_target(m.group("key"))
        if want and os.path.realpath(tgt) != want:
            continue
        out.append({"path": p, "name": name, "key": m.group("key"), "target": tgt,
                    "label": m.group("key").replace("%", "/"),
                    "mtime": created, "created": created, "seq": int(m.group("seq") or 1),
                    "content_mtime": st.st_mtime, "size": st.st_size})
    out.sort(key=lambda b: (b["created"], b["seq"]), reverse=True)
    return out


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read()


def write_config(text, path=None, expected_mtime=None, force=False):
    """Validates, backs up and atomically writes the config. Returns the new
    mtime (ns). Follows a symlinked config instead of replacing the link."""
    path = path or CONFIG_PATH
    real = os.path.realpath(path)
    directory = os.path.dirname(real)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    exists = os.path.exists(real)
    if exists and expected_mtime is not None and not force:
        if os.stat(real).st_mtime_ns != expected_mtime:
            raise ExternalChangeError(T('Файл конфигурации был изменён другой программой после загрузки.'))
    validate_text(text, directory)
    mode = stat.S_IMODE(os.stat(real).st_mode) if exists else 0o600
    make_backup(real)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".hostkeep-write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return os.stat(real).st_mtime_ns


def effective_config(alias, path=None):
    """`ssh -G alias` — what ssh will actually use after all Host/Match
    blocks (first value wins) are applied."""
    proc = subprocess.run([*ssh_base_args(path), "-G", alias], capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        raise ConfigError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def test_connection(alias, path=None, timeout=8):
    """Non-interactive login attempt (BatchMode). Returns (ok, message)."""
    args = [*ssh_base_args(path), "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
            alias, "exit 0"]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout * 4,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, T('таймаут')
    if proc.returncode == 0:
        return True, "OK"
    lines = [ln for ln in (proc.stderr or "").strip().splitlines()
             if ln and not ln.startswith("Warning: Permanently added")]
    return False, (lines[-1] if lines else T('код {0}').format(proc.returncode))


def list_private_keys():
    ssh_dir = os.path.expanduser("~/.ssh")
    keys = []
    skip = {"config", "known_hosts", "known_hosts.old", "authorized_keys", "authorized_keys2", "environment"}
    for root, dirs, files in os.walk(ssh_dir):
        if root.count(os.sep) - ssh_dir.count(os.sep) > 1:
            dirs[:] = []
            continue
        for name in sorted(files):
            if name in skip or name.endswith((".pub", ".old", ".bak")) or name.startswith("."):
                continue
            p = os.path.join(root, name)
            try:
                if os.path.getsize(p) > 20000:
                    continue
                with open(p, "rb") as fh:
                    head = fh.read(60)
            except OSError:
                continue
            if b"PRIVATE KEY" in head:
                keys.append("~/" + os.path.relpath(p, os.path.expanduser("~")))
    return sorted(keys)


# ---------------------------------------------------------------- terminals

HOLD_CONDITIONS = {
    "ssh": "[ $ec -eq 255 ]",   # ssh's own failure (auth, network...), not the last remote command
    "error": "[ $ec -ne 0 ]",
    "always": "true",
}


def _keep_open_wrapper(ssh_argv, keep_open, title, hold="ssh"):
    script = (
        ': hostkeep-wrapper; '
        'printf "\\033]0;%s\\007" "$0"; '
        'echo "\\$ $*"; '
        '"$@"; ec=$?; '
    )
    if keep_open:
        script += (T('if {0}; then printf "\\n[завершено с кодом %s] Enter — закрыть окно…" $ec; read -r _; fi; ').format(HOLD_CONDITIONS[hold]))
    script += "exit $ec"
    return ["bash", "-c", script, title, *ssh_argv]


# id -> (label, binary, builder(title, cmd) -> argv)
TERMINALS = {
    "gnome-terminal": ("GNOME Terminal", "gnome-terminal",
                       lambda t, c: ["gnome-terminal", "--title", t, "--", *c]),
    "ptyxis": ("Ptyxis", "ptyxis", lambda t, c: ["ptyxis", "--new-window", "--", *c]),
    "kgx": ("GNOME Console (kgx)", "kgx", lambda t, c: ["kgx", "--title", t, "--", *c]),
    "konsole": ("Konsole", "konsole", lambda t, c: ["konsole", "-p", f"tabtitle={t}", "-e", *c]),
    "xfce4-terminal": ("Xfce Terminal", "xfce4-terminal", lambda t, c: ["xfce4-terminal", "-T", t, "-x", *c]),
    "tilix": ("Tilix", "tilix", lambda t, c: ["tilix", "-t", t, "-e", shlex.join(c)]),
    "terminator": ("Terminator", "terminator", lambda t, c: ["terminator", "-T", t, "-x", *c]),
    "alacritty": ("Alacritty", "alacritty", lambda t, c: ["alacritty", "--title", t, "-e", *c]),
    "kitty": ("kitty", "kitty", lambda t, c: ["kitty", "--title", t, *c]),
    "wezterm": ("WezTerm", "wezterm", lambda t, c: ["wezterm", "start", "--", *c]),
    "foot": ("foot", "foot", lambda t, c: ["foot", "--title", t, *c]),
    "xterm": ("xterm", "xterm", lambda t, c: ["xterm", "-T", t, "-e", *c]),
    "x-terminal-emulator": ('x-terminal-emulator (системный)', "x-terminal-emulator",
                            lambda t, c: ["x-terminal-emulator", "-e", *c]),
}


def available_terminals():
    return [tid for tid, (_, binary, _) in TERMINALS.items() if shutil.which(binary)]


def auto_terminal():
    avail = available_terminals()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    prefs = []
    if "kde" in desktop:
        prefs = ["konsole"]
    elif "xfce" in desktop:
        prefs = ["xfce4-terminal"]
    elif "gnome" in desktop or "unity" in desktop:
        prefs = ["gnome-terminal", "ptyxis", "kgx"]
    for tid in prefs + ["x-terminal-emulator"] + avail:
        if tid in avail:
            return tid
    return None


def build_terminal_argv(settings, title, cmd):
    tid = settings.get("terminal") or "auto"
    if tid == "custom":
        template = (settings.get("custom_terminal") or "").strip()
        if not template:
            raise ConfigError(T('Не задана команда своего терминала (Настройки)'))
        out = []
        for tok in shlex.split(template):
            if tok == "{cmd}":
                out.extend(cmd)
            else:
                out.append(tok.replace("{title}", title).replace("{cmd}", shlex.join(cmd)))
        if "{cmd}" not in template:
            out.extend(cmd)
        return out
    if tid == "auto" or tid not in TERMINALS or not shutil.which(TERMINALS[tid][1]):
        tid = auto_terminal()
    if not tid:
        raise ConfigError(T('Не найден ни один эмулятор терминала. Укажите свой в настройках.'))
    return TERMINALS[tid][2](title, cmd)


def spawn_detached(argv):
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def open_in_terminal(settings, title, command_argv, hold="ssh"):
    """Returns (terminal argv, Popen) — the caller may poll() it shortly
    after to detect a terminal that failed to start."""
    cmd = _keep_open_wrapper(command_argv, settings.get("keep_open", True), title, hold)
    argv = build_terminal_argv(settings, title, cmd)
    return argv, spawn_detached(argv)


def ssh_command(alias, path=None):
    return [*ssh_base_args(path), alias]


def ssh_copy_id_command(alias, identity_file=None, path=None):
    args = ["ssh-copy-id"]
    if identity_file:
        pub = os.path.expanduser(identity_file) + ".pub"
        if os.path.exists(pub):
            args += ["-i", pub]
    path = path or CONFIG_PATH
    if os.path.realpath(path) != os.path.realpath(DEFAULT_CONFIG):
        args += ["-F", path]
    return [*args, alias]


# ---------------------------------------------------------------- state / settings

DEFAULT_SETTINGS = {
    "terminal": "auto",
    "custom_terminal": "",
    "keep_open": True,
    "grouping": "",          # "" = auto, "meta", "prefix", "none"
}


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def migrate_legacy_data():
    """One-time copy of ~/.config/ssh-manager (old project name) to the new
    data directory. The old directory is left untouched."""
    if "HOSTKEEP_DATA" in os.environ or os.path.exists(APP_DIR) or not os.path.isdir(_LEGACY_APP_DIR):
        return False
    try:
        shutil.copytree(_LEGACY_APP_DIR, APP_DIR, ignore=shutil.ignore_patterns(".idea"))
        os.chmod(APP_DIR, 0o700)
        return True
    except OSError:
        return False


class State:
    def __init__(self):
        migrate_legacy_data()
        data = _read_json(STATE_FILE, {})
        self.settings = {**DEFAULT_SETTINGS, **data.get("settings", {})}
        self.stats = data.get("stats", {})
        self.tunnels = [normalize_tunnel(t) for t in data.get("tunnels", []) if isinstance(t, dict)]

    def save(self):
        _write_json(STATE_FILE, {"settings": self.settings, "stats": self.stats, "tunnels": self.tunnels})

    def tunnel(self, tid):
        return next((t for t in self.tunnels if t["id"] == tid), None)

    def upsert_tunnel(self, tunnel):
        tunnel = normalize_tunnel(tunnel)
        for i, t in enumerate(self.tunnels):
            if t["id"] == tunnel["id"]:
                self.tunnels[i] = tunnel
                break
        else:
            self.tunnels.append(tunnel)
        self.save()
        return tunnel

    def remove_tunnel(self, tid):
        self.tunnels = [t for t in self.tunnels if t["id"] != tid]
        self.save()

    def record_use(self, alias):
        s = self.stats.setdefault(alias, {"count": 0, "last": ""})
        s["count"] = s.get("count", 0) + 1
        s["last"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save()

    def recent(self, n=6):
        items = [(a, s) for a, s in self.stats.items() if s.get("last")]
        items.sort(key=lambda x: x[1]["last"], reverse=True)
        return [a for a, _ in items[:n]]


# ---------------------------------------------------------------- templates
# A template is: name, description, options [[key, value], ...], group.
# Values may contain {alias} — replaced with the new host's alias.

BUILTIN_TEMPLATES = [
    {"name": "Пустой", "desc": 'Только Host и HostName', "options": []},
    {"name": "Сервер по ключу", "desc": 'Стандартный сервер: вход по ключу, только указанный ключ',
     "options": [["Port", "22"], ["PubkeyAuthentication", "yes"], ["IdentitiesOnly", "yes"],
                 ["ConnectTimeout", "15"]]},
    {"name": "Через бастион (ProxyJump)", "desc": 'Сервер во внутренней сети, доступ через jump-хост — укажите ProxyJump',
     "options": [["Port", "22"], ["PubkeyAuthentication", "yes"], ["IdentitiesOnly", "yes"],
                 ["ProxyJump", ""], ["ConnectTimeout", "15"]]},
    {"name": "Подсеть / wildcard", "desc": 'Общие настройки для группы адресов, например 10.0.1.* — в поле «Host» укажите шаблон',
     "options": [["Port", "22"], ["PubkeyAuthentication", "yes"], ["IdentitiesOnly", "yes"],
                 ["ProxyJump", ""]]},
    {"name": "По паролю", "desc": 'Вход только по паролю, без перебора ключей',
     "options": [["PubkeyAuthentication", "no"], ["PreferredAuthentications", "password,keyboard-interactive"]]},
    {"name": "Туннель к БД (LocalForward)", "desc": 'Проброс порта: localhost:15432 → БД на удалённой стороне',
     "options": [["PubkeyAuthentication", "yes"], ["IdentitiesOnly", "yes"],
                 ["LocalForward", "15432 127.0.0.1:5432"], ["ExitOnForwardFailure", "yes"],
                 ["ServerAliveInterval", "30"]]},
    {"name": "Нестабильная сеть (keepalive)", "desc": 'Не рвать сессию при простое / плохом канале',
     "options": [["ServerAliveInterval", "30"], ["ServerAliveCountMax", "4"], ["TCPKeepAlive", "yes"]]},
    {"name": "Мультиплексирование", "desc": 'ControlMaster: повторные подключения открываются мгновенно',
     "options": [["ControlMaster", "auto"], ["ControlPath", "~/.ssh/cm-%r@%h:%p"], ["ControlPersist", "10m"]]},
    {"name": "Старый сервер (ssh-rsa)", "desc": 'Для устаревших серверов, принимающих только ssh-rsa',
     "options": [["HostKeyAlgorithms", "+ssh-rsa"], ["PubkeyAcceptedAlgorithms", "+ssh-rsa"]]},
]


def load_templates():
    user = _read_json(TEMPLATES_FILE, [])
    # "name" of a built-in template is a stable id; "title" is what the UI shows
    out = [dict(t, builtin=True, title=T(t["name"]), desc=T(t.get("desc", ""))) for t in BUILTIN_TEMPLATES]
    for t in user if isinstance(user, list) else []:
        if isinstance(t, dict) and t.get("name"):
            out.append({"name": t["name"], "desc": t.get("desc", ""), "group": t.get("group", ""),
                        "options": [list(o) for o in t.get("options", []) if len(o) == 2],
                        "builtin": False, "title": t["name"]})
    return out


def save_user_templates(templates):
    data = [{"name": t["name"], "desc": t.get("desc", ""), "group": t.get("group", ""),
             "options": t.get("options", [])} for t in templates if not t.get("builtin")]
    _write_json(TEMPLATES_FILE, data)


def template_options(template, alias=""):
    return [(k, v.replace("{alias}", alias)) for k, v in template.get("options", [])]


def parse_options_text(text):
    """'Key value' lines -> [[key, value], ...] (for the template editor)."""
    out = []
    for raw in text.splitlines():
        line = Line(raw)
        if line.kind == "option" and line.key.lower() not in ("host", "match"):
            out.append([line.key, line.value])
    return out


# ---------------------------------------------------------------- grouping

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){1,3}(\.\*)?$|^[0-9a-f:]+$", re.I)

RULES_GROUP = "⚙ Общие правила (*, Match)"
NO_GROUP = "Без группы"


def group_of(block, mode):
    if mode == "file":
        return file_label(getattr(block, "source", None) or CONFIG_PATH)
    if mode == "meta" and block.meta("group"):
        return block.meta("group")
    if block.alias is None:
        return RULES_GROUP
    if mode == "meta":
        return NO_GROUP
    if mode == "prefix":
        alias = block.alias
        if _IP_RE.match(alias):
            parts = alias.split(".")
            return "IP " + ".".join(parts[:2]) + ".*" if len(parts) >= 2 else "IP"
        head = re.split(r"[.\-_]", alias, 1)[0]
        return head or NO_GROUP
    return ""


KNOWN_KEYWORDS = sorted([
    "AddKeysToAgent", "AddressFamily", "BatchMode", "BindAddress", "BindInterface", "CanonicalDomains",
    "CanonicalizeHostname", "CertificateFile", "CheckHostIP", "Ciphers", "ClearAllForwardings", "Compression",
    "ConnectionAttempts", "ConnectTimeout", "ControlMaster", "ControlPath", "ControlPersist", "DynamicForward",
    "EscapeChar", "ExitOnForwardFailure", "ForwardAgent", "ForwardX11", "ForwardX11Trusted",
    "GSSAPIAuthentication", "GSSAPIDelegateCredentials", "GSSAPIKeyExchange", "HashKnownHosts",
    "HostKeyAlgorithms", "HostKeyAlias", "HostName", "IdentitiesOnly", "IdentityAgent", "IdentityFile",
    "IPQoS", "KbdInteractiveAuthentication", "KexAlgorithms", "LocalCommand", "LocalForward", "LogLevel",
    "MACs", "NumberOfPasswordPrompts", "PasswordAuthentication", "PermitLocalCommand", "PKCS11Provider",
    "Port", "PreferredAuthentications", "ProxyCommand", "ProxyJump", "ProxyUseFdpass",
    "PubkeyAcceptedAlgorithms", "PubkeyAuthentication", "RekeyLimit", "RemoteCommand", "RemoteForward",
    "RequestTTY", "SendEnv", "ServerAliveCountMax", "ServerAliveInterval", "SetEnv", "StreamLocalBindUnlink",
    "StrictHostKeyChecking", "TCPKeepAlive", "Tunnel", "UpdateHostKeys", "User", "UserKnownHostsFile",
    "VerifyHostKeyDNS", "VisualHostKey",
], key=str.lower)


# ---------------------------------------------------------------- tunnels
#
# A tunnel preset (stored in state.json):
#   id, alias (ssh host), type L|R|D, name,
#   bind / listen_port  — where the listening socket is opened
#                          (L, D: on this computer; R: on the server)
#   dest_host / dest_port — where connections are forwarded to
#                          (L: as seen from the server; R: as seen from this computer)
#   reconnect, autostart

TUNNEL_TYPES = {
    "L": ('Локальный (-L)', 'Сервис с сервера (или из его сети) становится доступен у вас на localhost:порт'),
    "R": ('Удалённый (-R)', 'Сервис с вашего компьютера становится доступен на сервере'),
    "D": ('SOCKS-прокси (-D)', 'SOCKS5-прокси у вас: трафик выходит в сеть с сервера'),
}

SERVICE_PRESETS = [
    ("PostgreSQL", 5432), ("MySQL / MariaDB", 3306), ("Redis / KeyDB", 6379), ("MongoDB", 27017),
    ("Elasticsearch", 9200), ("ClickHouse HTTP", 8123), ("Kafka", 9092), ("RabbitMQ UI", 15672),
    ("MinIO", 9000), ("MinIO Console", 9001), ("Kubernetes API", 6443), ("Vault", 8200),
    ("Grafana", 3000), ("Prometheus", 9090), ("HTTP", 80), ("HTTPS", 443), ("HTTP 8080", 8080),
    ("RDP", 3389), ("VNC", 5900), ("SSH", 22),
]

TUNNEL_DEFAULTS = {"id": "", "alias": "", "type": "L", "name": "", "bind": "", "listen_port": 0,
                   "dest_host": "127.0.0.1", "dest_port": 0, "reconnect": True, "autostart": False,
                   "open_action": "auto"}   # auto | http | https | copy

OPEN_ACTIONS = [("auto", 'Авто (по порту и названию)'), ("http", 'Открыть в браузере http://'),
                ("https", 'Открыть в браузере https://'), ("copy", 'Скопировать адрес')]


def normalize_tunnel(t):
    out = {**TUNNEL_DEFAULTS, **{k: v for k, v in t.items() if k in TUNNEL_DEFAULTS}}
    out["id"] = out["id"] or uuid.uuid4().hex[:12]
    out["type"] = out["type"] if out["type"] in TUNNEL_TYPES else "L"
    if out["open_action"] not in dict(OPEN_ACTIONS):
        out["open_action"] = "auto"
    for k in ("listen_port", "dest_port"):
        try:
            out[k] = int(out[k])
        except (TypeError, ValueError):
            out[k] = 0
    for k in ("alias", "name", "bind", "dest_host"):
        out[k] = str(out[k] or "").strip()
    return out


def _host_part(h):
    return f"[{h}]" if ":" in h and not h.startswith("[") else h


def tunnel_spec(t):
    listen = f"{_host_part(t['bind'])}:{t['listen_port']}" if t["bind"] else str(t["listen_port"])
    if t["type"] == "D":
        return listen
    return f"{listen}:{_host_part(t['dest_host'] or '127.0.0.1')}:{t['dest_port']}"


def tunnel_problems(t):
    out = []
    if not t["alias"]:
        out.append(T('не выбран хост'))
    if not 0 < t["listen_port"] < 65536:
        out.append(T('неверный порт прослушивания'))
    if t["type"] != "D":
        if not 0 < t["dest_port"] < 65536:
            out.append(T('неверный порт назначения'))
    return out


def tunnel_title(t):
    return t["name"] or f"{t['alias']}:{t['dest_port'] if t['type'] != 'D' else 'socks'}"


def tunnel_summary(t):
    """'Where the service lives ⇒ where it becomes available'."""
    bind = t["bind"] or "localhost"
    dest = f"{t['dest_host'] or '127.0.0.1'}:{t['dest_port']}"
    if t["type"] == "L":
        return T('{0} ⇒ {1}:{2}  (через {3})').format(dest, bind, t['listen_port'], t['alias'])
    if t["type"] == "R":
        dest = dest.replace("127.0.0.1:", "localhost:", 1)
        return T('{0} ⇒ {1}:{2}  (ваш сервис на сервере)').format(dest, t['alias'], t['listen_port'])
    return T('SOCKS5 {0}:{1} ⇒ выход в сеть через {2}').format(bind, t['listen_port'], t['alias'])


def tunnel_local_address(t):
    """host:port to use on this computer (None for -R)."""
    if t["type"] == "R":
        return None
    host = t["bind"] if t["bind"] not in ("", "*", "0.0.0.0", "::", "localhost") else "127.0.0.1"
    return f"{host}:{t['listen_port']}"


def tunnel_ssh_argv(t, path=None):
    flag = {"L": "-L", "R": "-R", "D": "-D"}[t["type"]]
    return [*ssh_base_args(path), "-N", "-T",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-o", "ConnectTimeout=20",
            flag, tunnel_spec(t), t["alias"]]


def port_in_use(port, host="127.0.0.1"):
    """True when something already listens on host:port. Uses a bind test,
    so no connection is made through an active tunnel."""
    if host in ("", "*", "localhost"):
        host = "127.0.0.1"
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def suggest_local_port(dest_port, taken=()):
    candidates = [dest_port + 10000, dest_port + 20000, dest_port] if dest_port < 45000 else [dest_port]
    candidates += list(range(15000, 15100))
    for p in candidates:
        if 1024 < p < 65536 and p not in taken and not port_in_use(p):
            return p
    return 0


def parse_forward_option(key, value):
    """LocalForward/RemoteForward/DynamicForward value from the config →
    tunnel-like dict (for display only)."""
    typ = {"localforward": "L", "remoteforward": "R", "dynamicforward": "D"}.get(key.lower())
    if not typ:
        return None
    parts = value.split()
    listen = parts[0] if parts else ""
    bind, _, port = listen.rpartition(":")
    t = {"type": typ, "bind": bind.strip("[]"), "listen_port": port}
    if typ != "D" and len(parts) > 1:
        dh, _, dp = parts[1].rpartition(":")
        t.update(dest_host=dh.strip("[]"), dest_port=dp)
    return normalize_tunnel(t)


ASKPASS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "askpass.py")


def _tunnel_env(t):
    env = dict(os.environ)
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        try:
            if not os.access(ASKPASS, os.X_OK):
                os.chmod(ASKPASS, 0o755)
            env["SSH_ASKPASS"] = ASKPASS
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env["HOSTKEEP_TUNNEL"] = tunnel_title(t)
        except OSError:
            pass
    return env


def _die_with_parent():
    """Tunnels must not outlive the app if it is killed: ask the kernel to
    SIGTERM the ssh child when the thread that started it goes away."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001
        pass


class TunnelRunner:
    """Runs one `ssh -N` tunnel in the background and keeps it alive.

    Callbacks are invoked from worker threads:
      on_state(tunnel_id, state, message)   state: starting|up|reconnecting|error|stopped
      on_log(tunnel_id, line)
    """

    def __init__(self, tunnel, on_state, on_log, path=None):
        self.tunnel = dict(tunnel)
        self.id = tunnel["id"]
        self.on_state = on_state
        self.on_log = on_log
        self.path = path
        self.state = "stopped"
        self.message = ""
        self.started_at = None
        self._proc = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def active(self):
        return self.state in ("starting", "up", "reconnecting")

    def _set(self, state, message=""):
        self.state, self.message = state, message
        self.on_state(self.id, state, message)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass

    def _loop(self):
        t = self.tunnel
        delay = 3
        while not self._stop.is_set():
            local = t["type"] != "R"
            if local and port_in_use(t["listen_port"], t["bind"] or "127.0.0.1"):
                self._set("error", T('порт {0} уже занят другой программой').format(t['listen_port']))
                return
            argv = tunnel_ssh_argv(t, self.path)
            self._set("starting", T('подключение…'))
            self.on_log(self.id, "$ " + " ".join(shlex.quote(a) for a in argv))
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True, errors="replace",
                                        start_new_session=True, env=_tunnel_env(t),
                                        preexec_fn=_die_with_parent)
            except OSError as exc:
                self._set("error", str(exc))
                return
            self._proc = proc
            last_lines = []

            def read_err():
                for line in proc.stderr:
                    line = line.rstrip()
                    if line:
                        last_lines.append(line)
                        del last_lines[:-5]
                        self.on_log(self.id, line)
            reader = threading.Thread(target=read_err, daemon=True)
            reader.start()

            up_since = None
            began = time.monotonic()
            while proc.poll() is None and not self._stop.is_set():
                if up_since is None:
                    ready = (port_in_use(t["listen_port"], t["bind"] or "127.0.0.1") if local
                             else time.monotonic() - began > 4)
                    if ready:
                        up_since = time.monotonic()
                        self.started_at = time.time()
                        delay = 3
                        self._set("up", T('работает'))
                time.sleep(0.4)
            if self._stop.is_set():
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                        proc.wait(5)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except OSError:
                            pass
                reader.join(1)
                break
            reader.join(2)
            code = proc.returncode
            reason = last_lines[-1] if last_lines else T('ssh завершился с кодом {0}').format(code)
            lived = time.monotonic() - up_since if up_since else 0
            # Only reconnect a tunnel that actually worked for a while; an
            # immediate failure (auth, busy port, typo) would just loop.
            if t.get("reconnect") and up_since is not None and lived >= 10:
                self._set("reconnecting", T('обрыв ({0}), повтор через {1}с').format(reason, delay))
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2, 60)
                continue
            self._set("error", reason)
            self._proc = None
            return
        self._proc = None
        self._set("stopped", T('остановлен'))


# Ports whose services have no web UI: double click copies the address
# instead of opening a browser.
# Only unambiguous non-HTTP protocols (databases, SSH, mail, RDP/VNC...).
NON_WEB_PORTS = {22, 23, 25, 53, 110, 143, 389, 445, 636, 1433, 1521, 2049, 2181, 3306, 3389, 4222,
                 5432, 5672, 5900, 5901, 6379, 6380, 9042, 9092, 11211, 26379, 27017, 27018}
HTTPS_PORTS = {443, 6443, 8443, 9443, 2376, 10250}
_WEB_NAME_RE = re.compile(r"ui|web|http|console|admin|panel|dashboard|grafana|kibana|prometheus|"
                          r"vault|minio|rabbit|jenkins|gitlab|argo|portal|site|api", re.I)


def tunnel_is_web(t):
    if t["type"] != "L":
        return False
    action = t.get("open_action", "auto")
    if action in ("http", "https"):
        return True
    if action == "copy":
        return False
    if _WEB_NAME_RE.search(t.get("name") or ""):
        return True
    return t["dest_port"] not in NON_WEB_PORTS


def tunnel_url(t):
    action = t.get("open_action", "auto")
    if action in ("http", "https"):
        scheme = action
    else:
        scheme = "https" if t["dest_port"] in HTTPS_PORTS else "http"
    return f"{scheme}://{tunnel_local_address(t)}/"


# ---------------------------------------------------------------- active ssh sessions

_SSH_FLAGS_WITH_ARG = set("BbcDEeFIiJLlmOoPpQRSWw")
_SS_RE = re.compile(r"(\S+)\s+users:\(\(.*?\"ssh\",pid=(\d+),")


def parse_ssh_argv(argv):
    """Very small ssh(1) command-line parser: destination, flags, command."""
    flags, opts, dest, command = set(), [], None, []
    i = 1
    while i < len(argv):
        a = argv[i]
        if dest is None and a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                ch = a[j]
                if ch in _SSH_FLAGS_WITH_ARG:
                    val = a[j + 1:] or (argv[i + 1] if i + 1 < len(argv) else "")
                    if not a[j + 1:]:
                        i += 1
                    opts.append((ch, val))
                    break
                flags.add(ch)
                j += 1
        elif dest is None:
            dest = a
        else:
            command = argv[i:]
            break
        i += 1
    user = next((v for k, v in opts if k == "l"), "")
    host = dest or ""
    if "@" in host:
        user, host = host.rsplit("@", 1)
    if host.startswith("ssh://"):
        host = host[6:]
    return {"flags": flags, "opts": opts, "host": host, "user": user, "command": command}


def _proc_read(pid, name):
    try:
        with open(f"/proc/{pid}/{name}", "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _boot_time():
    for line in _proc_read("self", "../stat").decode().splitlines():
        if line.startswith("btime"):
            return int(line.split()[1])
    return int(time.time())


def _ssh_peers():
    """pid -> remote address of its TCP connection (via `ss`)."""
    try:
        out = subprocess.run(["ss", "-tnpH", "state", "established"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    peers = {}
    for line in out.splitlines():
        m = _SS_RE.search(line)
        if m:
            peers[int(m.group(2))] = m.group(1)
    return peers


def list_ssh_sessions(tunnel_pids=()):
    """All ssh client processes of the current user. ProxyJump helpers
    (`ssh -W`) are folded into the session that spawned them."""
    uid = os.getuid()
    hz = os.sysconf("SC_CLK_TCK")
    boot = _boot_time()
    procs = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
        except OSError:
            continue
        if exe != "ssh":
            continue
        argv = [a.decode("utf-8", "replace") for a in _proc_read(pid, "cmdline").split(b"\0") if a]
        stat_raw = _proc_read(pid, "stat").decode("utf-8", "replace")
        if not argv or not stat_raw:
            continue
        fields = stat_raw[stat_raw.rfind(")") + 2:].split()
        procs[pid] = {"pid": pid, "ppid": int(fields[1]), "started": boot + int(fields[19]) / hz, "argv": argv}
    peers = _ssh_peers()
    tunnel_pids = set(tunnel_pids)
    sessions = {}
    helpers = []
    for pid, p in procs.items():
        argv = p["argv"]
        if argv[0].startswith("ssh: ") and "[mux]" in argv[0]:
            kind, info = "ControlMaster", {"host": argv[0][5:].replace("[mux]", "").strip(), "user": "",
                                           "flags": set(), "opts": [], "command": []}
        else:
            info = parse_ssh_argv(argv)
            if "W" in dict(info["opts"]):
                helpers.append(p)
                continue
            if "N" in info["flags"]:
                kind = "туннель"
            elif info["command"]:
                kind = "команда"
            else:
                kind = "сессия"
        parent_cmd = _proc_read(p["ppid"], "cmdline").decode("utf-8", "replace")
        sessions[pid] = {
            "pid": pid, "host": info["host"], "user": info["user"], "kind": kind,
            "command": " ".join(info["command"]), "started": p["started"], "peer": peers.get(pid, ""),
            "via": "", "argv": argv,
            "from_app": pid in tunnel_pids or ": hostkeep-wrapper;" in parent_cmd,
            "app_tunnel": pid in tunnel_pids,
        }
    for h in helpers:
        parent = sessions.get(h["ppid"])
        if parent is None:
            continue
        hinfo = parse_ssh_argv(h["argv"])
        parent["via"] = hinfo["host"]
        if not parent["peer"]:
            parent["peer"] = peers.get(h["pid"], "")
    return sorted(sessions.values(), key=lambda s: s["started"])


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return T('{0}д {1}ч').format(d, h)
    if h:
        return T('{0}ч {1:02d}м').format(h, m)
    return T('{0}м {1:02d}с').format(m, s)


def terminate_process(pid):
    os.kill(pid, signal.SIGTERM)
