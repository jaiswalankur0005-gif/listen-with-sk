import time
import requests
import yt_dlp
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__)

URL_CACHE = {}
CACHE_TTL = 1800  # 30 minutes


def get_audio_url(video_id, title=""):
    now = time.time()
    if video_id in URL_CACHE:
        url, mime, ts = URL_CACHE[video_id]
        if now - ts < CACHE_TTL:
            return url, mime

    # 1. Try YouTube with mobile/TV clients (Bot check bypass)
    yt_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "tv_embedded"]
            }
        },
    }
    try:
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            audio_url = info["url"]
            ext = info.get("ext", "m4a")
            mime = "audio/mp4" if ext == "m4a" else f"audio/{ext}"
            URL_CACHE[video_id] = (audio_url, mime, now)
            return audio_url, mime
    except Exception:
        pass

    # 2. Auto-Fallback: Agar YouTube block kare, toh SoundCloud se audio uthao
    search_q = title if title else video_id
    sc_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(sc_opts) as ydl:
        info = ydl.extract_info(f"scsearch1:{search_q}", download=False)
        entry = info["entries"][0]
        audio_url = entry["url"]
        mime = "audio/mpeg"
        URL_CACHE[video_id] = (audio_url, mime, now)
        return audio_url, mime


@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch12:{query}", download=False)
            entries = result.get("entries", []) or []

        songs = []
        for item in entries:
            vid = item.get("id")
            if not vid:
                continue
            songs.append({
                "id": vid,
                "title": item.get("title", "Unknown Song"),
                "artist": item.get("channel") or item.get("uploader") or "YouTube",
                "duration": item.get("duration") or 0,
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            })
        return jsonify(songs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/play/<video_id>")
def play(video_id):
    try:
        title = request.args.get("title", "")
        audio_url, mime = get_audio_url(video_id, title)
        range_header = request.headers.get("Range")
        headers = {"User-Agent": "Mozilla/5.0"}
        if range_header:
            headers["Range"] = range_header

        r = requests.get(audio_url, headers=headers, stream=True, timeout=20)

        def generate():
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        resp_headers = {
            "Content-Type": r.headers.get("Content-Type", mime),
            "Accept-Ranges": "bytes",
        }
        if "Content-Range" in r.headers:
            resp_headers["Content-Range"] = r.headers["Content-Range"]
        if "Content-Length" in r.headers:
            resp_headers["Content-Length"] = r.headers["Content-Length"]

        return Response(generate(), status=r.status_code, headers=resp_headers)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
