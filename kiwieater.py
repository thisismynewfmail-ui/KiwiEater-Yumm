#!/usr/bin/env python3
"""
KiwiEater - Offline Wiki Backup System
A structured wiki archiver with a navigable offline browser.

Run:  python3 kiwieater.py
Then open the URL printed in the console (auto-opens in browser).
"""

import os
import sys
import json
import time
import re
import hashlib
import logging
import sqlite3
import threading
import random
import mimetypes
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin, unquote, quote
from collections import deque

import requests
from bs4 import BeautifulSoup
from flask import (Flask, render_template_string, jsonify, request as flask_request,
                   send_file, Response, abort)

# ───────────────────────────── Paths & Config ─────────────────────────────
APP_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = APP_DIR / "config.json"
PROJECTS_DIR = APP_DIR / "projects"
LOGS_DIR = APP_DIR / "logs"
PROJECTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "branding": "KiwiEater Archive System",
    "archive_heading": "OFFLINE ARCHIVE",
    "host": "127.0.0.1",
    "port": 7743,
    "network_access": False,
    "network_host": "0.0.0.0",
    "default_delay_min": 2.0,
    "default_delay_max": 5.0,
    "max_retries": 5,
    "retry_backoff_base": 3.0,
    "request_timeout": 30,
    "max_concurrent": 2,
    "user_agents": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
    ],
    "skip_external_domains": True
}

def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

CFG = load_config()

