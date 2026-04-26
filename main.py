from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."

@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "Missing YouTube URL"}), 400

    try:
        api_key = os.environ.get("SUPADATA_API_KEY")

        response = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": api_key}
        )

        result = response.json()

        # If Supadata returns transcript
        if "transcript" in result:
            return jsonify({
                "transcript": result["transcript"]
            })

        # If Supadata returns an error
        return jsonify({
            "error": "Transcript unavailable",
            "details": result
        }), 400

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
