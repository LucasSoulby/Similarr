import requests
import time
import random
import json
import os
import threading
import datetime
from flask import Flask, render_template, request, redirect
from plexapi.server import PlexServer
from thefuzz import fuzz

# Initialize the Flask App
app = Flask(__name__)

# ==========================================
# SECRETS (Loaded via .env)
# ==========================================
PLEX_URL = os.environ.get('PLEX_URL', '')
PLEX_TOKEN = os.environ.get('PLEX_TOKEN', '')
LASTFM_API_KEY = os.environ.get('LASTFM_API_KEY', '')
LIDARR_URL = os.environ.get('LIDARR_URL', '')
LIDARR_API_KEY = os.environ.get('LIDARR_API_KEY', '')
LIDARR_HEADERS = {'X-Api-Key': LIDARR_API_KEY}
PORT = int(os.environ.get('PORT', 5000))
HISTORY_FILE = 'history.json'
DEBUG_MODE = os.environ.get("DEBUG_MODE", "False").lower() == "true"
ENGINE_STATUS = "Sleeping"

# ==========================================
# SETTINGS (Loaded via config.json)
# ==========================================
def load_config():
    config = {
        "plex_min_artist_rating": 2.5,
        "plex_min_track_rating": 3.0,
        "sample_size": 10,
        "daily_add_limit": 5,
        "fuzz_threshold": 95,
        "quality_profile_id": 1,
        "metadata_profile_id": 1,
        "root_folder_path": "/data/Music",
        "lastfm_rec_limit": 5
    }
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
    except Exception as e:
        print(f"[WARNING] Could not load config.json: {e}. Using defaults.")
    return config

CONFIG = load_config()

# ==========================================
# ATOMIC HISTORY MANAGEMENT
# ==========================================
def read_history():
    """Reads the history file fresh from the disk every time."""
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "checked_artists": [], 
            "checked_tracks": [], 
            "activity_log": [], 
            "date": str(datetime.date.today()), 
            "added_today": 0, 
            "total_monitored": 0
        }