# ───────────────────────────── Helpers ─────────────────────────────
def slugify_wiki_name(url: str) -> str:
    """Generate a clean folder name from a wiki URL — e.g.
    https://kiwifarms.st/wiki/Ghost_in_the_Shell  ->  ghost_in_the_shell
    https://kiwifarms.st                          ->  kiwifarms_st
    """
    p = urlparse(url)
    path = unquote(p.path).strip("/")
    # Drop the leading 'wiki' segment if present
    parts = [seg for seg in path.split("/") if seg]
    if parts and parts[0].lower() in ("wiki", "w", "index.php"):
        parts = parts[1:]
    if parts:
        candidate = parts[-1]
    else:
        candidate = p.netloc.replace(".", "_")
    candidate = re.sub(r"[^A-Za-z0-9_\-]", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_").lower()
    return candidate or "archive"

def safe_filename(s: str, maxlen: int = 180) -> str:
    s = unquote(s)
    s = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", s)
    s = s.strip(". ")
    if len(s) > maxlen:
        h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
        s = s[:maxlen - 9] + "_" + h
    return s or "page"

def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()

def normalize_url(url: str, base: str = None) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    # Drop fragment, keep query (some wikis use query for page id)
    rebuilt = parsed._replace(fragment="").geturl()
    return rebuilt

def is_same_site(url: str, root_netloc: str) -> bool:
    try:
        n = urlparse(url).netloc.lower()
        return n == "" or n == root_netloc or n.endswith("." + root_netloc) or root_netloc.endswith("." + n)
    except Exception:
        return False

# ───────────────────────────── Project (per-archive) ─────────────────────────────
class Project:
    """Holds all per-archive state: db, blobs, log, manifest."""
    def __init__(self, name: str):
        self.name = name
        self.dir = PROJECTS_DIR / name
        self.dir.mkdir(exist_ok=True, parents=True)
        self.pages_dir = self.dir / "pages"
        self.pages_dir.mkdir(exist_ok=True)
        self.blobs_dir = self.dir / "blobs"
        self.blobs_dir.mkdir(exist_ok=True)
        self.db_path = self.dir / "archive.db"
        self.manifest_path = self.dir / "manifest.json"
        self.log_path = self.dir / "session.log"
        self._db_lock = threading.Lock()
        self._init_db()
        if not self.manifest_path.exists():
            self._write_manifest({})

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS pages (
            url_hash TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            saved_path TEXT,
            status TEXT,           -- pending | done | failed
            http_status INTEGER,
            depth INTEGER,
            error TEXT,
            saved_at TEXT,
            attempts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS blobs (
            url_hash TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            local_name TEXT,
            mime TEXT,
            size INTEGER,
            saved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS queue (
            url_hash TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            depth INTEGER,
            added_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
        CREATE INDEX IF NOT EXISTS idx_pages_title ON pages(title);
        """)
        con.commit()
        con.close()

    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _write_manifest(self, data: dict):
        with open(self.manifest_path, "w") as f:
            json.dump(data, f, indent=2)

    def write_manifest(self, data: dict):
        with self._db_lock:
            self._write_manifest(data)

    def read_manifest(self) -> dict:
        try:
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

# ───────────────────────────── Crawler ─────────────────────────────
class Crawler:
    """Polite, resumable crawler with rich anti-blocking behavior."""

    def __init__(self, project: Project, settings: dict, logger: logging.Logger):
        self.project = project
        self.settings = settings
        self.log = logger
        self.session = requests.Session()
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.state = {
            "running": False,
            "paused": False,
            "started_at": None,
            "ended_at": None,
            "pages_done": 0,
            "pages_failed": 0,
            "pages_pending": 0,
            "blobs_done": 0,
            "current_url": "",
            "last_status": None,
            "last_error": "",
            "rate": 0.0
        }
        self._lock = threading.Lock()
        # parsed start url
        self.start_url = settings["start_url"].strip()
        self.root_netloc = urlparse(self.start_url).netloc.lower()
        self.path_prefix = settings.get("path_prefix", "").strip()  # e.g. "/wiki/"
        self.max_depth = int(settings.get("max_depth", 3))
        self.max_pages = int(settings.get("max_pages", 500))
        self.delay_min = float(settings.get("delay_min", CFG["default_delay_min"]))
        self.delay_max = float(settings.get("delay_max", CFG["default_delay_max"]))
        self.download_blobs = bool(settings.get("download_blobs", True))
        self.respect_robots = bool(settings.get("respect_robots", False))
        self.include_videos = bool(settings.get("include_videos", True))
        self.same_site_only = bool(settings.get("same_site_only", True))
        self.user_agents = list(CFG.get("user_agents", []))
        if not self.user_agents:
            self.user_agents = [DEFAULT_CONFIG["user_agents"][0]]
        self._referer = self.start_url

    # --- HTTP layer with anti-blocking ---
    def _build_headers(self, referer: str = None, accept: str = None) -> dict:
        ua = random.choice(self.user_agents)
        headers = {
            "User-Agent": ua,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _polite_sleep(self):
        if self.delay_max <= 0:
            return
        d = random.uniform(self.delay_min, self.delay_max)
        # break the sleep so stop/pause respond quickly
        end = time.time() + d
        while time.time() < end:
            if self.stop_flag.is_set():
                return
            while self.pause_flag.is_set() and not self.stop_flag.is_set():
                time.sleep(0.25)
            time.sleep(min(0.25, end - time.time()))

    def _fetch(self, url: str, is_blob: bool = False, referer: str = None):
        """
        Fetch with adaptive retries. Handles 403, 429, transient errors with
        exponential back-off, header rotation, and a fresh session as last resort.
        Returns (response, error_message_or_None).
        """
        timeout = CFG.get("request_timeout", 30)
        max_retries = CFG.get("max_retries", 5)
        backoff = CFG.get("retry_backoff_base", 3.0)
        ref = referer or self._referer
        last_err = None

        for attempt in range(1, max_retries + 1):
            if self.stop_flag.is_set():
                return None, "stopped"
            try:
                accept = None if not is_blob else "*/*"
                headers = self._build_headers(referer=ref, accept=accept)
                # rotate session every few attempts
                sess = self.session if attempt < 3 else requests.Session()
                resp = sess.get(url, headers=headers, timeout=timeout,
                                allow_redirects=True, stream=is_blob)
                self.state["last_status"] = resp.status_code

                if resp.status_code == 200:
                    return resp, None

                if resp.status_code in (403, 401, 429, 503):
                    # 403/blocking: longer backoff, reset session, rotate UA
                    self.log.warning(
                        "HTTP %s on %s — attempt %d/%d (anti-block backoff)",
                        resp.status_code, url, attempt, max_retries)
                    # If body suggests Cloudflare/KiwiFlare, escalate wait
                    sniff = ""
                    try:
                        sniff = resp.text[:2000].lower()
                    except Exception:
                        pass
                    challenge = any(w in sniff for w in
                                    ("cloudflare", "kiwiflare", "just a moment",
                                     "checking your browser", "ddos protection",
                                     "attention required", "captcha"))
                    extra = 5.0 if challenge else 0.0
                    wait = (backoff ** attempt) + random.uniform(0.5, 2.0) + extra
                    self.session = requests.Session()  # fresh cookies
                    time.sleep(wait)
                    continue

                if 500 <= resp.status_code < 600:
                    wait = (backoff ** attempt) + random.uniform(0, 1.5)
                    self.log.warning("HTTP %s on %s, retrying in %.1fs",
                                     resp.status_code, url, wait)
                    time.sleep(wait)
                    continue

                # 404 / others — give up early
                return resp, f"HTTP {resp.status_code}"

            except requests.Timeout:
                last_err = "timeout"
                wait = (backoff ** attempt) + random.uniform(0, 1.5)
                self.log.warning("Timeout on %s, retrying in %.1fs", url, wait)
                time.sleep(wait)
                self.session = requests.Session()
            except requests.ConnectionError as e:
                last_err = f"conn:{e.__class__.__name__}"
                wait = (backoff ** attempt) + random.uniform(0, 1.5)
                self.log.warning("Connection error %s on %s, retrying in %.1fs",
                                 e.__class__.__name__, url, wait)
                time.sleep(wait)
                self.session = requests.Session()
            except Exception as e:
                last_err = f"err:{e.__class__.__name__}:{e}"
                self.log.exception("Unexpected fetch error on %s", url)
                time.sleep(backoff)

        return None, last_err or "exhausted retries"

    # --- warm up: hit homepage to get cookies before the wiki ---
    def warm_up(self):
        try:
            home = f"{urlparse(self.start_url).scheme}://{self.root_netloc}/"
            self.log.info("Warming up session: %s", home)
            headers = self._build_headers(referer=None)
            self.session.get(home, headers=headers, timeout=CFG["request_timeout"])
            time.sleep(random.uniform(1.0, 2.5))
        except Exception as e:
            self.log.warning("Warm-up failed (non-fatal): %s", e)

    # --- crawl strategy ---
    def _should_follow(self, url: str) -> bool:
        if not url:
            return False
        if url.startswith(("javascript:", "mailto:", "tel:", "#")):
            return False
        p = urlparse(url)
        if self.same_site_only and not is_same_site(url, self.root_netloc):
            return False
        # Skip obvious junk endpoints common to MediaWiki
        path = p.path.lower()
        bad_substrings = (
            "/special:", "?action=edit", "&action=edit",
            "?action=history", "&action=history",
            "?action=raw", "&action=raw",
            "/api.php", "/load.php",
            "&printable=yes", "?printable=yes",
            "?oldid=", "&oldid=",
            "?diff=", "&diff=",
            "?redirect=no", "&redirect=no",
            "&action=info", "?action=info",
            "&action=delete", "?action=delete",
            "&veaction=", "?veaction=",
        )
        full = (path + "?" + (p.query or "")).lower()
        if any(b in full for b in bad_substrings):
            return False
        # If a path prefix is set, require it
        if self.path_prefix and not path.startswith(self.path_prefix.lower()):
            # Also allow root-level navigation pages
            if path not in ("", "/"):
                return False
        # Skip non-html-ish extensions
        if re.search(r"\.(zip|rar|7z|tar|gz|exe|dmg|iso|css|js)(\?|$)", path):
            return False
        return True

    def _is_blob_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return bool(re.search(
            r"\.(jpg|jpeg|png|gif|webp|svg|ico|bmp|mp4|webm|ogg|mp3|wav)(\?|$)",
            path))

    # --- queue ops ---
    def _queue_seed(self):
        # Only seed if queue empty AND no pages saved yet (true fresh start)
        with self.project.conn() as con:
            cur = con.cursor()
            qsize = cur.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            psize = cur.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            if qsize == 0 and psize == 0:
                self._enqueue(self.start_url, 0)

    def _enqueue(self, url: str, depth: int):
        url = normalize_url(url)
        if not url:
            return
        h = url_hash(url)
        with self.project.conn() as con:
            cur = con.cursor()
            row = cur.execute("SELECT 1 FROM pages WHERE url_hash=?", (h,)).fetchone()
            if row:
                return
            cur.execute(
                "INSERT OR IGNORE INTO queue(url_hash,url,depth,added_at) VALUES (?,?,?,?)",
                (h, url, depth, datetime.utcnow().isoformat())
            )
            con.commit()

    def _dequeue(self):
        with self.project.conn() as con:
            cur = con.cursor()
            row = cur.execute(
                "SELECT url_hash,url,depth FROM queue ORDER BY depth ASC, added_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            cur.execute("DELETE FROM queue WHERE url_hash=?", (row["url_hash"],))
            con.commit()
            return dict(row)

    def _mark_page(self, url: str, status: str, http_status=None, error=None,
                   title=None, saved_path=None, depth=0):
        h = url_hash(url)
        now = datetime.utcnow().isoformat()
        with self.project.conn() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO pages(url_hash,url,title,saved_path,status,http_status,
                                  depth,error,saved_at,attempts)
                VALUES (?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(url_hash) DO UPDATE SET
                  title=COALESCE(excluded.title, pages.title),
                  saved_path=COALESCE(excluded.saved_path, pages.saved_path),
                  status=excluded.status,
                  http_status=excluded.http_status,
                  error=excluded.error,
                  saved_at=excluded.saved_at,
                  attempts=pages.attempts+1
            """, (h, url, title, saved_path, status, http_status, depth, error, now))
            con.commit()

    # --- blob handling ---
    def _save_blob(self, url: str, referer: str = None) -> str:
        """Download and store as a deduplicated blob; return the local web path."""
        url = normalize_url(url, base=referer)
        if not url:
            return ""
        h = url_hash(url)
        with self.project.conn() as con:
            cur = con.cursor()
            row = cur.execute("SELECT local_name FROM blobs WHERE url_hash=?", (h,)).fetchone()
            if row:
                return f"../blobs/{row['local_name']}"
        # Skip videos if disabled
        if not self.include_videos and re.search(r"\.(mp4|webm|ogg)(\?|$)",
                                                  urlparse(url).path, re.I):
            return ""
        if self.same_site_only and not is_same_site(url, self.root_netloc):
            # Still fetch if it's a media subdomain — many wikis use one
            if not urlparse(url).netloc.endswith(self.root_netloc.split(":")[0]):
                return ""
        resp, err = self._fetch(url, is_blob=True, referer=referer or self._referer)
        if not resp or resp.status_code != 200:
            self.log.warning("Blob failed %s (%s)", url, err)
            return ""
        # Determine extension
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        if not ext or len(ext) > 6:
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            guessed = mimetypes.guess_extension(ct) if ct else None
            ext = guessed or ".bin"
        local_name = f"{h}{ext}"
        local_path = self.project.blobs_dir / local_name
        try:
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
            size = local_path.stat().st_size
        except Exception as e:
            self.log.exception("Blob write failed %s: %s", url, e)
            return ""
        with self.project.conn() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO blobs(url_hash,url,local_name,mime,size,saved_at)
                VALUES (?,?,?,?,?,?)
            """, (h, url, local_name,
                  resp.headers.get("Content-Type", "application/octet-stream"),
                  size, datetime.utcnow().isoformat()))
            con.commit()
        with self._lock:
            self.state["blobs_done"] += 1
        return f"../blobs/{local_name}"

    # --- HTML cleaning + rewriting ---
    STRIP_TAG_NAMES = {"script", "noscript", "iframe", "form", "input", "button",
                       "footer", "nav"}
    STRIP_BY_ID = re.compile(
        r"^(footer|siteSub|p-search|mw-navigation|mw-head|mw-panel|jump-to-nav|"
        r"catlinks|mw-page-base|mw-head-base|p-personal|p-cactions|p-tb|p-coll-print_export)$",
        re.I)
    STRIP_BY_CLASS = re.compile(
        r"(mw-editsection|noprint|printfooter|sister-projects|navbox|metadata|"
        r"mw-jump-link|mw-cite-backlink|reference-text-edit|mw-indicators|"
        r"vector-menu|mw-portlet|mw-footer|catlinks|advertisement|ad-banner|"
        r"comment|comments|kiwiflare)",
        re.I)

    def _clean_and_rewrite(self, html: str, page_url: str, depth: int):
        """Return (title, cleaned_html, child_links)."""
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        # try <h1 id=firstHeading>
        if soup.find(id="firstHeading"):
            title = soup.find(id="firstHeading").get_text(strip=True)

        # Remove unwanted tags
        for tag in soup.find_all(self.STRIP_TAG_NAMES):
            tag.decompose()
        for el in soup.find_all(attrs={"id": self.STRIP_BY_ID}):
            el.decompose()
        for el in soup.find_all(attrs={"class": self.STRIP_BY_CLASS}):
            el.decompose()
        # Strip on* event handlers and external stylesheets
        for el in soup.find_all(True):
            for attr in list(el.attrs.keys()):
                if attr.startswith("on") or attr in ("srcset", "data-srcset"):
                    del el.attrs[attr]
        for link in soup.find_all("link"):
            link.decompose()
        for style in soup.find_all("style"):
            style.decompose()

        child_links = []

        # Rewrite <a href>
        for a in soup.find_all("a", href=True):
            raw = a.get("href")
            absu = normalize_url(raw, base=page_url)
            if not absu:
                a.unwrap()
                continue
            if self._should_follow(absu):
                child_links.append(absu)
                local = f"{url_hash(absu)}.html"
                a["href"] = local
            else:
                # external — neutralize but keep label
                a["href"] = "#"
                a["data-external"] = absu
                a["class"] = (a.get("class") or []) + ["ext-link"]

        # Rewrite <img>
        if self.download_blobs:
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if not src:
                    continue
                absu = normalize_url(src, base=page_url)
                local = self._save_blob(absu, referer=page_url)
                if local:
                    img["src"] = local
                else:
                    img["data-failed-src"] = absu
                    img["src"] = ""
                # Strip srcset already removed above
            # rewrite <video> / <source>
            if self.include_videos:
                for src in soup.find_all(["source", "video", "audio"]):
                    s = src.get("src")
                    if not s:
                        continue
                    absu = normalize_url(s, base=page_url)
                    local = self._save_blob(absu, referer=page_url)
                    if local:
                        src["src"] = local

        # Pick the main content container if one exists, to drop chrome
        body = (soup.find(id="mw-content-text")
                or soup.find(id="content")
                or soup.find("main")
                or soup.body)
        body_html = body.decode_contents() if body else str(soup)

        return title, body_html, list(dict.fromkeys(child_links))

    PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — {brand}</title>
<link rel="stylesheet" href="../assets/archive.css">
</head><body>
<div class="frame">
  <header class="topbar">
    <a class="brand" href="../index.html">{brand}</a>
    <span class="tag">{heading}</span>
    <nav class="topnav">
      <a href="../index.html">Index</a>
      <a href="../gallery.html">Gallery</a>
      <a href="../search.html">Search</a>
    </nav>
  </header>
  <main class="content">
    <h1 class="page-title">{title}</h1>
    <article class="article">{body}</article>
    <p class="src">Source: <code>{src}</code></p>
  </main>
  <footer class="bottombar">Archived {date} • KiwiEater</footer>
</div>
</body></html>"""

    def _write_page(self, url: str, title: str, body_html: str) -> str:
        h = url_hash(url)
        fname = f"{h}.html"
        out = self.project.pages_dir / fname
        html = self.PAGE_TEMPLATE.format(
            title=(title or url),
            brand=CFG.get("branding", "KiwiEater Archive"),
            heading=CFG.get("archive_heading", "OFFLINE ARCHIVE"),
            body=body_html,
            src=url,
            date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        )
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        return f"pages/{fname}"

    # --- main loop ---
    def run(self):
        self.state["running"] = True
        self.state["started_at"] = datetime.utcnow().isoformat()
        self.log.info("=== Crawl start: %s ===", self.start_url)
        self.log.info("Settings: %s", json.dumps(self.settings))
        try:
            self._queue_seed()
            self.warm_up()
            t0 = time.time()
            while not self.stop_flag.is_set():
                while self.pause_flag.is_set() and not self.stop_flag.is_set():
                    self.state["paused"] = True
                    time.sleep(0.4)
                self.state["paused"] = False

                with self.project.conn() as con:
                    cur = con.cursor()
                    pages_done = cur.execute(
                        "SELECT COUNT(*) FROM pages WHERE status='done'").fetchone()[0]
                    pages_failed = cur.execute(
                        "SELECT COUNT(*) FROM pages WHERE status='failed'").fetchone()[0]
                    qsize = cur.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
                with self._lock:
                    self.state["pages_done"] = pages_done
                    self.state["pages_failed"] = pages_failed
                    self.state["pages_pending"] = qsize
                    elapsed = max(time.time() - t0, 1)
                    self.state["rate"] = round(pages_done / elapsed * 60, 2)

                if pages_done >= self.max_pages:
                    self.log.info("Reached max_pages=%d, stopping.", self.max_pages)
                    break

                item = self._dequeue()
                if not item:
                    self.log.info("Queue empty, finished.")
                    break

                url = item["url"]; depth = item["depth"]
                self.state["current_url"] = url
                self.log.info("[%d/%d depth=%d] %s",
                              pages_done + 1, self.max_pages, depth, url)

                resp, err = self._fetch(url, is_blob=False, referer=self._referer)
                self._referer = url
                if not resp:
                    self._mark_page(url, "failed", error=err, depth=depth)
                    self.state["last_error"] = err or "unknown"
                    self.log.error("FAIL %s -> %s", url, err)
                    self._polite_sleep()
                    continue

                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "html" not in ctype and "xml" not in ctype:
                    if self._is_blob_url(url) and self.download_blobs:
                        local = self._save_blob(url, referer=self._referer)
                        self._mark_page(url, "done", http_status=resp.status_code,
                                        title=os.path.basename(urlparse(url).path),
                                        saved_path=local, depth=depth)
                    else:
                        self._mark_page(url, "failed",
                                        error=f"non-html ({ctype})",
                                        http_status=resp.status_code, depth=depth)
                    self._polite_sleep()
                    continue

                try:
                    text = resp.text
                except Exception:
                    text = resp.content.decode("utf-8", errors="ignore")

                # KiwiFlare / Cloudflare detection
                low = text[:5000].lower()
                if any(w in low for w in ("kiwiflare", "just a moment",
                                          "checking your browser",
                                          "attention required")):
                    self.log.warning("Challenge page detected on %s; backing off", url)
                    self._mark_page(url, "failed",
                                    error="challenge-page",
                                    http_status=resp.status_code, depth=depth)
                    time.sleep(random.uniform(8, 15))
                    self.session = requests.Session()
                    self._polite_sleep()
                    continue

                try:
                    title, body, links = self._clean_and_rewrite(text, url, depth)
                    saved = self._write_page(url, title, body)
                    self._mark_page(url, "done", http_status=resp.status_code,
                                    title=title, saved_path=saved, depth=depth)
                    self.log.info("OK %s (%d links)", title or url, len(links))
                    if depth + 1 <= self.max_depth:
                        for ln in links:
                            self._enqueue(ln, depth + 1)
                except Exception as e:
                    self.log.exception("Parse error on %s", url)
                    self._mark_page(url, "failed", error=f"parse:{e}",
                                    http_status=resp.status_code, depth=depth)

                self._polite_sleep()

            self._finalize()
        except Exception as e:
            self.log.exception("Crawler crashed: %s", e)
        finally:
            self.state["running"] = False
            self.state["ended_at"] = datetime.utcnow().isoformat()
            self.log.info("=== Crawl end ===")

    def _finalize(self):
        """Write Index, Gallery, Search, manifest, archive.css."""
        self.log.info("Building index, gallery, search…")
        with self.project.conn() as con:
            cur = con.cursor()
            pages = cur.execute(
                "SELECT url,title,saved_path,depth FROM pages "
                "WHERE status='done' AND saved_path LIKE 'pages/%' "
                "ORDER BY title COLLATE NOCASE"
            ).fetchall()
            blobs = cur.execute(
                "SELECT url,local_name,mime,size FROM blobs "
                "WHERE mime LIKE 'image/%' ORDER BY local_name"
            ).fetchall()

        # ---- archive.css (Ghost-in-the-Shell-flavored, fifties-CRT hybrid) ----
        assets_dir = self.project.dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        css = ARCHIVE_CSS
        (assets_dir / "archive.css").write_text(css, encoding="utf-8")

        # ---- index.html ----
        rows = []
        for r in pages:
            t = (r["title"] or r["url"]).replace("<", "&lt;")
            rows.append(
                f'<li><a href="{r["saved_path"]}">{t}</a>'
                f'<span class="meta">depth {r["depth"]}</span></li>'
            )
        idx_html = INDEX_TEMPLATE.format(
            brand=CFG.get("branding", "KiwiEater Archive"),
            heading=CFG.get("archive_heading", "OFFLINE ARCHIVE"),
            count=len(pages),
            blob_count=len(blobs),
            generated=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            source=self.start_url,
            rows="\n".join(rows) or "<li><em>(no pages)</em></li>"
        )
        (self.project.dir / "index.html").write_text(idx_html, encoding="utf-8")

        # ---- gallery.html ----
        items = []
        for b in blobs:
            items.append(
                f'<figure><img loading="lazy" src="blobs/{b["local_name"]}">'
                f'<figcaption>{os.path.basename(urlparse(b["url"]).path)}</figcaption></figure>'
            )
        gal_html = GALLERY_TEMPLATE.format(
            brand=CFG.get("branding", "KiwiEater Archive"),
            heading=CFG.get("archive_heading", "OFFLINE ARCHIVE"),
            items="\n".join(items) or "<p><em>(no images)</em></p>"
        )
        (self.project.dir / "gallery.html").write_text(gal_html, encoding="utf-8")

        # ---- search.html (client-side index) ----
        search_index = [
            {"t": (r["title"] or r["url"]), "p": r["saved_path"]}
            for r in pages
        ]
        search_html = SEARCH_TEMPLATE.format(
            brand=CFG.get("branding", "KiwiEater Archive"),
            heading=CFG.get("archive_heading", "OFFLINE ARCHIVE"),
            data=json.dumps(search_index)
        )
        (self.project.dir / "search.html").write_text(search_html, encoding="utf-8")

        # ---- manifest ----
        self.project.write_manifest({
            "name": self.project.name,
            "source": self.start_url,
            "branding": CFG.get("branding", "KiwiEater Archive"),
            "heading": CFG.get("archive_heading", "OFFLINE ARCHIVE"),
            "pages": len(pages),
            "blobs": len(blobs),
            "settings": self.settings,
            "generated": datetime.utcnow().isoformat() + "Z"
        })


# ───────────────────────────── Templates ─────────────────────────────
ARCHIVE_CSS = r"""
:root{
  --bg:#0b1112; --panel:#0f1719; --ink:#cfeee8; --accent:#7afcd6;
  --accent2:#ffb347; --grid:rgba(122,252,214,.08); --rule:rgba(122,252,214,.25);
  --warn:#ff5577;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Mono","Courier New",monospace;line-height:1.55}
body{
  background-image:
    linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:32px 32px;
}
.frame{max-width:1080px;margin:0 auto;padding:0 18px}
.topbar{display:flex;align-items:center;gap:18px;
  border-bottom:1px solid var(--rule);padding:14px 0;
  background:linear-gradient(180deg,rgba(122,252,214,.05),transparent)}
.brand{color:var(--accent);text-decoration:none;font-weight:700;letter-spacing:.18em}
.tag{font-size:.78rem;color:var(--accent2);border:1px solid var(--accent2);
  padding:2px 8px;border-radius:2px;letter-spacing:.2em}
.topnav{margin-left:auto;display:flex;gap:14px}
.topnav a{color:var(--ink);text-decoration:none;border-bottom:1px dashed transparent}
.topnav a:hover{border-color:var(--accent);color:var(--accent)}
.content{padding:24px 0 60px}
.page-title{font-size:1.6rem;color:var(--accent);
  border-left:3px solid var(--accent);padding:6px 12px;margin:0 0 18px}
.article a{color:var(--accent2)}
.article a.ext-link{opacity:.65;text-decoration:line-through;cursor:not-allowed}
.article img{max-width:100%;height:auto;border:1px solid var(--rule);
  background:#000;display:block;margin:8px 0}
.article table{border-collapse:collapse;margin:8px 0}
.article table,.article th,.article td{border:1px solid var(--rule);padding:6px 10px}
.article h2,.article h3{color:var(--accent);border-bottom:1px solid var(--rule);
  padding-bottom:4px}
.article pre,.article code{background:#000;padding:2px 6px;border:1px solid var(--rule)}
.src{font-size:.78rem;opacity:.6;margin-top:30px;border-top:1px dashed var(--rule);
  padding-top:8px;word-break:break-all}
.bottombar{border-top:1px solid var(--rule);padding:14px 0;font-size:.8rem;
  opacity:.7;letter-spacing:.16em}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
  gap:12px;padding:18px 0}
.gallery figure{margin:0;border:1px solid var(--rule);background:#000}
.gallery img{width:100%;height:160px;object-fit:cover;display:block}
.gallery figcaption{font-size:.7rem;padding:6px;opacity:.7;
  border-top:1px solid var(--rule)}
.search-bar{display:flex;gap:8px;margin:18px 0}
.search-bar input{flex:1;background:#000;color:var(--accent);
  border:1px solid var(--rule);padding:10px 12px;font-family:inherit;font-size:1rem}
.search-bar input:focus{outline:1px solid var(--accent)}
.results{list-style:none;padding:0;margin:0}
.results li{padding:8px 10px;border-bottom:1px dashed var(--rule)}
.results a{color:var(--ink);text-decoration:none}
.results a:hover{color:var(--accent)}
.list{list-style:none;padding:0;margin:0}
.list li{padding:8px 10px;border-bottom:1px dashed var(--rule);
  display:flex;justify-content:space-between;align-items:center}
.list a{color:var(--ink);text-decoration:none}
.list a:hover{color:var(--accent)}
.list .meta{font-size:.7rem;opacity:.6}
.stats{display:flex;gap:24px;margin:14px 0 28px;flex-wrap:wrap}
.stat{border:1px solid var(--rule);padding:10px 14px}
.stat b{color:var(--accent);font-size:1.3rem;display:block}
.stat span{font-size:.7rem;letter-spacing:.18em;opacity:.7}
"""

INDEX_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Index — {brand}</title><link rel="stylesheet" href="assets/archive.css"></head>
<body><div class="frame">
<header class="topbar">
  <a class="brand" href="index.html">{brand}</a>
  <span class="tag">{heading}</span>
  <nav class="topnav">
    <a href="index.html">Index</a>
    <a href="gallery.html">Gallery</a>
    <a href="search.html">Search</a>
  </nav>
</header>
<main class="content">
  <h1 class="page-title">Archive Index</h1>
  <div class="stats">
    <div class="stat"><b>{count}</b><span>PAGES</span></div>
    <div class="stat"><b>{blob_count}</b><span>BLOBS</span></div>
    <div class="stat"><b>{generated}</b><span>GENERATED (UTC)</span></div>
  </div>
  <p class="src">Source: <code>{source}</code></p>
  <ul class="list">{rows}</ul>
</main>
<footer class="bottombar">KiwiEater offline archive</footer>
</div></body></html>"""

GALLERY_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Gallery — {brand}</title><link rel="stylesheet" href="assets/archive.css"></head>
<body><div class="frame">
<header class="topbar">
  <a class="brand" href="index.html">{brand}</a>
  <span class="tag">{heading}</span>
  <nav class="topnav">
    <a href="index.html">Index</a>
    <a href="gallery.html">Gallery</a>
    <a href="search.html">Search</a>
  </nav>
</header>
<main class="content">
  <h1 class="page-title">Gallery</h1>
  <div class="gallery">{items}</div>
</main>
<footer class="bottombar">KiwiEater offline archive</footer>
</div></body></html>"""

SEARCH_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Search — {brand}</title><link rel="stylesheet" href="assets/archive.css"></head>
<body><div class="frame">
<header class="topbar">
  <a class="brand" href="index.html">{brand}</a>
  <span class="tag">{heading}</span>
  <nav class="topnav">
    <a href="index.html">Index</a>
    <a href="gallery.html">Gallery</a>
    <a href="search.html">Search</a>
  </nav>
</header>
<main class="content">
  <h1 class="page-title">Search</h1>
  <div class="search-bar"><input id="q" placeholder="Type to search titles…"></div>
  <ul class="results" id="r"></ul>
</main>
<footer class="bottombar">KiwiEater offline archive</footer>
</div>
<script>
const DATA = {data};
const q=document.getElementById("q"), r=document.getElementById("r");
function render(list){{r.innerHTML=list.map(x=>'<li><a href="'+x.p+'">'+x.t.replace(/</g,"&lt;")+'</a></li>').join("")||"<li><em>no matches</em></li>";}}
render(DATA.slice(0,200));
q.addEventListener("input",()=>{{const s=q.value.toLowerCase().trim();
  if(!s){{render(DATA.slice(0,200));return;}}
  render(DATA.filter(x=>x.t.toLowerCase().includes(s)).slice(0,500));}});
</script></body></html>"""


# ───────────────────────────── Logging per-project ─────────────────────────────
def make_logger(project: Project) -> logging.Logger:
    name = f"kiwieater.{project.name}"
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    # Avoid duplicate handlers on resume
    for h in list(lg.handlers):
        lg.removeHandler(h)
    fh = logging.FileHandler(project.log_path, encoding="utf-8")
    sh = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt); sh.setFormatter(fmt)
    lg.addHandler(fh); lg.addHandler(sh)
    lg.propagate = False
    return lg


# ───────────────────────────── Job Manager ─────────────────────────────
class JobManager:
    def __init__(self):
        self.crawler: Crawler | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def start(self, settings: dict):
        with self.lock:
            if self.crawler and self.crawler.state["running"]:
                return False, "A crawl is already running."
            name = settings.get("project_name") or slugify_wiki_name(settings["start_url"])
            settings["project_name"] = name
            project = Project(name)
            logger = make_logger(project)
            self.crawler = Crawler(project, settings, logger)
            t = threading.Thread(target=self.crawler.run, daemon=True)
            self.thread = t
            t.start()
            return True, name

    def stop(self):
        with self.lock:
            if self.crawler:
                self.crawler.stop_flag.set()

    def pause(self, paused: bool):
        with self.lock:
            if self.crawler:
                if paused:
                    self.crawler.pause_flag.set()
                else:
                    self.crawler.pause_flag.clear()

    def status(self):
        with self.lock:
            if not self.crawler:
                return {"running": False, "project": None, "state": None}
            return {
                "running": self.crawler.state["running"],
                "project": self.crawler.project.name,
                "state": dict(self.crawler.state),
                "settings": self.crawler.settings,
            }

JOBS = JobManager()


# ───────────────────────────── Flask App ─────────────────────────────
app = Flask(__name__)

@app.route("/")
def root():
    return render_template_string(UI_HTML,
        brand=CFG.get("branding"),
        heading=CFG.get("archive_heading"))

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    global CFG
    if flask_request.method == "POST":
        data = flask_request.get_json(force=True)
        for k in ("branding", "archive_heading", "network_access",
                  "default_delay_min", "default_delay_max", "max_retries",
                  "request_timeout"):
            if k in data:
                CFG[k] = data[k]
        save_config(CFG)
    return jsonify(CFG)

@app.route("/api/projects")
def api_projects():
    out = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        man = d / "manifest.json"
        meta = {}
        if man.exists():
            try:
                meta = json.load(open(man))
            except Exception:
                pass
        # quick stats from db if present
        db = d / "archive.db"
        stats = {"pages": 0, "queue": 0, "failed": 0}
        if db.exists():
            try:
                con = sqlite3.connect(db)
                cur = con.cursor()
                stats["pages"] = cur.execute(
                    "SELECT COUNT(*) FROM pages WHERE status='done'").fetchone()[0]
                stats["queue"] = cur.execute(
                    "SELECT COUNT(*) FROM queue").fetchone()[0]
                stats["failed"] = cur.execute(
                    "SELECT COUNT(*) FROM pages WHERE status='failed'").fetchone()[0]
                con.close()
            except Exception:
                pass
        out.append({"name": d.name, "manifest": meta, "stats": stats})
    return jsonify(out)

@app.route("/api/start", methods=["POST"])
def api_start():
    s = flask_request.get_json(force=True)
    if not s.get("start_url"):
        return jsonify({"ok": False, "error": "start_url required"}), 400
    ok, msg = JOBS.start(s)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 409
    return jsonify({"ok": True, "project": msg})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    JOBS.stop()
    return jsonify({"ok": True})

@app.route("/api/pause", methods=["POST"])
def api_pause():
    data = flask_request.get_json(force=True) or {}
    JOBS.pause(bool(data.get("paused", True)))
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    return jsonify(JOBS.status())

@app.route("/api/log/<project>")
def api_log(project):
    p = PROJECTS_DIR / project / "session.log"
    if not p.exists():
        return jsonify({"lines": []})
    try:
        # tail last 400 lines
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-400:]
        return jsonify({"lines": [l.rstrip() for l in lines]})
    except Exception as e:
        return jsonify({"lines": [f"(log read error: {e})"]})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    data = flask_request.get_json(force=True)
    name = data.get("project_name")
    if not name:
        return jsonify({"ok": False, "error": "project_name required"}), 400
    proj = PROJECTS_DIR / name
    if not proj.is_dir():
        return jsonify({"ok": False, "error": "project not found"}), 404
    man = {}
    if (proj / "manifest.json").exists():
        try:
            man = json.load(open(proj / "manifest.json"))
        except Exception:
            pass
    settings = man.get("settings", {})
    settings["project_name"] = name
    if not settings.get("start_url"):
        return jsonify({"ok": False,
                        "error": "no start_url stored — cannot resume"}), 400
    ok, msg = JOBS.start(settings)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 409
    return jsonify({"ok": True, "project": msg})

@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = flask_request.get_json(force=True)
    name = data.get("project_name")
    if not name:
        return jsonify({"ok": False, "error": "project_name required"}), 400
    p = PROJECTS_DIR / name
    if p.is_dir():
        import shutil; shutil.rmtree(p, ignore_errors=True)
    return jsonify({"ok": True})

@app.route("/archive/<project>/")
@app.route("/archive/<project>/<path:sub>")
def archive_serve(project, sub="index.html"):
    base = PROJECTS_DIR / project
    target = (base / sub).resolve()
    try:
        target.relative_to(base.resolve())
    except Exception:
        abort(403)
    if target.is_dir():
        target = target / "index.html"
    if not target.exists():
        abort(404)
    return send_file(target)


# ───────────────────────────── UI HTML ─────────────────────────────
UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{brand}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=VT323&family=Share+Tech+Mono&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#070c0d; --panel:#0d1517; --panel-2:#0a1213;
  --ink:#d6f5ee; --dim:#7c9c95;
  --accent:#7afcd6;        /* Tachikoma cyan-mint */
  --accent-2:#ffb347;      /* GITS amber */
  --warn:#ff5577;
  --rule:rgba(122,252,214,.22);
  --grid:rgba(122,252,214,.06);
  --shadow:0 0 0 1px var(--rule), 0 0 24px rgba(122,252,214,.06) inset;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Mono","Share Tech Mono",monospace;
  -webkit-font-smoothing:antialiased;overflow-x:hidden}

/* ── animated grid floor + scan lines + soft vignette ── */
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(ellipse at 50% 30%,transparent 0,rgba(0,0,0,.55) 75%),
    repeating-linear-gradient(0deg,rgba(0,0,0,.18) 0 2px,transparent 2px 4px);
}
body::after{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:1;
  background-image:
    linear-gradient(var(--grid) 1px,transparent 1px),
    linear-gradient(90deg,var(--grid) 1px,transparent 1px);
  background-size:48px 48px;
  animation: drift 24s linear infinite;
}
@keyframes drift{from{background-position:0 0,0 0}to{background-position:0 480px,480px 0}}

/* ── moving sweep bar ── */
.sweep{
  position:fixed;left:0;right:0;top:0;height:1px;z-index:2;pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
  animation: sweep 6s linear infinite;
  filter:drop-shadow(0 0 6px var(--accent));
}
@keyframes sweep{
  0%{transform:translateY(0vh)}
  100%{transform:translateY(100vh)}
}

/* ── corner brackets that the GITS HUD always uses ── */
.bracket{position:fixed;width:34px;height:34px;border:1px solid var(--accent);z-index:3}
.bracket.tl{top:14px;left:14px;border-right:none;border-bottom:none}
.bracket.tr{top:14px;right:14px;border-left:none;border-bottom:none}
.bracket.bl{bottom:14px;left:14px;border-right:none;border-top:none}
.bracket.br{bottom:14px;right:14px;border-left:none;border-top:none}

.shell{position:relative;z-index:4;max-width:1280px;margin:0 auto;padding:36px 28px 80px}

/* ── header with rotating section-9 mark ── */
header.hud{display:flex;align-items:center;gap:18px;margin-bottom:22px}
.mark{
  width:64px;height:64px;position:relative;flex:0 0 64px;
  filter:drop-shadow(0 0 6px rgba(122,252,214,.5));
}
.mark .ring{
  position:absolute;inset:0;border:1px solid var(--accent);border-radius:50%;
  animation:spin 14s linear infinite;
}
.mark .ring.inner{inset:8px;border-style:dashed;animation-duration:9s;animation-direction:reverse}
.mark .ring.core{inset:18px;border-color:var(--accent-2);
  animation-duration:6s}
.mark::after{content:"K9";position:absolute;inset:0;display:grid;place-items:center;
  font-family:"VT323",monospace;font-size:1.6rem;color:var(--accent-2);
  letter-spacing:.05em}
@keyframes spin{to{transform:rotate(360deg)}}

.titles h1{
  margin:0;font-family:"VT323","Share Tech Mono",monospace;
  font-size:2.6rem;letter-spacing:.18em;color:var(--accent);
  text-shadow:0 0 12px rgba(122,252,214,.35);
}
.titles h2{
  margin:0;font-size:.78rem;letter-spacing:.4em;color:var(--accent-2);
  text-transform:uppercase
}
.tag-pill{
  margin-left:auto;display:inline-flex;align-items:center;gap:8px;
  border:1px solid var(--accent-2);padding:6px 12px;color:var(--accent-2);
  font-size:.72rem;letter-spacing:.32em;
}
.tag-pill .dot{width:8px;height:8px;background:var(--accent-2);
  border-radius:50%;box-shadow:0 0 8px var(--accent-2);
  animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.3}}

/* ── grid layout ── */
.grid{display:grid;grid-template-columns:1.05fr .95fr;gap:24px}
@media (max-width:1000px){.grid{grid-template-columns:1fr}}
.panel{
  background:var(--panel);border:1px solid var(--rule);
  position:relative;box-shadow:var(--shadow);
}
.panel::before{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(180deg,rgba(122,252,214,.04),transparent 30%);
}
.panel header{
  display:flex;align-items:center;gap:10px;
  padding:10px 14px;border-bottom:1px solid var(--rule);
  font-size:.72rem;letter-spacing:.3em;color:var(--accent-2);text-transform:uppercase;
  background:linear-gradient(90deg,rgba(255,179,71,.07),transparent)
}
.panel header .id{margin-left:auto;color:var(--dim);font-size:.65rem}
.panel .body{padding:16px}

/* ── form fields ── */
label{display:block;font-size:.7rem;letter-spacing:.22em;color:var(--dim);
  text-transform:uppercase;margin:14px 0 6px}
label:first-of-type{margin-top:0}
input[type=text],input[type=number],select,textarea{
  width:100%;background:#000;color:var(--accent);
  border:1px solid var(--rule);padding:10px 12px;
  font-family:inherit;font-size:.95rem;letter-spacing:.04em;
}
input:focus,select:focus,textarea:focus{outline:1px solid var(--accent);
  box-shadow:0 0 0 1px rgba(122,252,214,.4),0 0 14px rgba(122,252,214,.18) inset}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.toggle{display:flex;align-items:center;gap:10px;font-size:.78rem;
  color:var(--ink);margin-top:6px;cursor:pointer;user-select:none}
.toggle input{appearance:none;width:36px;height:18px;background:#000;
  border:1px solid var(--rule);position:relative;cursor:pointer;flex:0 0 36px}
.toggle input::after{content:"";position:absolute;left:1px;top:1px;width:14px;height:14px;
  background:var(--dim);transition:left .15s, background .15s}
.toggle input:checked{border-color:var(--accent)}
.toggle input:checked::after{left:19px;background:var(--accent);
  box-shadow:0 0 6px var(--accent)}

/* ── buttons ── */
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
button{
  background:transparent;color:var(--accent);
  border:1px solid var(--accent);padding:9px 14px;
  font-family:inherit;font-size:.78rem;letter-spacing:.22em;
  text-transform:uppercase;cursor:pointer;transition:all .12s;
  position:relative;overflow:hidden;
}
button::before{content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(122,252,214,.18),transparent);
  transform:translateX(-110%);transition:transform .35s}
button:hover::before{transform:translateX(110%)}
button:hover{background:rgba(122,252,214,.08);box-shadow:0 0 12px rgba(122,252,214,.25)}
button:disabled{opacity:.35;cursor:not-allowed}
button.warn{color:var(--warn);border-color:var(--warn)}
button.warn:hover{background:rgba(255,85,119,.1)}
button.amber{color:var(--accent-2);border-color:var(--accent-2)}
button.amber:hover{background:rgba(255,179,71,.1)}

/* ── status panel ── */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.kpi{border:1px solid var(--rule);padding:10px 12px;background:#000}
.kpi b{display:block;font-size:1.4rem;color:var(--accent);font-family:"VT323",monospace}
.kpi span{font-size:.62rem;letter-spacing:.24em;color:var(--dim);text-transform:uppercase}
.bar{height:6px;background:#000;border:1px solid var(--rule);position:relative;
  overflow:hidden;margin:14px 0 6px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));
  width:0;transition:width .3s;box-shadow:0 0 8px var(--accent)}
.url-line{font-size:.78rem;color:var(--dim);word-break:break-all;min-height:1.2em}
.status-led{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--dim);margin-right:6px}
.status-led.live{background:var(--accent);box-shadow:0 0 8px var(--accent);
  animation:pulse 1.2s ease-in-out infinite}
.status-led.paused{background:var(--accent-2);box-shadow:0 0 8px var(--accent-2)}
.status-led.err{background:var(--warn);box-shadow:0 0 8px var(--warn)}

/* ── log ── */
.log{
  background:#000;border:1px solid var(--rule);height:260px;overflow:auto;
  padding:8px 10px;font-size:.78rem;line-height:1.4;color:#9bd6c8;
  font-family:"Share Tech Mono",monospace;
}
.log .l-warn{color:var(--accent-2)}
.log .l-err{color:var(--warn)}
.log .l-info{color:#b8e6dc}

/* ── projects list ── */
.proj{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;
  padding:10px;border:1px solid var(--rule);background:#000;margin-bottom:8px}
.proj b{color:var(--accent);font-weight:600;letter-spacing:.06em}
.proj small{display:block;color:var(--dim);font-size:.7rem}
.proj .actions{display:flex;gap:6px}
.proj .actions button{padding:6px 10px;font-size:.66rem}
.empty{color:var(--dim);font-size:.85rem;padding:14px;text-align:center;
  border:1px dashed var(--rule)}

/* ── notice / errors ── */
.notice{padding:10px 12px;border:1px solid var(--accent-2);color:var(--accent-2);
  background:rgba(255,179,71,.07);font-size:.82rem;margin-bottom:14px;display:none}
.notice.err{border-color:var(--warn);color:var(--warn);background:rgba(255,85,119,.07)}
.notice.show{display:block;animation:fadein .25s}
@keyframes fadein{from{opacity:0;transform:translateY(-2px)}to{opacity:1}}

/* ── tail glyph ── */
.glyph{position:fixed;right:18px;bottom:60px;z-index:5;font-family:"VT323",monospace;
  font-size:.7rem;color:var(--accent);letter-spacing:.3em;opacity:.6;
  writing-mode:vertical-rl;transform:rotate(180deg)}

/* fine elements */
hr.divider{border:none;border-top:1px dashed var(--rule);margin:18px 0}
.foot-strip{margin-top:30px;border-top:1px solid var(--rule);
  padding-top:10px;display:flex;justify-content:space-between;
  font-size:.7rem;letter-spacing:.24em;color:var(--dim);text-transform:uppercase}
a.subtle{color:var(--accent);text-decoration:none;border-bottom:1px dashed var(--accent)}
</style>
</head>
<body>

<div class="sweep"></div>
<div class="bracket tl"></div><div class="bracket tr"></div>
<div class="bracket bl"></div><div class="bracket br"></div>
<div class="glyph">SECTION-9 // ARCHIVAL UNIT // K9</div>

<div class="shell">
  <header class="hud">
    <div class="mark"><div class="ring"></div><div class="ring inner"></div><div class="ring core"></div></div>
    <div class="titles">
      <h1 id="brand-h1">{{brand}}</h1>
      <h2 id="brand-h2">{{heading}} // OFFLINE WIKI BACKUPPER</h2>
    </div>
    <div class="tag-pill"><span class="dot"></span><span id="hud-tag">STANDBY</span></div>
  </header>

  <div id="notice" class="notice"></div>

  <div class="grid">

    <!-- LEFT: NEW BACKUP -->
    <section class="panel">
      <header><span>► NEW ARCHIVAL TASK</span><span class="id">FRM-001</span></header>
      <div class="body">

        <label>SOURCE URL</label>
        <input id="f-url" type="text" placeholder="https://kiwifarms.st/wiki/Ghost_in_the_Shell" value="https://kiwifarms.st">

        <label>PROJECT NAME (auto if blank)</label>
        <input id="f-name" type="text" placeholder="ghost_in_the_shell">

        <label>PATH PREFIX (limits crawl scope)</label>
        <input id="f-prefix" type="text" placeholder="/wiki/  (recommended for wiki sites)">

        <div class="row">
          <div>
            <label>MAX DEPTH</label>
            <input id="f-depth" type="number" min="0" max="10" value="3">
          </div>
          <div>
            <label>MAX PAGES</label>
            <input id="f-pages" type="number" min="1" max="20000" value="500">
          </div>
        </div>

        <div class="row">
          <div>
            <label>SLEEP MIN (s)</label>
            <input id="f-dmin" type="number" step="0.5" min="0" value="2.0">
          </div>
          <div>
            <label>SLEEP MAX (s)</label>
            <input id="f-dmax" type="number" step="0.5" min="0" value="5.0">
          </div>
        </div>

        <hr class="divider">

        <label class="toggle"><input id="f-blobs" type="checkbox" checked>
          DOWNLOAD IMAGES &amp; MEDIA AS BLOBS</label>
        <label class="toggle"><input id="f-video" type="checkbox" checked>
          INCLUDE LOCAL VIDEO</label>
        <label class="toggle"><input id="f-same" type="checkbox" checked>
          SAME-SITE ONLY</label>
        <label class="toggle"><input id="f-robots" type="checkbox">
          RESPECT ROBOTS.TXT</label>

        <hr class="divider">

        <label>BRANDING / ARCHIVE HEADING</label>
        <div class="row">
          <input id="f-brand" type="text" placeholder="KiwiEater Archive">
          <input id="f-heading" type="text" placeholder="OFFLINE ARCHIVE">
        </div>

        <label class="toggle" style="margin-top:12px">
          <input id="f-network" type="checkbox">
          ENABLE NETWORK ACCESS (LAN)
        </label>

        <div class="controls">
          <button id="btn-start">▶ Begin Archival</button>
          <button id="btn-pause" class="amber" disabled>⏸ Pause</button>
          <button id="btn-stop" class="warn" disabled>■ Stop</button>
          <button id="btn-save-cfg">Save Config</button>
        </div>
      </div>
    </section>

    <!-- RIGHT: STATUS + LOG -->
    <section class="panel">
      <header><span>► LIVE TELEMETRY</span><span class="id">TEL-007</span></header>
      <div class="body">
        <div class="kpis">
          <div class="kpi"><b id="k-done">0</b><span>Done</span></div>
          <div class="kpi"><b id="k-pending">0</b><span>Queued</span></div>
          <div class="kpi"><b id="k-fail">0</b><span>Failed</span></div>
          <div class="kpi"><b id="k-blob">0</b><span>Blobs</span></div>
        </div>
        <div class="bar"><i id="prog"></i></div>
        <div class="url-line">
          <span class="status-led" id="led"></span>
          <span id="status-text">Idle</span> — <span id="cur-url">no current target</span>
        </div>
        <div style="margin-top:6px;font-size:.7rem;color:var(--dim)">
          last HTTP: <span id="last-status">—</span> • rate: <span id="rate">0</span>/min
          • project: <span id="cur-proj">—</span>
        </div>
        <div class="log" id="log"></div>
      </div>
    </section>

    <!-- PROJECTS -->
    <section class="panel" style="grid-column:1/-1">
      <header><span>► EXISTING ARCHIVES</span><span class="id">DAT-002</span></header>
      <div class="body">
        <div id="projects"></div>
      </div>
    </section>
  </div>

  <div class="foot-strip">
    <span>SECTION 9 // K9 // ARCHIVAL DIVISION</span>
    <span id="foot-time">—</span>
  </div>
</div>

<script>
const $=s=>document.querySelector(s);
const notice = (msg, isErr=false) => {
  const n = $("#notice");
  n.textContent = msg;
  n.className = "notice show" + (isErr ? " err" : "");
  clearTimeout(notice._t);
  notice._t = setTimeout(()=>{ n.classList.remove("show"); }, 6000);
};

async function api(path, opts={}){
  const r = await fetch(path, Object.assign({headers:{"Content-Type":"application/json"}}, opts));
  let data; try{ data = await r.json(); }catch(e){ data={ok:false,error:"bad json"}; }
  return {ok:r.ok && (data.ok!==false), status:r.status, data};
}

function buildSettings(){
  return {
    start_url: $("#f-url").value.trim(),
    project_name: $("#f-name").value.trim() || null,
    path_prefix: $("#f-prefix").value.trim(),
    max_depth: parseInt($("#f-depth").value || "3"),
    max_pages: parseInt($("#f-pages").value || "500"),
    delay_min: parseFloat($("#f-dmin").value || "2"),
    delay_max: parseFloat($("#f-dmax").value || "5"),
    download_blobs: $("#f-blobs").checked,
    include_videos: $("#f-video").checked,
    same_site_only: $("#f-same").checked,
    respect_robots: $("#f-robots").checked
  };
}

$("#btn-start").addEventListener("click", async ()=>{
  if (!$("#f-url").value.trim()){ notice("Source URL required.", true); return; }
  const s = buildSettings();
  const {ok, data} = await api("/api/start", {method:"POST", body: JSON.stringify(s)});
  if (!ok){ notice(data.error || "start failed", true); return; }
  notice("Archival initiated → "+data.project);
});
$("#btn-stop").addEventListener("click", async ()=>{
  await api("/api/stop", {method:"POST"});
  notice("Stop signal sent.");
});
$("#btn-pause").addEventListener("click", async (e)=>{
  const paused = e.target.dataset.paused !== "1";
  await api("/api/pause", {method:"POST", body: JSON.stringify({paused})});
  e.target.dataset.paused = paused ? "1" : "0";
  e.target.textContent = paused ? "▶ Resume" : "⏸ Pause";
});

$("#btn-save-cfg").addEventListener("click", async ()=>{
  const body = {
    branding: $("#f-brand").value.trim() || "KiwiEater Archive System",
    archive_heading: $("#f-heading").value.trim() || "OFFLINE ARCHIVE",
    network_access: $("#f-network").checked,
    default_delay_min: parseFloat($("#f-dmin").value || "2"),
    default_delay_max: parseFloat($("#f-dmax").value || "5")
  };
  const {ok, data} = await api("/api/config", {method:"POST", body: JSON.stringify(body)});
  if (!ok){ notice("config save failed", true); return; }
  $("#brand-h1").textContent = data.branding;
  $("#brand-h2").textContent = data.archive_heading + " // OFFLINE WIKI BACKUPPER";
  notice("Config saved.");
});

async function loadConfig(){
  const r = await fetch("/api/config"); const c = await r.json();
  $("#f-brand").value = c.branding || "";
  $("#f-heading").value = c.archive_heading || "";
  $("#f-network").checked = !!c.network_access;
  $("#f-dmin").value = c.default_delay_min;
  $("#f-dmax").value = c.default_delay_max;
}

async function loadProjects(){
  const r = await fetch("/api/projects"); const list = await r.json();
  const root = $("#projects");
  if (!list.length){
    root.innerHTML = '<div class="empty">No archives yet. Begin one on the left.</div>';
    return;
  }
  root.innerHTML = "";
  for (const p of list){
    const m = p.manifest || {};
    const el = document.createElement("div");
    el.className = "proj";
    el.innerHTML = `
      <div>
        <b>${p.name}</b>
        <small>${m.source||"(unknown source)"} • ${p.stats.pages} pages • ${p.stats.queue} queued • ${p.stats.failed} failed</small>
      </div>
      <div class="actions">
        <button data-act="open">Open</button>
        <button data-act="resume" class="amber">Resume</button>
        <button data-act="delete" class="warn">Delete</button>
      </div>`;
    el.querySelector("[data-act=open]").onclick = ()=>{
      window.open(`/archive/${encodeURIComponent(p.name)}/`, "_blank");
    };
    el.querySelector("[data-act=resume]").onclick = async ()=>{
      const {ok,data} = await api("/api/resume", {method:"POST",
        body: JSON.stringify({project_name: p.name})});
      if (!ok){ notice(data.error||"resume failed", true); return; }
      notice("Resumed: "+p.name);
    };
    el.querySelector("[data-act=delete]").onclick = async ()=>{
      if (!confirm("Delete archive '"+p.name+"'? This removes all saved pages and blobs.")) return;
      const {ok,data} = await api("/api/delete", {method:"POST",
        body: JSON.stringify({project_name: p.name})});
      if (!ok){ notice(data.error||"delete failed", true); return; }
      notice("Deleted: "+p.name);
      loadProjects();
    };
    root.appendChild(el);
  }
}

let lastLogProj = null;
async function tick(){
  try{
    const r = await fetch("/api/status"); const s = await r.json();
    const running = s.running;
    const st = s.state || {};
    $("#btn-start").disabled = running;
    $("#btn-stop").disabled = !running;
    $("#btn-pause").disabled = !running;
    $("#led").className = "status-led " + (running ? (st.paused?"paused":"live") : (st.last_error?"err":""));
    $("#status-text").textContent =
      !running ? "Idle" : (st.paused ? "Paused" : "Crawling");
    $("#hud-tag").textContent = !running ? "STANDBY" : (st.paused?"PAUSED":"ACTIVE");
    $("#cur-url").textContent = st.current_url || "no current target";
    $("#k-done").textContent = st.pages_done || 0;
    $("#k-pending").textContent = st.pages_pending || 0;
    $("#k-fail").textContent = st.pages_failed || 0;
    $("#k-blob").textContent = st.blobs_done || 0;
    $("#last-status").textContent = st.last_status || "—";
    $("#rate").textContent = st.rate || 0;
    $("#cur-proj").textContent = s.project || "—";
    const total = (st.pages_done||0) + (st.pages_pending||0);
    const pct = total ? Math.min(100, Math.round((st.pages_done/total)*100)) : 0;
    $("#prog").style.width = pct + "%";

    if (s.project && s.project !== lastLogProj){ lastLogProj = s.project; }
    if (s.project){
      const lr = await fetch("/api/log/"+encodeURIComponent(s.project));
      const lj = await lr.json();
      const log = $("#log");
      log.innerHTML = (lj.lines||[]).map(line=>{
        let cls="l-info";
        if (/\[ERROR\]/.test(line)) cls="l-err";
        else if (/\[WARNING\]/.test(line)) cls="l-warn";
        return `<div class="${cls}">${line.replace(/[<>&]/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))}</div>`;
      }).join("");
      log.scrollTop = log.scrollHeight;
    }
  }catch(e){/* ignore transient */}
  $("#foot-time").textContent = new Date().toISOString().replace("T"," ").slice(0,19)+" UTC";
}

loadConfig().then(loadProjects);
setInterval(tick, 1500);
setInterval(loadProjects, 8000);
tick();
</script>
</body></html>
"""


# ───────────────────────────── Main ─────────────────────────────
def main():
    cfg = load_config()
    host = cfg["network_host"] if cfg.get("network_access") else cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 7743))
    url = f"http://{('localhost' if host=='127.0.0.1' else host)}:{port}/"
    print("\n" + "═" * 60)
    print(f"  KiwiEater  →  {url}")
    if cfg.get("network_access"):
        print(f"  LAN access enabled. Other devices on the network can reach")
        print(f"  this server at http://<this-machine-ip>:{port}/")
    print("═" * 60 + "\n")
    try:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
