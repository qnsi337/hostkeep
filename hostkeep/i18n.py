"""Tiny translation layer.

Source strings are Russian (the original language of the UI); catalogs in
hostkeep/locale/<lang>.json map them to other languages. To add a language,
copy en.json, translate the values (keep {0}, {1}… placeholders and any
<b>/<span> markup) and add the code to LANGUAGES.

The language is picked at start-up (and can be switched at runtime):
  1. HOSTKEEP_LANG environment variable ("ru", "en", …)
  2. "language" in ~/.config/hostkeep/state.json (set in Settings)
  3. the system locale (LANGUAGE / LC_ALL / LC_MESSAGES / LANG); Russian
     locales -> ru, everything else -> en
"""
import json
import os

SOURCE = "ru"
LANGUAGES = {"ru": "Русский", "en": "English"}
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")


def _state_language():
    data_dir = os.path.expanduser(os.environ.get(
        "HOSTKEEP_DATA", os.path.join(os.environ.get("XDG_CONFIG_HOME", "~/.config"), "hostkeep")))
    try:
        with open(os.path.join(data_dir, "state.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("settings") or {}).get("language") or ""
    except (OSError, ValueError, AttributeError):
        return ""


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val and val not in ("C", "POSIX") and not val.startswith("C."):
            code = val.split(":")[0].split("_")[0].split(".")[0].lower()
            return code if code in LANGUAGES else "en"
    return "en"


def pick_language():
    lang = os.environ.get("HOSTKEEP_LANG") or _state_language()
    if not lang or lang == "auto":
        lang = system_language()
    return lang if lang in LANGUAGES else "en"


LANG = SOURCE
_catalog = {}


def set_language(lang):
    """Switch the language at runtime (already built widgets keep their text —
    the UI rebuilds itself after calling this)."""
    global LANG, _catalog
    LANG = lang if lang in LANGUAGES else "en"
    _catalog = {}
    if LANG != SOURCE:
        try:
            with open(os.path.join(_DIR, f"{LANG}.json"), encoding="utf-8") as fh:
                _catalog = json.load(fh)
        except (OSError, ValueError):
            _catalog = {}


set_language(pick_language())


def T(text):
    """Translate a source (Russian) string; unknown strings pass through."""
    if not _catalog or not text:
        return text
    return _catalog.get(text) or text