def write_history(data):
    """Writes to the history file instantly to prevent thread clashing."""
    with open(HISTORY_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def record_successful_add(message):
    """Updates the counters and activity log instantly."""
    hist = read_history()
    
    # 1. Check if we crossed midnight to reset the daily limit
    today = str(datetime.date.today())
    if hist.get("date") != today:
        hist["date"] = today
        hist["added_today"] = 0
        
    # 2. Increment counters
    hist["added_today"] = hist.get("added_today", 0) + 1
    hist["total_monitored"] = hist.get("total_monitored", 0) + 1
    
    # 3. Log the Activity
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
    if "activity_log" not in hist:
        hist["activity_log"] = []
    hist["activity_log"].insert(0, f"[{timestamp}] {message}")
    hist["activity_log"] = hist["activity_log"][:50] # Keep only last 50
    
    write_history(hist)

def get_lidarr_library():
    print("Downloading Lidarr library for Fuzzy Matching...")
    url = f"{LIDARR_URL}/api/v1/artist"
    response = requests.get(url, headers=LIDARR_HEADERS)
    if response.status_code == 200:
        return response.json()
    return []

def process_and_add_to_lidarr(artist_name, lidarr_library):
    print(f"  -> Checking Lidarr for: {artist_name}...")
    
    for lib_artist in lidarr_library:
        if fuzz.ratio(artist_name.lower(), lib_artist['artistName'].lower()) >= CONFIG['fuzz_threshold']:
            print(f"     [SKIPPED] Fuzzy Match! '{artist_name}' is {fuzz.ratio(artist_name.lower(), lib_artist['artistName'].lower())}% similar to '{lib_artist['artistName']}' and is already monitored.")
            return False

    search_url = f"{LIDARR_URL}/api/v1/artist/lookup?term={artist_name}"
    search_res = requests.get(search_url, headers=LIDARR_HEADERS)
    
    if search_res.status_code != 200 or not search_res.json():
        return False
        
    artist_data = search_res.json()[0]
    
    if 'id' in artist_data and artist_data['id'] != 0:
        if artist_data.get('monitored', False):
            print(f"     [SKIPPED] {artist_data['artistName']} is already fully monitored.")
            return False
        else:
            print(f"     [GHOST HUNTER] Waking up {artist_data['artistName']}...")
            artist_data['monitored'] = True
            artist_data['monitorNewItems'] = "all"
            update_url = f"{LIDARR_URL}/api/v1/artist/{artist_data['id']}"
            put_res = requests.put(update_url, headers=LIDARR_HEADERS, json=artist_data)
            if put_res.status_code in [200, 202]:
                print(f"     [SUCCESS] Woke up {artist_data['artistName']}!")
                record_successful_add(f"Woke up ghost artist: {artist_data['artistName']}")
                return True
            return False

    print(f"     [ADDING] Sending {artist_data['artistName']} to Lidarr...")
    artist_data['qualityProfileId'] = CONFIG['quality_profile_id']
    artist_data['metadataProfileId'] = CONFIG['metadata_profile_id']
    artist_data['rootFolderPath'] = CONFIG['root_folder_path']
    artist_data['monitored'] = True
    artist_data['addOptions'] = {"searchForMissingAlbums": True}
    
    add_url = f"{LIDARR_URL}/api/v1/artist"
    add_res = requests.post(add_url, headers=LIDARR_HEADERS, json=artist_data)
    
    if add_res.status_code == 201:
        print(f"     [SUCCESS] Added {artist_data['artistName']}!")
        record_successful_add(f"Discovered & Added: {artist_data['artistName']}")
        return True
    return False

# ==========================================
# MAIN DISCOVERY LOGIC
# ==========================================
def get_discoveries():
    global CONFIG, ENGINE_STATUS
    ENGINE_STATUS = "Scanning..."
    CONFIG = load_config()
    
    print("Connecting to Plex...")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        music_lib = plex.library.section('Music') 
    except Exception as e:
        print(f"[ERROR] Could not connect to Plex: {e}")
        return

    lidarr_library = get_lidarr_library()
    
    # Update total monitored at the start of the run
    hist = read_history()
    hist["total_monitored"] = len(lidarr_library)
    write_history(hist)
    
    daily_limit = CONFIG['daily_add_limit']
    
    # ------------------------------------------------
    # ARTIST DISCOVERY
    # ------------------------------------------------
    print(f"\n--- Scanning for Artists ({CONFIG['plex_min_artist_rating']}+ Stars) ---")
    highly_rated_artists = music_lib.search(libtype='artist', filters={'userRating>>=': CONFIG['plex_min_artist_rating']})
    
    hist = read_history()
    un_checked_artists = [a for a in highly_rated_artists if str(a.ratingKey) not in hist.get('checked_artists', [])]
    print(f"Found {len(un_checked_artists)} un-checked highly-rated artists.")
    
    sample_to_check = random.sample(un_checked_artists, min(CONFIG['sample_size'], len(un_checked_artists)))
    
    for i, artist in enumerate(sample_to_check):
        current_hist = read_history()
        if current_hist.get("added_today", 0) >= daily_limit:
            print(f"\n[LIMIT REACHED] Added {daily_limit} artists today. Stopping.")
            return

        print(f"\n[ARTIST MATCH {i+1}/{len(sample_to_check)}] Asking Last.fm who sounds like {artist.title}...")
        
        lastfm_url = f"http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist={artist.title}&api_key={LASTFM_API_KEY}&format=json&limit={CONFIG['lastfm_rec_limit']}"
        res = requests.get(lastfm_url)
        
        if res.status_code == 200:
            data = res.json()
            if 'similarartists' in data and 'artist' in data['similarartists'] and data['similarartists']['artist']:
                for rec in data['similarartists']['artist']:
                    chk_hist = read_history()
                    if chk_hist.get("added_today", 0) >= daily_limit:
                        return
                    process_and_add_to_lidarr(rec['name'], lidarr_library)
            else:
                print("  -> No matches found on Last.fm.")
        
        # Mark as checked instantly
        update_hist = read_history()
        update_hist['checked_artists'].append(str(artist.ratingKey))
        write_history(update_hist)
        time.sleep(2) 
        
    # ------------------------------------------------
    # TRACK DISCOVERY
    # ------------------------------------------------
    final_chk_hist = read_history()
    if final_chk_hist.get("added_today", 0) < daily_limit:
        print(f"\n--- Scanning for Tracks ({CONFIG['plex_min_track_rating']}+ Stars) ---")
        highly_rated_tracks = music_lib.search(libtype='track', filters={'userRating>>=': CONFIG['plex_min_track_rating']})
        
        hist = read_history()
        un_checked_tracks = [t for t in highly_rated_tracks if str(t.ratingKey) not in hist.get('checked_tracks', [])]
        print(f"Found {len(un_checked_tracks)} un-checked highly-rated tracks.")
        
        track_sample = random.sample(un_checked_tracks, min(CONFIG['sample_size'], len(un_checked_tracks)))
        
        for i, track in enumerate(track_sample):
            current_hist = read_history()
            if current_hist.get("added_today", 0) >= daily_limit:
                print(f"\n[LIMIT REACHED] Added {daily_limit} artists today. Stopping.")
                return

            print(f"\n[TRACK MATCH {i+1}/{len(track_sample)}] Asking Last.fm what sounds like '{track.title}'...")
            
            artist_to_search = track.originalTitle if track.originalTitle else track.grandparentTitle
            lastfm_url = f"http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist={artist_to_search}&track={track.title}&api_key={LASTFM_API_KEY}&format=json&limit={CONFIG['lastfm_rec_limit']}"
            res = requests.get(lastfm_url)
            
            if res.status_code == 200:
                data = res.json()
                if 'similartracks' in data and 'track' in data['similartracks'] and data['similartracks']['track']:
                    seen_artists = []
                    for rec_track in data['similartracks']['track']:
                        chk_hist = read_history()
                        if chk_hist.get("added_today", 0) >= daily_limit:
                            return
                            
                        rec_artist = rec_track['artist']['name']
                        if rec_artist.lower() not in seen_artists:
                            process_and_add_to_lidarr(rec_artist, lidarr_library)
                            seen_artists.append(rec_artist.lower())
                else:
                    print("  -> No matches found on Last.fm.")
            
            update_hist = read_history()
            update_hist['checked_tracks'].append(str(track.ratingKey))
            write_history(update_hist)
            time.sleep(2)

    print("\n--- Discovery Run Complete! ---")
    ENGINE_STATUS = "Sleeping"

# ==========================================
# WEB UI ROUTES
# ==========================================
@app.route('/')
def home():
    hist = read_history()
    
    # Run a quick check to see if it's a new day and reset the dashboard UI if needed
    today = str(datetime.date.today())
    if hist.get("date") != today:
        hist["date"] = today
        hist["added_today"] = 0
        write_history(hist)
        
    stats = {
        "added_today": hist.get("added_today", 0),
        "total_added": hist.get("total_monitored", 0),
        "status": ENGINE_STATUS
    }
    # Notice we don't call get_lidarr_library() here anymore! Instant page loads.
    return render_template('dashboard.html', stats=stats, config=CONFIG, activity=hist.get("activity_log", []))

@app.route('/api/stats')
def api_stats():
    """Provides a live JSON feed of the engine's current state."""
    global ENGINE_STATUS, CONFIG
    hist = read_history()
    
    # Handle the midnight reset check silently
    today = str(datetime.date.today())
    if hist.get("date") != today:
        hist["date"] = today
        hist["added_today"] = 0
        write_history(hist)
        
    return {
        "added_today": hist.get("added_today", 0),
        "total_added": hist.get("total_monitored", 0),
        "status": ENGINE_STATUS,
        "daily_limit": CONFIG['daily_add_limit'],
        "activity": hist.get("activity_log", [])
    }

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global CONFIG
    if request.method == 'POST':
        CONFIG['daily_add_limit'] = int(request.form.get('daily_add_limit'))
        CONFIG['fuzz_threshold'] = int(request.form.get('fuzz_threshold'))
        CONFIG['plex_min_artist_rating'] = float(request.form.get('plex_min_artist_rating'))
        CONFIG['plex_min_track_rating'] = float(request.form.get('plex_min_track_rating'))
        CONFIG['sample_size'] = int(request.form.get('sample_size'))
        CONFIG['lastfm_rec_limit'] = int(request.form.get('lastfm_rec_limit'))
        CONFIG['quality_profile_id'] = int(request.form.get('quality_profile_id'))
        CONFIG['metadata_profile_id'] = int(request.form.get('metadata_profile_id'))
        CONFIG['root_folder_path'] = request.form.get('root_folder_path')
        
        with open('config.json', 'w') as f:
            json.dump(CONFIG, f, indent=4)
            
        return redirect('/')
        
    return render_template('settings.html', config=CONFIG)

@app.route('/trigger')
def trigger_run():
    thread = threading.Thread(target=get_discoveries)
    thread.start()
    return "<h1>Discovery Run Started!</h1><p>Check the dashboard activity log to see results.</p><a href='/'>Go Back to Dashboard</a>"

# ==========================================
# BACKGROUND WORKER
# ==========================================
def background_worker():
    while True:
        get_discoveries()
        print("\n[SLEEPING] Engine is resting for 24 hours. See you tomorrow!")
        time.sleep(86400)

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    if not os.path.exists('config.json'):
        with open('config.json', 'w') as f:
            json.dump(load_config(), f, indent=4)
            
    worker_thread = threading.Thread(target=background_worker, daemon=True)
    worker_thread.start()
    
    print("[WEBUI] Starting Web Server on port 5000...")
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)