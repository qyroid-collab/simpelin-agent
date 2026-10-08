import json
import os
import asyncio
import feedparser
import edge_tts
from google import genai
from notion_client import Client
# Inisialisasi Client
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
notion = Client(auth=os.getenv("NOTION_TOKEN"))
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

GEMINI_MODEL = "gemini-flash"

# 1. Radar Tren
def get_trending_topic():
    feed_url = "https://trends.google.com/trending/rss?geo=ID"
    feed = feedparser.parse(feed_url)
    if feed.entries:
        first_entry = feed.entries[0]
        return {
            "title": first_entry.title,
            "link": first_entry.link
        }
    return {"title": "Update Ekonomi Digital Indonesia", "link": "https://bps.go.id"}

# 2. Generator Naskah Simpelin
def generate_script(topic):
    prompt = f"""
    Kamu adalah pembuat konten akun berita & edukasi "Simpelin".
    Topik: {topic['title']}
    Sumber: {topic['link']}

    Buat naskah video pendek (maksimal 60 detik / ~130 kata):
    - Santai tapi tajam, kalimat pendek, tanpa kata kaku.
    - Struktur: Hook (1 kalimat) -> Inti Masalah -> Kenapa Penting -> Solusi/Aksi.
    - Pilih Pilar Topik: Kebijakan & Pemerintah / Ekonomi Digital / Bisnis Local.
    - Buat Fact-Check ringkas (KNOWN/INFERRED/NEEDS RESEARCH).
    - Buat Caption + Hashtag siap pakai.

    Format JSON Wajib:
    {{
        "pilar": "Nama Pilar",
        "fact_check": "Ringkasan verifikasi...",
        "naskah": "Isi naskah utuh...",
        "caption": "Isi caption dan hashtag..."
    }}
    """
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)
# 3. Generate Voiceover
async def generate_vo(text, output_file="vo.mp3"):
    communicate = edge_tts.Communicate(text, "id-ID-ArdiNeural")
    await communicate.save(output_file)

# 4. Push ke Notion Database
def push_to_notion(topic_title, data):
    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Topik / Judul": {
                "title": [{"text": {"content": topic_title}}]
            },
            "Status": {
                "status": {"name": "2. Menunggu Approve"}
            },
            "Pilar Topik": {
                "select": {"name": data.get("pilar", "Viral & Konteks")}
            },
            "Fact Check & Sumber": {
                "rich_text": [{"text": {"content": data.get("fact_check", "")}}]
            },
            "Paket Caption & Hashtag": {
                "rich_text": [{"text": {"content": data.get("caption", "")}}]
            }
        },
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Draft Naskah Simpelin"}}]}
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": data.get("naskah", "")}}]}
            }
        ]
    )

async def main():
    topic = get_trending_topic()
    script_data = generate_script(topic)
    await generate_vo(script_data['naskah'])
    push_to_notion(topic['title'], script_data)

if __name__ == "__main__":
    asyncio.run(main())
