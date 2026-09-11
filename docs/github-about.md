# GitHub "About" panel — values to set

The repo's About panel has not changed since the repo was created. Paste these in at
<https://github.com/Oddmagician6/typeset-studio> (the gear icon beside **About**).

## Description  (350 char limit; this is 134)

> Hand it a manuscript, get back a book you can print - PDF and EPUB, fonts embedded, covers and all. Runs offline, on your own machine.

## Website

```
https://ashforgestudio.com/typeset-studio.html
```

## Topics

```
typesetting  publishing  pdf  epub  self-publishing  book-design  kdp
ingramspark  python  flask  reportlab  markdown  offline-first  bookbinding
```

## Checkboxes

- **Releases** — on. The in-app update check reads a releases feed, so this is load-bearing.
- **Packages** — off.
- **Deployments** — off.

---

## Before flipping the repo to public

The secrets sweep came back clean — no keys, tokens or credentials in the tree or in
any historical diff. Remaining items, none of them blocking:

- [x] ~~`"Matthias Moore"` as the Cover Studio preview sample~~ - now `Author Name`, in
      both `app.py` and `templates/cover_editor.html`.
- [ ] Commit history carries `matthias.moore.pro@gmail.com`. Public on GitHub anyway;
      switching to the `@users.noreply.github.com` address would mean rewriting history.
- [ ] `app.py:270` sets `app.secret_key = 'typeset-studio-local'`. Fine for a localhost-only
      app, but a public repo invites "hardcoded secret" reports — worth a comment saying so.
- [ ] Decide whether `promo/` ships. It is the advertising reels; harmless, but it is
      marketing rather than program.
