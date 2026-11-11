# Changelog

## Unreleased

- English UI (Russian stays available); language picked from the system or in Settings and switched live (tunnels keep running).
- Required fields are marked softly; a field is highlighted only after it was left empty or on save.
- Theme setting: system / light / dark, applied instantly.
- Restyled inputs, dropdowns, context menus; calmer Connect buttons.
- Include diagnostics with one-click fixes; backups show their file, can be
  filtered and deleted.

## 0.1.0 — 2026-11-11

First public release.

- Lossless `~/.ssh/config` editing: untouched lines are written back byte for byte.
- Validation with `ssh -G` before every write, per-file backups, atomic writes,
  external-change detection.
- `Include` support following OpenSSH rules (globs, nesting, `~/.ssh`-relative
  paths); hosts are saved back into the file they live in.
- Hosts: grouped searchable list, settings-style form, raw text, effective
  config (`ssh -G`), required-field validation, templates, duplicate, delete
  with exact preview.
- Sessions open in the system terminal; terminal stays open on ssh errors.
- Background tunnels (`-L`, `-R`, `-D`) with status, auto-reconnect,
  autostart, open-in-browser / copy-address, tray control, askpass dialog.
- Live list of all ssh client processes of the user.
- Config editor with syntax highlighting and line numbers (GtkSourceView),
  backups page with diff preview and restore.
- Navigation rail, light and dark themes, tray icon.
