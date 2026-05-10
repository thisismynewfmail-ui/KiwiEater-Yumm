#!/usr/bin/env python3
"""
KiwiEater - Ghost in the Shell S.A.C. 2002 Themed Wiki Archiver
Novel solutions for Kiwiflare/Captcha bypass using multiple strategies:
1. Browser emulation with Selenium + undetected-chromedriver patterns
2. Challenge page detection and automated solving via JavaScript execution
3. Session warming with progressive request patterns
4. Cookie persistence and header randomization
5. Request timing humanization
6. Multiple fallback strategies when challenges detected
"""

import os
import sys
import json
import time
import random
import hashlib
import base64
import logging
import threading
import socket
import re
from datetime import datetime
from urllib.parse import urlparse, urljoin, quote
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any

# Third-party imports
try:
    from flask import Flask, render_template_string, jsonify, request, send_from_directory
    from flask_socketio import SocketIO, emit
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from webdriver_manager.chrome import ChromeDriverManager
    from PIL import Image
    import io
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)

# Configuration paths
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"
ARCHIVES_DIR = BASE_DIR / "archives"
SESSIONS_DIR = BASE_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
for d in [ARCHIVES_DIR, SESSIONS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Logging setup
def setup_logging(session_id: str) -> logging.Logger:
    logger = logging.getLogger(f"KiwiEater_{session_id}")
    logger.setLevel(logging.INFO)
    
    # File handler
    log_file = LOGS_DIR / f"{session_id}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

# User Agent rotation list
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Common headers that mimic real browsers
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class ChallengeSolver:
    """
    Novel solution for Kiwiflare/Captcha challenges.
    Uses multiple strategies to detect and bypass challenge pages.
    """
    
    CHALLENGE_INDICATORS = [
        "checking your browser",
        "ddos-guard",
        "cloudflare",
        "challenge-platform",
        "just a moment",
        "enable javascript",
        "captcha",
        "kiwiflare",
        "security check",
        "verifying you are human",
    ]
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.driver = None
        self.browser_initialized = False
        
    def init_browser(self) -> bool:
        """Initialize stealth browser for challenge solving."""
        if self.browser_initialized:
            return True
            
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--user-agent=" + random.choice(USER_AGENTS))
            
            # Stealth options
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Execute CDP commands for additional stealth
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                '''
            })
            
            self.browser_initialized = True
            self.logger.info("Stealth browser initialized for challenge solving")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return False
    
    def is_challenge_page(self, html: str, status_code: int = 200) -> bool:
        """Detect if response is a challenge/captcha page."""
        html_lower = html.lower()
        
        # Check for challenge indicators
        for indicator in self.CHALLENGE_INDICATORS:
            if indicator in html_lower:
                return True
        
        # Check for very short responses (often indicates block)
        if len(html) < 500 and status_code == 200:
            return True
        
        # Check for meta refresh or JS redirect patterns common in challenges
        if '<meta http-equiv="refresh"' in html_lower:
            return True
        
        # Check for common challenge page titles
        soup = BeautifulSoup(html, 'lxml')
        if soup.title:
            title = soup.title.get_text().lower()
            if any(ind in title for ind in self.CHALLENGE_INDICATORS):
                return True
        
        return False
    
    def solve_challenge(self, url: str, session: requests.Session) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Attempt to solve challenge page using browser automation.
        Returns: (success, html_content, cookies)
        """
        if not self.init_browser():
            return False, None, None
        
        try:
            self.logger.info(f"Attempting browser-based challenge solve for: {url}")
            
            # Navigate to URL
            self.driver.get(url)
            
            # Wait for potential challenge completion (up to 30 seconds)
            max_wait = 30
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                # Check if we've passed the challenge
                current_html = self.driver.page_source
                
                if not self.is_challenge_page(current_html):
                    self.logger.info("Challenge solved successfully!")
                    
                    # Get cookies for session reuse
                    cookies = {}
                    for cookie in self.driver.get_cookies():
                        cookies[cookie['name']] = cookie['value']
                    
                    # Update requests session with cookies
                    for name, value in cookies.items():
                        session.cookies.set(name, value, domain=urlparse(url).netloc)
                    
                    return True, current_html, cookies
                
                # Small wait before checking again
                time.sleep(1)
                
                # Try clicking if there's a visible button
                try:
                    verify_button = self.driver.find_element(By.CSS_SELECTOR, 
                        'button[type="submit"], input[type="submit"], .verify-button')
                    if verify_button.is_displayed():
                        verify_button.click()
                        time.sleep(2)
                except:
                    pass
            
            self.logger.warning("Challenge solve timeout - challenge may be too complex")
            return False, None, None
            
        except Exception as e:
            self.logger.error(f"Error during challenge solving: {e}")
            return False, None, None
    
    def close(self):
        """Close browser instance."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.browser_initialized = False


class KiwiEaterCrawler:
    """Main crawler class with anti-detection and challenge handling."""
    
    def __init__(self, config: dict, session_id: str, socketio=None):
        self.config = config
        self.session_id = session_id
        self.socketio = socketio
        self.logger = setup_logging(session_id)
        
        # Initialize challenge solver
        self.challenge_solver = ChallengeSolver(self.logger)
        
        # Crawl state
        self.base_url = ""
        self.domain = ""
        self.archive_name = ""
        self.visited_urls: Set[str] = set()
        self.queue: List[Tuple[str, int]] = []  # (url, depth)
        self.downloaded_assets: Dict[str, str] = {}  # url -> local path
        self.pages_data: Dict[str, dict] = {}  # url -> page info
        self.session_state = "idle"
        self.should_stop = False
        self.progress = 0
        self.total_estimated = 0
        
        # Requests session with persistence
        self.session = requests.Session()
        self._setup_session()
        
        # Load or create session state
        self.session_file = SESSIONS_DIR / f"{session_id}.json"
        self.load_session_state()
    
    def _setup_session(self):
        """Configure requests session with anti-detection measures."""
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
        
        # Enable cookie persistence
        if self.config.get("anti_detection", {}).get("cookie_persistence", True):
            cookie_file = SESSIONS_DIR / f"{self.session_id}_cookies.json"
            if cookie_file.exists():
                try:
                    with open(cookie_file, 'r') as f:
                        cookies = json.load(f)
                    for name, value in cookies.items():
                        self.session.cookies.set(name, value)
                    self.logger.info("Loaded persisted cookies")
                except:
                    pass
    
    def _save_cookies(self):
        """Save cookies for session persistence."""
        cookie_file = SESSIONS_DIR / f"{self.session_id}_cookies.json"
        cookies = {c.name: c.value for c in self.session.cookies}
        try:
            with open(cookie_file, 'w') as f:
                json.dump(cookies, f)
        except:
            pass
    
    def _human_delay(self):
        """Add human-like delay between requests."""
        crawl_settings = self.config.get("crawl_settings", {})
        min_delay = crawl_settings.get("request_delay_min", 2.0)
        max_delay = crawl_settings.get("request_delay_max", 5.0)
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)
    
    def _rotate_user_agent(self):
        """Rotate user agent to avoid fingerprinting."""
        if self.config.get("crawl_settings", {}).get("user_agent_rotation", True):
            self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent tracking."""
        url = url.strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        parsed = urlparse(url)
        # Remove fragment
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        
        # Remove trailing slash for consistency (except root)
        if normalized.endswith('/') and len(normalized) > 1:
            normalized = normalized.rstrip('/')
        
        return normalized
    
    def _is_internal_url(self, url: str) -> bool:
        """Check if URL belongs to the same domain/subdomain."""
        parsed = urlparse(url)
        base_parsed = urlparse(self.base_url)
        
        # Allow same domain and subdomains
        return parsed.netloc.endswith(base_parsed.netloc) or \
               base_parsed.netloc.endswith(parsed.netloc)
    
    def _extract_links(self, html: str, current_url: str) -> List[str]:
        """Extract internal links from HTML."""
        soup = BeautifulSoup(html, 'lxml')
        links = []
        
        for tag in soup.find_all(['a', 'link']):
            href = tag.get('href') or tag.get('src')
            if not href:
                continue
            
            # Skip non-http links
            if href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue
            
            # Resolve relative URLs
            absolute_url = urljoin(current_url, href)
            absolute_url = self._normalize_url(absolute_url)
            
            # Only include internal URLs
            if self._is_internal_url(absolute_url):
                links.append(absolute_url)
        
        return links
    
    def _fetch_with_fallback(self, url: str, depth: int) -> Tuple[Optional[str], bool]:
        """
        Fetch URL with multiple fallback strategies for challenge bypass.
        Returns: (html_content, is_challenge)
        """
        max_retries = self.config.get("crawl_settings", {}).get("max_retries", 5)
        timeout = self.config.get("crawl_settings", {}).get("timeout_seconds", 30)
        
        for attempt in range(max_retries):
            try:
                # Rotate user agent each attempt
                self._rotate_user_agent()
                
                # Human-like delay before request
                if attempt > 0:
                    self._human_delay()
                
                self.logger.debug(f"Fetching {url} (attempt {attempt + 1}/{max_retries})")
                
                response = self.session.get(url, timeout=timeout, allow_redirects=True)
                
                # Check for obvious blocks
                if response.status_code == 403:
                    self.logger.warning(f"403 Forbidden on {url}, attempting challenge solve")
                    success, html, cookies = self.challenge_solver.solve_challenge(url, self.session)
                    if success and html:
                        self._save_cookies()
                        return html, False
                    time.sleep(5 * (attempt + 1))  # Exponential backoff
                    continue
                
                if response.status_code == 429:
                    self.logger.warning(f"429 Rate limited on {url}, backing off")
                    time.sleep(10 * (attempt + 1))
                    continue
                
                if response.status_code >= 500:
                    self.logger.warning(f"Server error {response.status_code} on {url}")
                    time.sleep(5)
                    continue
                
                # Check for challenge page
                if self.challenge_solver.is_challenge_page(response.text, response.status_code):
                    self.logger.warning(f"Challenge page detected on {url}, attempting solve")
                    
                    # Try browser-based solve
                    success, html, cookies = self.challenge_solver.solve_challenge(url, self.session)
                    if success and html:
                        self._save_cookies()
                        return html, False
                    
                    # If solve failed, back off and requeue
                    self.logger.info(f"Challenge solve failed, will retry later")
                    if attempt < max_retries - 1:
                        time.sleep(15 * (attempt + 1))
                        continue
                    else:
                        return None, True  # Mark as challenge that couldn't be solved
                
                return response.text, False
                
            except requests.exceptions.Timeout:
                self.logger.warning(f"Timeout fetching {url}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                    
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request error on {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
        
        return None, False
    
    def _warm_up_session(self, url: str):
        """Warm up session with progressive requests to establish trust."""
        self.logger.info(f"Warming up session: {url}")
        
        # Make a few preliminary requests to establish session
        warmup_paths = ['/', '/robots.txt']
        for path in warmup_paths:
            try:
                warmup_url = urljoin(url, path)
                self.session.head(warmup_url, timeout=5)
                time.sleep(1)
            except:
                pass
        
        # Initial fetch with extra delay
        self._human_delay()
    
    def _download_asset(self, url: str, asset_type: str = 'image') -> Optional[str]:
        """Download asset and save as blob file."""
        if url in self.downloaded_assets:
            return self.downloaded_assets[url]
        
        try:
            # Skip external assets
            if not self._is_internal_url(url):
                return None
            
            self.logger.debug(f"Downloading asset: {url}")
            
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                return None
            
            # Generate unique filename
            content_hash = hashlib.md5(response.content).hexdigest()[:12]
            ext = Path(urlparse(url).path).suffix or '.bin'
            filename = f"{asset_type}_{content_hash}{ext}"
            
            # Save to archive
            asset_dir = ARCHIVES_DIR / self.archive_name / "assets" / asset_type
            asset_dir.mkdir(parents=True, exist_ok=True)
            asset_path = asset_dir / filename
            
            # Compress images if configured
            if asset_type == 'image' and self.config.get("storage", {}).get("compress_images", True):
                try:
                    img = Image.open(io.BytesIO(response.content))
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img.save(asset_path, 'PNG', optimize=True)
                    else:
                        img.save(asset_path, 'JPEG', quality=85, optimize=True)
                except:
                    # Fallback to original
                    with open(asset_path, 'wb') as f:
                        f.write(response.content)
            else:
                with open(asset_path, 'wb') as f:
                    f.write(response.content)
            
            # Store relative path for rewriting
            relative_path = f"../assets/{asset_type}/{filename}"
            self.downloaded_assets[url] = relative_path
            
            return relative_path
            
        except Exception as e:
            self.logger.error(f"Failed to download asset {url}: {e}")
            return None
    
    def _process_html(self, html: str, url: str) -> str:
        """Process HTML: download assets, rewrite links, clean content."""
        soup = BeautifulSoup(html, 'lxml')
        
        # Process images
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src:
                absolute_src = urljoin(url, src)
                local_path = self._download_asset(absolute_src, 'image')
                if local_path:
                    img['src'] = local_path
                else:
                    # Keep original for external or failed downloads
                    img['src'] = absolute_src
        
        # Process videos
        for video in soup.find_all('video'):
            if self.config.get("storage", {}).get("save_videos", True):
                src = video.get('src')
                if src:
                    absolute_src = urljoin(url, src)
                    local_path = self._download_asset(absolute_src, 'video')
                    if local_path:
                        video['src'] = local_path
        
        for source in soup.find_all('source'):
            src = source.get('src')
            if src:
                absolute_src = urljoin(url, src)
                local_path = self._download_asset(absolute_src, 'video')
                if local_path:
                    source['src'] = local_path
        
        # Process CSS files
        for link in soup.find_all('link', rel='stylesheet'):
            href = link.get('href')
            if href:
                absolute_href = urljoin(url, href)
                local_path = self._download_asset(absolute_href, 'css')
                if local_path:
                    link['href'] = local_path
        
        # Rewrite internal links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith(('http://', 'https://')):
                absolute_href = self._normalize_url(href)
                if self._is_internal_url(absolute_href):
                    # Convert to relative path
                    target_parsed = urlparse(absolute_href)
                    current_parsed = urlparse(url)
                    
                    # Simple relative path generation
                    if target_parsed.netloc == current_parsed.netloc:
                        target_path = target_parsed.path.lstrip('/')
                        if target_path:
                            # Create relative link
                            depth = current_parsed.path.count('/') 
                            relative = '../' * depth + target_path
                            a['href'] = relative
                            a['data-original'] = href  # Preserve original for reference
            elif href.startswith('/'):
                # Absolute path on same domain
                absolute_href = self._normalize_url(urljoin(url, href))
                if self._is_internal_url(absolute_href):
                    target_path = absolute_href.replace(self.base_url, '').lstrip('/')
                    depth = urlparse(url).path.count('/')
                    relative = '../' * depth + target_path
                    a['href'] = relative
        
        # Add archive branding
        branding = self.config.get("branding", {})
        heading = branding.get("heading", "ARCHIVE")
        subheading = branding.get("subheading", "")
        
        # Inject archive header
        header_html = f'''
        <div class="archive-header" style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #00ff41; padding: 15px; margin-bottom: 20px; border: 1px solid #00ff41; font-family: monospace;">
            <h2 style="margin: 0; font-size: 1.5em;">⚡ {heading}</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 0.9em;">{subheading} | Archived: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p style="margin: 5px 0 0 0; font-size: 0.8em;">Original: <a href="{url}" style="color: #00ff41;">{url}</a></p>
        </div>
        '''
        
        if soup.body:
            soup.body.insert(0, BeautifulSoup(header_html, 'lxml'))
        
        return str(soup)
    
    def _save_page(self, url: str, html: str):
        """Save processed page to archive."""
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')
        
        # Handle index pages
        if not path or path.endswith('/'):
            path = path + 'index.html' if path else 'index.html'
        elif not path.endswith('.html'):
            path = path + '/index.html'
        
        # Create directory structure
        page_dir = ARCHIVES_DIR / self.archive_name / path
        page_dir.parent.mkdir(parents=True, exist_ok=True)
        
        # Save HTML
        with open(page_dir, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self.logger.info(f"Saved: {path}")
    
    def _build_index(self):
        """Build navigation index page."""
        branding = self.config.get("branding", {})
        
        index_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{branding.get("heading", "Archive")} - Index</title>
    <style>
        :root {{
            --primary: #00ff41;
            --secondary: #0a192f;
            --accent: #64ffda;
            --bg: #020c1b;
        }}
        body {{
            background: var(--bg);
            color: var(--primary);
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            border-bottom: 2px solid var(--primary);
            padding-bottom: 10px;
        }}
        .nav-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .nav-item {{
            background: rgba(0, 255, 65, 0.1);
            border: 1px solid var(--primary);
            padding: 15px;
            transition: all 0.3s ease;
        }}
        .nav-item:hover {{
            background: rgba(0, 255, 65, 0.2);
            transform: translateX(5px);
        }}
        .nav-item a {{
            color: var(--primary);
            text-decoration: none;
        }}
        .search-box {{
            margin: 20px 0;
        }}
        .search-box input {{
            width: 100%;
            padding: 10px;
            background: var(--secondary);
            border: 1px solid var(--primary);
            color: var(--primary);
            font-family: inherit;
        }}
        .stats {{
            margin-top: 30px;
            padding: 15px;
            background: rgba(0, 255, 65, 0.05);
            border: 1px dashed var(--primary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📁 {branding.get("heading", "Archive")} - Site Index</h1>
        <p>{branding.get("subheading", "")}</p>
        
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search archived pages..." onkeyup="filterPages()">
        </div>
        
        <div class="nav-grid" id="pageGrid">
'''
        
        # Add all crawled pages
        for url, data in sorted(self.pages_data.items()):
            title = data.get('title', 'Untitled')
            path = urlparse(url).path.lstrip('/') or 'index.html'
            if not path.endswith('.html'):
                path = path + '/index.html' if path else 'index.html'
            
            index_html += f'''
            <div class="nav-item" data-title="{title.lower()}" data-url="{url}">
                <a href="{path}">
                    <strong>{title[:50]}{'...' if len(title) > 50 else ''}</strong>
                    <br><small style="opacity: 0.7">{url[:60]}...</small>
                </a>
            </div>
'''
        
        index_html += f'''
        </div>
        
        <div class="stats">
            <h3>Archive Statistics</h3>
            <p>Total Pages: {len(self.pages_data)}</p>
            <p>Total Assets: {len(self.downloaded_assets)}</p>
            <p>Archive Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>
    </div>
    
    <script>
        function filterPages() {{
            const input = document.getElementById('searchInput');
            const filter = input.value.toLowerCase();
            const grid = document.getElementById('pageGrid');
            const items = grid.getElementsByClassName('nav-item');
            
            for (let i = 0; i < items.length; i++) {{
                const title = items[i].getAttribute('data-title');
                const url = items[i].getAttribute('data-url');
                if (title.includes(filter) || url.toLowerCase().includes(filter)) {{
                    items[i].style.display = '';
                }} else {{
                    items[i].style.display = 'none';
                }}
            }}
        }}
    </script>
</body>
</html>
'''
        
        # Save index
        index_path = ARCHIVES_DIR / self.archive_name / "site_index.html"
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_html)
        
        self.logger.info("Built site index")
    
    def _save_session_state(self):
        """Save current session state for resuming."""
        state = {
            'session_id': self.session_id,
            'base_url': self.base_url,
            'visited_urls': list(self.visited_urls),
            'queue': self.queue,
            'downloaded_assets': self.downloaded_assets,
            'pages_data': self.pages_data,
            'progress': self.progress,
            'timestamp': datetime.now().isoformat(),
            'status': self.session_state
        }
        
        try:
            with open(self.session_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save session state: {e}")
    
    def load_session_state(self):
        """Load previous session state if exists."""
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r') as f:
                    state = json.load(f)
                
                self.base_url = state.get('base_url', '')
                self.visited_urls = set(state.get('visited_urls', []))
                self.queue = state.get('queue', [])
                self.downloaded_assets = state.get('downloaded_assets', {})
                self.pages_data = state.get('pages_data', {})
                self.progress = state.get('progress', 0)
                
                self.logger.info(f"Loaded session state from {self.session_file}")
                return True
            except Exception as e:
                self.logger.error(f"Failed to load session state: {e}")
        
        return False
    
    def start_crawl(self, url: str, resume: bool = False):
        """Start crawling process."""
        self.base_url = self._normalize_url(url)
        self.domain = urlparse(self.base_url).netloc
        
        # Generate archive name from domain
        self.archive_name = re.sub(r'[^a-z0-9]+', '_', self.domain.lower()).strip('_')
        
        # Create archive directory
        archive_dir = ARCHIVES_DIR / self.archive_name
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Starting crawl of {self.base_url}")
        self.logger.info(f"Archive name: {self.archive_name}")
        self.session_state = "running"
        
        # Warm up session
        self._warm_up_session(self.base_url)
        
        # Initialize queue
        if not resume or not self.queue:
            self.queue = [(self.base_url, 0)]
        
        max_depth = self.config.get("crawl_settings", {}).get("max_depth", 3)
        
        # Main crawl loop
        while self.queue and not self.should_stop:
            # Sort queue by depth (BFS)
            self.queue.sort(key=lambda x: x[1])
            
            current_url, depth = self.queue.pop(0)
            
            # Skip if already visited
            if current_url in self.visited_urls:
                continue
            
            # Check depth limit
            if depth > max_depth:
                self.logger.debug(f"Skipping {current_url} - max depth reached")
                continue
            
            self.visited_urls.add(current_url)
            self.progress = len(self.visited_urls)
            
            self.logger.info(f"[{self.progress}] Processing: {current_url} (depth={depth})")
            
            # Emit progress update
            if self.socketio:
                self.socketio.emit('progress', {
                    'url': current_url,
                    'progress': self.progress,
                    'depth': depth,
                    'status': 'processing'
                })
            
            # Fetch page
            html, is_challenge = self._fetch_with_fallback(current_url, depth)
            
            if html is None:
                if is_challenge:
                    # Re-queue challenge pages for later attempts
                    self.queue.append((current_url, depth))
                    self.logger.warning(f"Re-queuing challenge page: {current_url}")
                else:
                    self.logger.error(f"Failed to fetch: {current_url}")
                continue
            
            # Process and save page
            processed_html = self._process_html(html, current_url)
            self._save_page(current_url, processed_html)
            
            # Extract page info
            soup = BeautifulSoup(html, 'lxml')
            title = soup.title.string if soup.title else current_url
            self.pages_data[current_url] = {
                'title': title,
                'url': current_url,
                'depth': depth,
                'timestamp': datetime.now().isoformat()
            }
            
            # Extract and queue new links
            new_links = self._extract_links(html, current_url)
            for link in new_links:
                if link not in self.visited_urls and not any(l[0] == link for l in self.queue):
                    self.queue.append((link, depth + 1))
            
            # Save session state periodically
            if self.progress % 10 == 0:
                self._save_session_state()
                self._save_cookies()
            
            # Human delay
            self._human_delay()
        
        # Final save
        self._save_session_state()
        self._save_cookies()
        
        if not self.should_stop:
            self.logger.info("Queue empty, finished crawling")
            self.logger.info("Building index, gallery, search...")
            self._build_index()
            self.session_state = "completed"
        else:
            self.logger.info("Crawl stopped by user")
            self.session_state = "paused"
        
        self.logger.info("=== Crawl end ===")
        
        # Close challenge solver
        self.challenge_solver.close()
        
        # Emit completion
        if self.socketio:
            self.socketio.emit('complete', {
                'status': self.session_state,
                'pages': len(self.pages_data),
                'assets': len(self.downloaded_assets),
                'archive_name': self.archive_name
            })
    
    def stop(self):
        """Stop crawling gracefully."""
        self.should_stop = True
        self.logger.info("Stop requested")


# Flask app setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global crawler instance
active_crawler: Optional[KiwiEaterCrawler] = None
current_session_id: Optional[str] = None


def load_config() -> dict:
    """Load configuration from config.json."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}


# HTML Template - Ghost in the Shell S.A.C. 2002 Theme
UI_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KiwiEater - Tachikoma Interface</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
        
        :root {
            --primary: #00ff41;
            --primary-dim: #008f24;
            --secondary: #0a192f;
            --accent: #64ffda;
            --warning: #ffcc00;
            --danger: #ff4444;
            --bg: #020c1b;
            --bg-panel: rgba(10, 25, 47, 0.9);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            background: var(--bg);
            color: var(--primary);
            font-family: 'Share Tech Mono', monospace;
            overflow-x: hidden;
            min-height: 100vh;
            position: relative;
        }
        
        /* Animated background grid */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                linear-gradient(rgba(0, 255, 65, 0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 255, 65, 0.03) 1px, transparent 1px);
            background-size: 20px 20px;
            animation: gridMove 20s linear infinite;
            pointer-events: none;
            z-index: 0;
        }
        
        @keyframes gridMove {
            0% { transform: translateY(0); }
            100% { transform: translateY(20px); }
        }
        
        /* Scanline effect */
        body::after {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: repeating-linear-gradient(
                0deg,
                rgba(0, 0, 0, 0.1) 0px,
                rgba(0, 0, 0, 0.1) 1px,
                transparent 1px,
                transparent 2px
            );
            pointer-events: none;
            z-index: 1000;
            animation: scanline 8s linear infinite;
        }
        
        @keyframes scanline {
            0% { transform: translateY(-100%); }
            100% { transform: translateY(100vh); }
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 1;
        }
        
        /* Header */
        .header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 2px solid var(--primary);
            margin-bottom: 30px;
            position: relative;
        }
        
        .header::before {
            content: '⚡';
            font-size: 3em;
            animation: pulse 2s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.1); }
        }
        
        .header h1 {
            font-size: 2.5em;
            text-transform: uppercase;
            letter-spacing: 4px;
            margin-top: 10px;
            text-shadow: 0 0 10px var(--primary);
        }
        
        .header p {
            color: var(--accent);
            opacity: 0.8;
            margin-top: 10px;
        }
        
        /* Status bar */
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: var(--bg-panel);
            border: 1px solid var(--primary-dim);
            margin-bottom: 20px;
            border-radius: 4px;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: var(--primary-dim);
            animation: blink 1s ease-in-out infinite;
        }
        
        .status-dot.active {
            background: var(--primary);
            box-shadow: 0 0 10px var(--primary);
        }
        
        .status-dot.error {
            background: var(--danger);
            animation: blinkError 0.5s ease-in-out infinite;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        @keyframes blinkError {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        /* Panels */
        .panel {
            background: var(--bg-panel);
            border: 1px solid var(--primary-dim);
            border-radius: 4px;
            padding: 20px;
            margin-bottom: 20px;
            position: relative;
            overflow: hidden;
        }
        
        .panel::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--primary), transparent);
            animation: shimmer 3s ease-in-out infinite;
        }
        
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        
        .panel h2 {
            color: var(--accent);
            margin-bottom: 15px;
            font-size: 1.3em;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        /* Form elements */
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            color: var(--accent);
            font-size: 0.9em;
        }
        
        input[type="text"],
        input[type="number"],
        select {
            width: 100%;
            padding: 12px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--primary-dim);
            color: var(--primary);
            font-family: inherit;
            font-size: 1em;
            border-radius: 4px;
            transition: all 0.3s ease;
        }
        
        input:focus,
        select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 10px rgba(0, 255, 65, 0.3);
        }
        
        /* Buttons */
        .btn {
            padding: 12px 24px;
            background: transparent;
            border: 1px solid var(--primary);
            color: var(--primary);
            font-family: inherit;
            font-size: 1em;
            cursor: pointer;
            border-radius: 4px;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        
        .btn:hover {
            background: var(--primary);
            color: var(--bg);
            box-shadow: 0 0 15px var(--primary);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-danger {
            border-color: var(--danger);
            color: var(--danger);
        }
        
        .btn-danger:hover {
            background: var(--danger);
            color: white;
            box-shadow: 0 0 15px var(--danger);
        }
        
        /* Progress bar */
        .progress-container {
            margin: 20px 0;
        }
        
        .progress-bar {
            height: 20px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--primary-dim);
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary-dim), var(--primary));
            width: 0%;
            transition: width 0.3s ease;
            position: relative;
        }
        
        .progress-fill::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: repeating-linear-gradient(
                90deg,
                transparent,
                transparent 10px,
                rgba(255, 255, 255, 0.1) 10px,
                rgba(255, 255, 255, 0.1) 20px
            );
            animation: progressMove 2s linear infinite;
        }
        
        @keyframes progressMove {
            0% { transform: translateX(0); }
            100% { transform: translateX(20px); }
        }
        
        .progress-text {
            text-align: center;
            margin-top: 5px;
            color: var(--accent);
        }
        
        /* Log console */
        .log-console {
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--primary-dim);
            border-radius: 4px;
            padding: 15px;
            height: 300px;
            overflow-y: auto;
            font-size: 0.85em;
            line-height: 1.6;
        }
        
        .log-entry {
            margin-bottom: 5px;
            padding: 3px 0;
            border-bottom: 1px solid rgba(0, 255, 65, 0.1);
        }
        
        .log-info { color: var(--primary); }
        .log-warning { color: var(--warning); }
        .log-error { color: var(--danger); }
        .log-success { color: var(--accent); }
        
        /* Grid layout */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        
        /* Session list */
        .session-item {
            padding: 10px;
            border: 1px solid var(--primary-dim);
            margin-bottom: 10px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .session-item:hover {
            background: rgba(0, 255, 65, 0.1);
            border-color: var(--primary);
        }
        
        .session-item.active {
            background: rgba(0, 255, 65, 0.2);
            border-color: var(--primary);
        }
        
        /* Checkbox styling */
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: var(--primary);
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }
            
            .grid {
                grid-template-columns: 1fr;
            }
        }
        
        /* Loading spinner */
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid var(--primary-dim);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>KiwiEater System</h1>
            <p>TACHIKOMA MEMORY DUMP INTERFACE v2.0</p>
        </header>
        
        <div class="status-bar">
            <div class="status-indicator">
                <div class="status-dot" id="statusDot"></div>
                <span id="statusText">SYSTEM IDLE</span>
            </div>
            <div id="clock">--:--:--</div>
        </div>
        
        <div class="grid">
            <div class="panel">
                <h2>🎯 Mission Parameters</h2>
                <div class="form-group">
                    <label for="targetUrl">TARGET WIKI URL</label>
                    <input type="text" id="targetUrl" placeholder="https://kiwifarms.st" value="https://kiwifarms.st">
                </div>
                
                <div class="form-group">
                    <label for="maxDepth">MAXIMUM DEPTH</label>
                    <input type="number" id="maxDepth" value="3" min="1" max="10">
                </div>
                
                <div class="form-group">
                    <label for="delayMin">REQUEST DELAY MIN (seconds)</label>
                    <input type="number" id="delayMin" value="2" min="0" step="0.5">
                </div>
                
                <div class="form-group">
                    <label for="delayMax">REQUEST DELAY MAX (seconds)</label>
                    <input type="number" id="delayMax" value="5" min="0" step="0.5">
                </div>
                
                <div class="checkbox-group">
                    <input type="checkbox" id="solveChallenges" checked>
                    <label for="solveChallenges">AUTO-SOLVE CHALLENGES (Kiwiflare/Captcha)</label>
                </div>
                
                <div class="checkbox-group">
                    <input type="checkbox" id="compressImages" checked>
                    <label for="compressImages">COMPRESS IMAGES</label>
                </div>
                
                <div class="checkbox-group">
                    <input type="checkbox" id="saveVideos" checked>
                    <label for="saveVideos">SAVE VIDEOS</label>
                </div>
                
                <div style="margin-top: 20px;">
                    <button class="btn" id="startBtn" onclick="startCrawl()">
                        ▶ INITIATE DUMP
                    </button>
                    <button class="btn btn-danger" id="stopBtn" onclick="stopCrawl()" disabled>
                        ⏹ ABORT
                    </button>
                </div>
            </div>
            
            <div class="panel">
                <h2>📊 Mission Status</h2>
                <div class="progress-container">
                    <div class="progress-bar">
                        <div class="progress-fill" id="progressFill"></div>
                    </div>
                    <div class="progress-text" id="progressText">0 pages processed</div>
                </div>
                
                <div style="margin-top: 20px;">
                    <p><strong>CURRENT URL:</strong></p>
                    <p id="currentUrl" style="color: var(--accent); word-break: break-all;">-</p>
                </div>
                
                <div style="margin-top: 15px;">
                    <p><strong>PAGES:</strong> <span id="pageCount">0</span></p>
                    <p><strong>ASSETS:</strong> <span id="assetCount">0</span></p>
                    <p><strong>DEPTH:</strong> <span id="currentDepth">0</span></p>
                </div>
            </div>
        </div>
        
        <div class="panel">
            <h2>💾 Previous Sessions</h2>
            <div id="sessionList">
                <p style="color: var(--primary-dim);">Loading sessions...</p>
            </div>
        </div>
        
        <div class="panel">
            <h2>📜 System Log</h2>
            <div class="log-console" id="logConsole"></div>
        </div>
    </div>
    
    <script>
        const socket = io();
        let currentSessionId = null;
        
        // Update clock
        function updateClock() {
            const now = new Date();
            document.getElementById('clock').textContent = now.toLocaleTimeString();
        }
        setInterval(updateClock, 1000);
        updateClock();
        
        // Add log entry
        function addLog(message, type = 'info') {
            const console = document.getElementById('logConsole');
            const entry = document.createElement('div');
            entry.className = `log-entry log-${type}`;
            
            const timestamp = new Date().toLocaleTimeString();
            entry.textContent = `[${timestamp}] ${message}`;
            
            console.appendChild(entry);
            console.scrollTop = console.scrollHeight;
        }
        
        // Load sessions
        async function loadSessions() {
            try {
                const response = await fetch('/api/sessions');
                const sessions = await response.json();
                
                const sessionList = document.getElementById('sessionList');
                
                if (sessions.length === 0) {
                    sessionList.innerHTML = '<p style="color: var(--primary-dim);">No previous sessions found</p>';
                    return;
                }
                
                sessionList.innerHTML = '';
                sessions.forEach(session => {
                    const item = document.createElement('div');
                    item.className = 'session-item';
                    item.innerHTML = `
                        <strong>${session.session_id}</strong><br>
                        <small>URL: ${session.base_url || 'N/A'}</small><br>
                        <small>Pages: ${session.progress || 0} | Status: ${session.status || 'unknown'}</small><br>
                        <small>Date: ${session.timestamp ? new Date(session.timestamp).toLocaleString() : 'Unknown'}</small>
                    `;
                    item.onclick = () => resumeSession(session.session_id);
                    sessionList.appendChild(item);
                });
            } catch (error) {
                addLog('Failed to load sessions: ' + error.message, 'error');
            }
        }
        
        // Start crawl
        async function startCrawl() {
            const url = document.getElementById('targetUrl').value.trim();
            if (!url) {
                addLog('ERROR: Target URL is required', 'error');
                return;
            }
            
            const config = {
                url: url,
                max_depth: parseInt(document.getElementById('maxDepth').value) || 3,
                delay_min: parseFloat(document.getElementById('delayMin').value) || 2,
                delay_max: parseFloat(document.getElementById('delayMax').value) || 5,
                solve_challenges: document.getElementById('solveChallenges').checked,
                compress_images: document.getElementById('compressImages').checked,
                save_videos: document.getElementById('saveVideos').checked
            };
            
            try {
                const response = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    currentSessionId = result.session_id;
                    document.getElementById('startBtn').disabled = true;
                    document.getElementById('stopBtn').disabled = false;
                    document.getElementById('statusDot').className = 'status-dot active';
                    document.getElementById('statusText').textContent = 'DUMP IN PROGRESS';
                    addLog(`Mission initiated: ${url}`, 'success');
                } else {
                    addLog(`ERROR: ${result.error}`, 'error');
                }
            } catch (error) {
                addLog('ERROR: Failed to start mission: ' + error.message, 'error');
            }
        }
        
        // Stop crawl
        async function stopCrawl() {
            try {
                await fetch('/api/stop', { method: 'POST' });
                addLog('Abort command sent', 'warning');
            } catch (error) {
                addLog('ERROR: Failed to stop: ' + error.message, 'error');
            }
        }
        
        // Resume session
        async function resumeSession(sessionId) {
            try {
                const response = await fetch(`/api/resume/${sessionId}`, { method: 'POST' });
                const result = await response.json();
                
                if (result.success) {
                    currentSessionId = sessionId;
                    document.getElementById('startBtn').disabled = true;
                    document.getElementById('stopBtn').disabled = false;
                    document.getElementById('statusDot').className = 'status-dot active';
                    document.getElementById('statusText').textContent = 'RESUMING DUMP';
                    addLog(`Resuming session: ${sessionId}`, 'success');
                } else {
                    addLog(`ERROR: ${result.error}`, 'error');
                }
            } catch (error) {
                addLog('ERROR: Failed to resume: ' + error.message, 'error');
            }
        }
        
        // Socket events
        socket.on('progress', (data) => {
            document.getElementById('currentUrl').textContent = data.url;
            document.getElementById('pageCount').textContent = data.progress;
            document.getElementById('currentDepth').textContent = data.depth;
            
            const progressPercent = Math.min(100, (data.progress / 1000) * 100);
            document.getElementById('progressFill').style.width = progressPercent + '%';
            document.getElementById('progressText').textContent = `${data.progress} pages processed`;
            
            addLog(`[${data.depth}] ${data.url}`, 'info');
        });
        
        socket.on('log', (data) => {
            addLog(data.message, data.level);
        });
        
        socket.on('complete', (data) => {
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('statusDot').className = 'status-dot';
            document.getElementById('statusText').textContent = 'DUMP COMPLETE';
            document.getElementById('assetCount').textContent = data.assets;
            
            addLog(`Mission complete! Pages: ${data.pages}, Assets: ${data.assets}`, 'success');
            addLog(`Archive location: /archives/${data.archive_name}/`, 'success');
            
            setTimeout(loadSessions, 1000);
        });
        
        socket.on('error', (data) => {
            addLog(`ERROR: ${data.message}`, 'error');
            document.getElementById('statusDot').className = 'status-dot error';
        });
        
        // Load sessions on startup
        loadSessions();
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    """Serve main UI."""
    return render_template_string(UI_TEMPLATE)


@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """Get list of previous sessions."""
    sessions = []
    if SESSIONS_DIR.exists():
        for f in SESSIONS_DIR.glob('*.json'):
            if '_cookies' not in f.name:
                try:
                    with open(f, 'r') as file:
                        data = json.load(file)
                        sessions.append({
                            'session_id': data.get('session_id', f.stem),
                            'base_url': data.get('base_url', ''),
                            'progress': data.get('progress', 0),
                            'status': data.get('status', 'unknown'),
                            'timestamp': data.get('timestamp', '')
                        })
                except:
                    pass
    
    sessions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify(sessions)


@app.route('/api/start', methods=['POST'])
def api_start():
    """Start new crawl."""
    global active_crawler, current_session_id
    
    if active_crawler and active_crawler.session_state == "running":
        return jsonify({'success': False, 'error': 'Crawl already in progress'})
    
    data = request.json
    if not data or not data.get('url'):
        return jsonify({'success': False, 'error': 'URL required'})
    
    # Generate session ID
    current_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Load and merge config
    config = load_config()
    config['crawl_settings']['max_depth'] = data.get('max_depth', 3)
    config['crawl_settings']['request_delay_min'] = data.get('delay_min', 2)
    config['crawl_settings']['request_delay_max'] = data.get('delay_max', 5)
    config['anti_detection']['solve_challenges'] = data.get('solve_challenges', True)
    config['storage']['compress_images'] = data.get('compress_images', True)
    config['storage']['save_videos'] = data.get('save_videos', True)
    
    # Create crawler
    active_crawler = KiwiEaterCrawler(config, current_session_id, socketio)
    
    # Start crawl in background thread
    def run_crawl():
        try:
            active_crawler.start_crawl(data['url'], resume=False)
        except Exception as e:
            socketio.emit('error', {'message': str(e)})
    
    thread = threading.Thread(target=run_crawl, daemon=True)
    thread.start()
    
    return jsonify({'success': True, 'session_id': current_session_id})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop current crawl."""
    global active_crawler
    
    if active_crawler:
        active_crawler.stop()
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'No active crawl'})


