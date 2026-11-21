import base64
import html
import requests
from Crypto.Cipher import DES
from Crypto.Util.Padding import unpad
from flask import Flask, request, jsonify, redirect, send_from_directory

app = Flask(__name__)

AUDIO_CACHE = {}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def decrypt_url(enc_url, is_320=False):
    key = b"38346591"
    cipher = DES.new(key, DES.MODE_ECB)
    raw = base64.b64decode(enc_url.strip())
    decrypted = unpad(cipher.decrypt(raw), DES.block_size).decode("utf-8")
    if is_320:
        return decrypted.replace("_96.mp4", "_320.mp4")
    return decrypted.replace("_96.mp4", "_160.mp4")


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "search.getResults",
        "_format": "json",
        "_marker": "0",
        "cc": "in",
        "includeMetaTags": "1",
        "q": query,
        "n": "15",
        "p": "1",
    }

    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = res.json()
        results = data.get("results", []) or []

        songs = []
        for item in results:
            more = item.get("more_info", {}) or {}
            enc_url = more.get("encrypted_media_url") or item.get("encrypted_media_url")
            song_id = item.get("id")
            if not song_id or not enc_url:
                continue

            is_320 = str(more.get("320kbps", "")).lower() == "true"
            try:
                audio_url = decrypt_url(enc_url, is_320)
            except Exception:
                continue

            AUDIO_CACHE[song_id] = audio_url

            # Artist name nikalo
            artists_list = (more.get("artistMap") or {}).get("primary_artists") or []
            if artists_list:
                artist = ", ".join(a.get("name", "") for a in artists_list if a.get("name"))
            else:
                artist = item.get("subtitle") or item.get("primary_artists") or "Music"

            thumb = (item.get("image") or "").replace("150x150", "500x500")
            duration = int(more.get("duration") or item.get("duration") or 0)

            songs.append({
                "id": song_id,
                "title": html.unescape(item.get("title") or item.get("song") or "Unknown"),
                "artist": html.unescape(artist),
                "duration": duration,
                "thumbnail": thumb,
            })

        return jsonify(songs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/play/<song_id>")
def play(song_id):
    audio_url = AUDIO_CACHE.get(song_id)

    if not audio_url:
        try:
            res = requests.get(
                "https://www.jiosaavn.com/api.php",
                params={"__call": "song.getDetails", "_format": "json", "_marker": "0", "cc": "in", "pids": song_id},
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
    
