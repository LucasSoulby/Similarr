# Similarr 🎵

![Similarr Dashboard](https://img.shields.io/badge/Status-v1.0_Complete-brightgreen) ![Docker](https://img.shields.io/badge/Docker-Supported-blue)

A lightweight, Dockerized automation bridge for TrueNAS and homelabs that connects your Plex (Plexamp) ratings to Lidarr using the Last.fm API. 

**Disclaimer:** *Hey! I'm pretty new to coding (I've only taken one AP Comp Sci class and I'm not a developer by trade). This is my first major homelab project. I built it to solve a specific problem in my stack, and while the code might not be textbook perfect, it runs flawlessly on my TrueNAS server 24/7!*

---

## 🚀 What it Does
Similarr acts as a background discovery engine for your music library:
1. **Listens to Plex:** It scans your Plex library for artists you've rated 2.5+ stars and tracks you've rated 3.0+ stars.
2. **Asks Last.fm:** It takes your favorites and asks Last.fm for "Similar Artists" and "Similar Tracks".
3. **Smart Filters:** It uses C++ accelerated Fuzzy Matching (`thefuzz`) to check your Lidarr library to ensure you don't already own the recommended artist under a slightly different name (e.g., skipping "The Beatles" if you have "Beatles, The").
4. **Auto-Adds to Lidarr:** It automatically adds the missing artists to Lidarr, wakes up "unmonitored" ghost artists, and triggers album searches.
5. **Protects your Queue:** Features a customizable "Daily Add Limit" so your torrent client (qBittorrent/Transmission) doesn't get slammed with 500 discographies at once.

## ✨ Features
* **Built-in WebUI:** A slick, *arr*-style dark mode dashboard running on Flask.
* **Live Settings:** Change your daily limits, fuzzy strictness, Plex rating thresholds, and Lidarr profiles directly from the browser—no JSON editing required.
* **Multi-threaded:** The background scanner runs on its own thread, meaning the WebUI never hangs while it's doing heavy lifting.
* **Self-Healing:** Handles missing API connections, unmonitored existing artists, and auto-resets its daily counters at midnight.

---

## 🛠️ Installation (Docker Compose)

The easiest way to run this on TrueNAS SCALE (or any Docker environment) is via `docker-compose`.

### 1. Create your `docker-compose.yml`
```yaml
version: '3.8'

services:
  similarr-engine:
    image: ljsbaseball8/similarr:latest
    container_name: similarr-worker
    restart: unless-stopped
    env_file: .env
    ports:
      - "${PORT:-5000}:${PORT:-5000}"
    volumes:
      - ./history.json:/app/history.json
      - ./config.json:/app/config.json
```

### 2. Create your `.env` file
You need to provide your API keys for the script to talk to your homelab. Create a file named `.env` in the same directory:
```env
PLEX_URL=http://192.168.x.x:32400
PLEX_TOKEN=your_plex_token_here
LASTFM_API_KEY=your_lastfm_api_key_here
LIDARR_URL=http://192.168.x.x:32400
LIDARR_API_KEY=your_lidarr_api_key_here
PORT=web_ui_port_here
```

### 3. Deploy
Run the following commands in your terminal:
```bash
# Create empty files so Docker doesn't accidentally make folders
touch history.json
touch config.json

# Start the container
docker compose up -d
```

## 🎛️ Usage
Once the container is running, open your web browser and go to:
`http://<your-server-ip>:5000` (or you're set port from .env)

From the WebUI, you can view your total monitored artists, adjust your discovery parameters in the **Settings** tab, and click **Run Discovery Now** to force a manual scan. Otherwise, the engine will happily sleep in the background and run its checks every 24 hours.

---
*Built for the homelab community.*
