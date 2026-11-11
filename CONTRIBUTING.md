# Contributing to Hostkeep

Thanks for helping! A few ground rules keep the project trustworthy — it edits
people's `~/.ssh/config`, after all.

## The one rule

**Never lose a byte the user did not ask to change.** Any change to the parser
or writer (`hostkeep/backend.py`) needs a test in `tests/` showing that
untouched lines survive a load → edit → save round trip.

## Setup

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4 openssh-client xvfb
python3 -m unittest discover -s tests -v
./examples/run-demo.sh          # play with the UI on a throw-away config
```

Never develop against your real config: use `HOSTKEEP_CONFIG=/path/to/copy`
and `HOSTKEEP_DATA=/tmp/somewhere`, or `examples/run-demo.sh`.

## Layout

- `hostkeep/backend.py` — no GTK imports; everything testable lives here.
- `hostkeep/app.py` — GTK 3 UI.
- `tools/screenshots.py` — regenerates `docs/screenshots/` from the demo
  config. If your change is visible, please update the screenshots.

## Translations

UI strings are wrapped with `T("…")` (`hostkeep/i18n.py`); source strings are
Russian, catalogs live in `hostkeep/locale/<lang>.json`.

1. Copy `hostkeep/locale/en.json` to `<lang>.json` and translate the values.
   Keep `{0}`, `{1}`… placeholders and `<b>` / `<span …>` markup as they are.
2. Add the language to `LANGUAGES` in `hostkeep/i18n.py`.
3. Run the tests — `tests/test_i18n.py` fails if a string is missing or a
   placeholder/tag does not match.

When you add a new UI string, wrap it in `T()` and add it to every catalog.

## Wanted

- More translations.
- Packaging: Flatpak, AUR, `.deb`.
- A structured editor for `Match` blocks.

## Pull requests

Keep them focused, describe *why*, and make sure the tests pass. For larger
features, open an issue first so we can agree on the approach.
