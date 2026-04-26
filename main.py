from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter
import requests
import os
import tempfile

app = Flask(__name__)
CORS(app)


@app.route("/", methods=["GET"])
def home():
    return "SignalScript API is running."


def create_transcript_pdf(transcript_text):
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf_path = temp_file.name
    temp_file.close()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    body_style = styles["Normal"]
    body_style.leading = 14

    content = []
    content.append(Paragraph("YouTube Transcript", title_style))
    content.append(Spacer(1, 20))

    if isinstance(transcript_text, list):
        for item in transcript_text:
            if isinstance(item, dict):
                text = item.get("text", "")
            else:
                text = str(item)

            if text.strip():
                content.append(Paragraph(text, body_style))
                content.append(Spacer(1, 10))
    else:
        for paragraph in str(transcript_text).split("\n"):
            if paragraph.strip():
                content.append(Paragraph(paragraph, body_style))
                content.append(Spacer(1, 10))

    doc.build(content)

    return pdf_path


@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "Missing YouTube URL"}), 400

    try:
        api_key = os.environ.get("SUPADATA_API_KEY")

        if not api_key:
            return jsonify({"error": "Missing SUPADATA_API_KEY"}), 500

        response = requests.get(
            "https://api.supadata.ai/v1/youtube/transcript",
            params={"url": url},
            headers={"x-api-key": api_key}
        )

        result = response.json()

        if "transcript" in result:
            pdf_path = create_transcript_pdf(result["transcript"])

            return send_file(
                pdf_path,
                as_attachment=True,
                download_name="youtube_transcript.pdf",
                mimetype="application/pdf"
            )

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
