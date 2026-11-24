import base64
import html
from concurrent.futures import ThreadPoolExecutor
import requests
from Crypto.Cipher import DES
from Crypto.Util.Padding import unpad
from flask import Flask, request, jsonify, redirect, send_from_directory

app = Flask(__name__)

ALLOWED_ORIGINS = {
    "https://listen-with-sk-official.github.io",
    "https://listen-with-sk-official.blogspot.com",
    "https://listen-with-sk.onrender.com",
}


def is_allowed_request():
    origin = (request.headers.get("Origin") or "").rstrip("/")
    referer = request.headers.get("Referer") or ""

    if origin:
        return origin in ALLOWED_ORIGINS

    if referer:
        return any(referer.startswith(allowed) for allowed in ALLOWED_ORIGINS)

    return True


@app.before_request
def guard_api_routes():
    if request.path.startswith("/api/"):
        if not is_allowed_request():
            return jsonify({"error": "Unauthorized origin"}), 403


@app.after_request
def add_cors(response):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


AUDIO_CACHE = {}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
SAAVN_URL = "https://www.jiosaavn.com/api.php"


def decrypt_url(enc_url, is_320=False):
    key = b"38346591"
    cipher = DES.new(key, DES.MODE_ECB)
    raw = base64.b64decode(enc_url.strip())
    decrypted = unpad(cipher.decrypt(raw), DES.block_size).decode("utf-8")
    if is_320:
        return decrypted.replace("_96.mp4", "_320.mp4")
    return decrypted.replace("_96.mp4", "_160.mp4")


def parse_song_item(item):
    more = item.get("more_info", {}) or {}
    enc_url = more.get("encrypted_media_url") or item.get("encrypted_media_url")
    song_id = item.get("id")
    if not song_id or not enc_url:
        return None

    is_320 = str(more.get("320kbps", "") or item.get("320kbps", "")).lower() == "true"
    try:
        audio_url = decrypt_url(enc_url, is_320)
    except Exception:
        return None

    AUDIO_CACHE[song_id] = audio_url

    artists_list = (more.get("artistMap") or {}).get("primary_artists") or []
    if artists_list:
        artist = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))
    else:
        artist = item.get("subtitle") or item.get("primary_artists") or "Music"

    thumb = (item.get("image") or "").replace("150x150", "500x500")
    duration = int(more.get("duration") or item.get("duration") or 0)

    return {
        "id": song_id,
        "title": html.unescape(item.get("title") or item.get("song") or "Unknown"),
        "artist": html.unescape(artist),
        "duration": duration,
        "thumbnail": thumb,
    }


def fetch_saavn_page(query, page=1, count=30):
    try:
        params = {
            "__call": "search.getResults",
            "_format": "json",
            "_marker": "0",
            "cc": "in",
            "includeMetaTags": "1",
            "q": query,
            "n": str(count),
            "p": str(page),
        }
        res = requests.get(SAAVN_URL, params=params, headers=HEADERS, timeout=10)
        data = res.json()
        return data.get("results", []) or []
    except Exception:
        return []


def fetch_playlist_songs(query):
    try:
        # Top matching playlist dhoondh kar uske gaane laata hai
        res = requests.get(
            SAAVN_URL,
            params={
                "__call": "search.getPlaylistResults",
                "_format": "json",
                "_marker": "0",
                "cc": "in",
                "q": query,
                "n": "2",
                "p": "1",
            },
            headers=HEADERS,
            timeout=8,
        )
        playlists = (res.json().get("results") or [])[:1]
        if not playlists:
            return []

        list_id = playlists[0].get("id")
        if not list_id:
            return []

        detail_res = requests.get(
            SAAVN_URL,
            params={
                "__call": "playlist.getDetails",
                "_format": "json",
                "_marker": "0",
                "cc": "in",
                "listid": list_id,
            },
            headers=HEADERS,
            timeout=8,
        )
        detail_data = detail_res.json()
        return (detail_data.get("list") or detail_data.get("songs") or [])[:20]
    except Exception:
        return []


def fetch_itunes_corrected_saavn(query):
    try:
        # Agar spelling galat ho to iTunes India se sahi track name pakad kar JioSaavn se laata hai
        it_res = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "country": "IN", "media": "music", "entity": "song", "limit": "5"},
            headers=HEADERS,
            timeout=6,
        )
        items = it_res.json().get("results", []) or []
        if not items:
            return []

        top = items[0]
        clean_term = f"{top.get('trackName', '')} {top.get('artistName', '')}".strip()
        if not clean_term or clean_term.lower() == query.lower():
            return []

        return fetch_saavn_page(clean_term, page=1, count=10)
    except Exception:
        return []


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            f_page1 = executor.submit(fetch_saavn_page, query, 1, 30)
            f_page2 = executor.submit(fetch_saavn_page, query, 2, 30)
            f_playlist = executor.submit(fetch_playlist_songs, query)
            f_itunes = executor.submit(fetch_itunes_corrected_saavn, query)

            raw_items = (
                f_page1.result()
                + f_page2.result()
                + f_playlist.result()
                + f_itunes.result()
            )

        songs = []
        seen_ids = set()
        seen_titles = set()

        for item in raw_items:
            parsed = parse_song_item(item)
            if not parsed:
                continue

            title_key = f"{parsed['title'].lower()}_{parsed['artist'].lower()}"
            if parsed["id"] in seen_ids or title_key in seen_titles:
                continue

            seen_ids.add(parsed["id"])
            seen_titles.add(title_key)
            songs.append(parsed)

        return jsonify(songs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/play/<song_id>")
def play(song_id):
    audio_url = AUDIO_CACHE.get(song_id)

    if not audio_url:
        try:
            res = requests.get(
                SAAVN_URL,
                params={
                    "__call": "song.getDetails",
                    "_format": "json",
                    "_marker": "0",
                    "cc": "in",
                    "pids": song_id,
                },
                headers=HEADERS,
                timeout=10,
            )
            data = res.json()
            item = data.get(song_id) or (data.get("songs") or [{}])[0]
            enc_url = item.get("encrypted_media_url")
            if enc_url:
                is_320 = str(item.get("320kbps", "")).lower() == "true"
                audio_url = decrypt_url(enc_url, is_320)
                AUDIO_CACHE[song_id] = audio_url
        except Exception:
            pass

    if not audio_url:
        return jsonify({"error": "Audio not found"}), 404

    return redirect(audio_url, code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