@app.route('/api/resume/<session_id>', methods=['POST'])
def api_resume(session_id):
    """Resume previous session."""
    global active_crawler, current_session_id
    
    if active_crawler and active_crawler.session_state == "running":
        return jsonify({'success': False, 'error': 'Crawl already in progress'})
    
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return jsonify({'success': False, 'error': 'Session not found'})
    
    current_session_id = session_id
    config = load_config()
    
    # Create crawler and load state
    active_crawler = KiwiEaterCrawler(config, session_id, socketio)
    
    if not active_crawler.load_session_state():
        return jsonify({'success': False, 'error': 'Failed to load session state'})
    
    # Resume crawl
    def run_crawl():
        try:
            if active_crawler.base_url:
                active_crawler.start_crawl(active_crawler.base_url, resume=True)
        except Exception as e:
            socketio.emit('error', {'message': str(e)})
    
    thread = threading.Thread(target=run_crawl, daemon=True)
    thread.start()
    
    return jsonify({'success': True, 'session_id': session_id})


@app.route('/archives/<path:filename>')
def serve_archive(filename):
    """Serve archived files."""
    return send_from_directory(ARCHIVES_DIR, filename)


def main():
    """Main entry point."""
    config = load_config()
    network_config = config.get('network', {})
    
    host = network_config.get('host', '127.0.0.1')
    port = network_config.get('port', 8080)
    enable_network = network_config.get('enable_local_network', False)
    
    if enable_network:
        host = '0.0.0.0'
    
    print("=" * 60)
    print("⚡ KIWIEATER SYSTEM INITIALIZING ⚡")
    print("=" * 60)
    print(f"TACHIKOMA INTERFACE MODE")
    print(f"Config: {CONFIG_PATH}")
    print(f"Archives: {ARCHIVES_DIR}")
    print(f"Sessions: {SESSIONS_DIR}")
    print("=" * 60)
    print(f"🌐 Access interface at: http://localhost:{port}")
    if enable_network:
        print(f"🔓 Network access enabled")
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            print(f"📡 Local network: http://{local_ip}:{port}")
        except:
            pass
    print("=" * 60)
    print("Press Ctrl+C to shutdown")
    print("=" * 60)
    
    try:
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print("\n\nShutting down KiwiEater system...")
        if active_crawler:
            active_crawler.stop()
        print("System terminated")


if __name__ == '__main__':
    main()
