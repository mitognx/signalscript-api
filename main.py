from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import os

app = Flask(__name__)
CORS(app)

def get_video_id(url):
    parsed = urlparse(url)

    if "youtube.com" in parsed.netloc:
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1].split("/")[1]
        return parse_qs(parsed.query).get("v", [None])[0]

    if "youtu.be" in parsed.netloc:
        return parsed.path.strip("/")

    return url

@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."

@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "Missing YouTube URL"}), 400

    video_id = get_video_id(url)

    try:
        transcript_data = YouTubeTranscriptApi().fetch(video_id)
        clean_text = " ".join([item.text for item in transcript_data])

        return jsonify({
            "video_id": video_id,
            "transcript": clean_text
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Transcript unavailable. Captions may be disabled, private, blocked, or unavailable."
        }), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
