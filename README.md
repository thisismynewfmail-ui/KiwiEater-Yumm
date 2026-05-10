# KiwiEater — Offline Wiki Backup System

A structured, navigable wiki archiver with a Ghost-in-the-Shell-themed control panel.
Backs up wikis (e.g. `https://kiwifarms.st/wiki/...`) into a fully offline,
self-contained, browseable archive with index / gallery / search.

## Quick start

```bash
pip install flask requests beautifulsoup4 lxml
python3 kiwieater.py
```

The script opens the WebUI in your browser automatically (default
`http://127.0.0.1:7743/`). If your browser doesn't pop up, the URL is printed
in the console — copy it.

## What it does

- Crawls a target wiki politely, with randomized delays, rotating user-agents,
  warm-up requests, header rotation, and exponential back-off — designed to
  ride past 403s, **KiwiFlare** challenges, Cloudflare prompts, and 429
  throttling without being noisy.
- Saves each page as a cleaned, skeletal HTML file (drops chrome: nav, edit
  links, scripts, comments, footers) inside `projects/<wiki_name>/pages/`.
- Stores **all images and local video as deduplicated BLOBs** (hashed by URL)
  inside `projects/<wiki_name>/blobs/` — small, no duplicates, fast lookup.
- Rewrites every internal link to point at the local archive copy. External
  links are neutralised but their original URL is kept in `data-external` so
  nothing is lost.
- Builds **Index**, **Gallery**, and **client-side Search** pages so the
  finished archive is navigable exactly like a real wiki.
- Persists everything in a SQLite DB (`archive.db`) so you can **stop**,
  close the script, **come back later**, and **Resume** the same project
  with no duplicate work.

## Folders & files written per archive

```
projects/
  ghost_in_the_shell/             # auto-named from the URL
    archive.db                    # pages + blobs + queue
    manifest.json                 # settings + summary, used to resume
    session.log                   # everything that happened, for debugging
    index.html                    # offline index
    gallery.html                  # all images
    search.html                   # client-side title search
    assets/archive.css            # archive theme
    pages/<sha1>.html             # one cleaned page per URL
    blobs/<sha1>.<ext>            # one blob per unique media URL
```

## Branding

`config.json` (in the same folder as the script) holds `branding` and
`archive_heading`. Both can also be edited from the UI — *Save Config*. The
values are baked into every page, the index, the gallery, and the search page
when the archive is finalized.

## Network access

In `config.json` set `"network_access": true` (or tick the toggle in the UI
and Save Config) to bind the server to `0.0.0.0` so other devices on your
LAN can reach the control panel and any built archives.

## Resuming

Every project keeps its queue, completed pages, and blob index in
`archive.db`. The **Resume** button on each project rebuilds the crawler with
the original settings stored in `manifest.json` and continues from where it
left off — already-saved pages are skipped, queued URLs continue draining.

## Anti-blocking strategies in use

- Warm-up GET against the site root (gathers cookies, looks like a real browser).
- Random User-Agent per request from a configurable pool.
- Full realistic header set (`Sec-Fetch-*`, `Accept-Language`, `DNT`, etc.).
- Per-request randomized delay between configurable min/max bounds.
- Adaptive exponential back-off on 403 / 429 / 503, with jitter.
- Fresh `requests.Session` rotation when blocking is suspected (drops cookies).
- Inline content sniffing for **KiwiFlare / Cloudflare / "just a moment"** —
  triggers a longer cool-down (8–15s) and re-arms the session before retrying.
- Skips edit/history/diff/api endpoints by default to avoid noisy hits and
  honeypot-style URLs.

## Common UI options

| Option | What it does |
|---|---|
| Source URL | The seed page. Wikis: a top-level page is fine, the crawler will spread out. |
| Project Name | Folder name. Auto-derived from the URL slug if blank (`/wiki/Ghost_in_the_Shell` → `ghost_in_the_shell`). |
| Path Prefix | Lock the crawl to e.g. `/wiki/` — strongly recommended for wikis to avoid wandering into forum threads. |
| Max Depth / Pages | Hard caps. |
| Sleep Min/Max | Random delay between requests in seconds. Increase if you keep getting 403s. |
| Same-Site Only | Refuses to follow links off the seed domain. |
| Download Blobs | Save images / video as BLOBs in `blobs/`. |

## Notes

- The Resume / Delete / Open buttons all live on the *Existing Archives* card.
  *Open* launches the offline archive in a new tab — served by the same
  Flask server out of `/archive/<name>/`.
- Logs are tailed live in the *Live Telemetry* panel and written to
  `projects/<name>/session.log`.
