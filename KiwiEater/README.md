# KiwiEater - Ghost in the Shell S.A.C. 2002 Themed Wiki Archiver

## Overview
KiwiEater is a sophisticated wiki backup system with a **Ghost in the Shell: Stand Alone Complex (2002)** themed interface. It creates structured, navigable offline backups of wikis while implementing novel solutions to bypass Kiwiflare/Captcha challenges.

## Novel Anti-Detection & Challenge Solving Features

### 1. **Browser-Based Challenge Solver**
- Uses Selenium with stealth Chrome configuration
- Executes CDP (Chrome DevTools Protocol) commands to hide automation
- Automatically detects and solves Kiwiflare/Captcha pages
- Waits up to 30 seconds for JavaScript challenges to complete
- Extracts cookies from solved challenges for session reuse

### 2. **Multi-Layer Detection System**
Detects challenge pages by checking for:
- "checking your browser", "ddos-guard", "cloudflare"
- "just a moment", "kiwiflare", "captcha"
- Unusually short responses (<500 chars with 200 status)
- Meta refresh redirects
- Challenge-related page titles

### 3. **Progressive Session Warming**
- Makes preliminary requests before main crawl
- Establishes trust with target server
- Gradual request pattern simulation

### 4. **Advanced Evasion Techniques**
- **User Agent Rotation**: Rotates between 5+ realistic browser signatures
- **Header Randomization**: Full set of browser-like headers
- **Human-like Delays**: Configurable random delays between requests
- **Cookie Persistence**: Saves and reuses cookies across sessions
- **Exponential Backoff**: Progressive wait times on failures

### 5. **Fallback Strategies**
- Multiple retry attempts (configurable, default 5)
- Browser-based solve when standard requests fail
- Re-queuing of challenge pages for later attempts
- Graceful handling of 403/429 errors

## Installation

```bash
cd KiwiEater
pip install -r requirements.txt
```

### Requirements
- Python 3.8+
- Chrome/Chromium browser (for challenge solving)
- Required packages in `requirements.txt`

## Usage

### Start the System
```bash
python kiwieater.py
```

The web interface will open at: **http://localhost:8080**

### Network Access
To enable local network access, edit `config.json`:
```json
{
  "network": {
    "enable_local_network": true,
    "host": "0.0.0.0",
    "port": 8080
  }
}
```

### Interface Features

#### Mission Parameters Panel
- **Target URL**: Wiki URL to backup (e.g., https://kiwifarms.st)
- **Maximum Depth**: How many link levels to crawl (1-10)
- **Request Delay Min/Max**: Human-like delay range in seconds
- **Auto-Solve Challenges**: Enable browser-based captcha solving
- **Compress Images**: Optimize image storage
- **Save Videos**: Download video content

#### Mission Status Panel
- Real-time progress bar
- Current URL being processed
- Page count, asset count, current depth
- Live status indicator

#### Previous Sessions
- View all previous backup sessions
- Click any session to resume from where it left off
- Shows progress, status, and timestamp

#### System Log
- Real-time log output
- Color-coded messages (info, warning, error, success)
- Scrollable console view

## Configuration (config.json)

```json
{
  "branding": {
    "heading": "KIWIFARMS ARCHIVE",
    "subheading": "TACHIKOMA MEMORY DUMP SYSTEM",
    "footer": "Section 9 - Public Information Division"
  },
  "network": {
    "enable_local_network": true,
    "host": "0.0.0.0",
    "port": 8080
  },
  "crawl_settings": {
    "max_depth": 3,
    "request_delay_min": 2.0,
    "request_delay_max": 5.0,
    "timeout_seconds": 30,
    "max_retries": 5,
    "user_agent_rotation": true,
    "respect_robots_txt": false
  },
  "anti_detection": {
    "solve_challenges": true,
    "browser_emulation": true,
    "randomize_headers": true,
    "cookie_persistence": true
  },
  "storage": {
    "compress_images": true,
    "convert_to_blob": true,
    "save_videos": true
  }
}
```

## Archive Structure

```
archives/
└── kiwifarms_st/           # Auto-named from domain
    ├── index.html          # Home page
    ├── site_index.html     # Searchable index of all pages
    ├── thread/
    │   └── example/
    │       └── index.html
    └── assets/
        ├── image/
        │   ├── image_abc123.jpg
        │   └── image_def456.png
        ├── video/
        │   └── video_ghi789.mp4
        └── css/
            └── css_jkl012.css
```

## Features

### ✅ Complete Navigation Preservation
- Internal links rewritten to work offline
- Subdomain support
- Relative path conversion
- Original URLs preserved in data attributes

### ✅ Asset Management
- Images downloaded and compressed (JPEG/PNG optimization)
- Videos saved locally
- CSS files preserved
- Content-addressed storage (hash-based filenames)
- Duplicate detection via MD5 hashing

### ✅ Search & Index
- Auto-generated searchable index page
- Filter by page title or URL
- Statistics dashboard
- Grid layout navigation

### ✅ Session Management
- Automatic state saving every 10 pages
- Cookie persistence between sessions
- Resume from exact point of interruption
- Multiple independent sessions supported

### ✅ Error Handling
- Timeout recovery
- 403/429 rate limit handling
- Server error (5xx) retry logic
- Challenge page detection and solving
- Comprehensive logging

### ✅ Custom Branding
- Configurable heading, subheading, footer
- Archive header injected into each page
- Timestamp and original URL preserved

## Troubleshooting

### Challenge Pages Still Detected
1. Increase `request_delay_min` and `request_delay_max`
2. Enable `solve_challenges` option
3. Check logs for specific challenge type
4. Try running during off-peak hours

### 403 Errors
- The system automatically attempts browser-based solving
- If persistent, increase delays and max_retries
- Check if IP is temporarily blocked

### Slow Performance
- Reduce `max_depth` for faster partial backups
- Increase delay minimum for more human-like patterns
- Disable video saving if not needed

### Browser Not Initializing
- Ensure Chrome/Chromium is installed
- Check that webdriver-manager can download chromedriver
- Review logs for specific error messages

## Technical Details

### Challenge Detection Algorithm
```python
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
    "verifying you are human"
]
```

### Stealth Browser Configuration
- Disables `navigator.webdriver` property
- Spoofs plugins, languages
- Sets realistic window size (1920x1080)
- Uses headless mode with new flags
- Excludes automation switches

## Legal & Ethical Notice

This tool is designed for:
- Personal archival purposes
- Research and preservation
- Offline reading of publicly available content

**Respect:**
- Website terms of service
- Robots.txt directives (configurable)
- Server load and bandwidth
- Copyright and intellectual property

Use responsibly and ethically.

---

**KiwiEater v2.0** - Tachikoma Memory Dump System  
*Ghost in the Shell S.A.C. 2002 Edition*
