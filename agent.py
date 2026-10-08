import json
import os
import asyncio
import time

import feedparser
import edge_tts
from google import genai
from google.genai import errors
from notion_client import Client


# =========================
# KONFIGURASI
# =========================

gemini_client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

notion = Client(
    auth=os.getenv("NOTION_TOKEN")
)

NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

GEMINI_MODEL = "gemini-3.8-flash"


# =========================
# 1. RADAR TREN
# =========================

def get_trending_topic():
    feed_url = "https://trends.google.com/trending/rss?geo=ID"

    feed = feedparser.parse(feed_url)

    if feed.entries:
        first_entry = feed.entries[0]

        return {
            "title": first_entry.title,
            "link": first_entry.link
        }

    return {
        "title": "Update Ekonomi Digital Indonesia",
        "link": "https://bps.go.id"
    }


# =========================
# 2. GENERATOR NASKAH
# =========================

def generate_script(topic):

    prompt = f"""
Kamu adalah pembuat konten akun berita & edukasi "Simpelin".

Topik: {topic['title']}
Sumber: {topic['link']}

Buat naskah video pendek maksimal 60 detik atau sekitar 130 kata.

Aturan:
- Santai tapi tajam.
- Gunakan kalimat pendek.
- Jangan menggunakan bahasa yang kaku.
- Struktur: Hook -> Inti Masalah -> Kenapa Penting -> Solusi/Aksi.
- Pilih satu Pilar Topik:
  1. Kebijakan & Pemerintah
  2. Ekonomi Digital
  3. Bisnis Lokal
- Buat Fact-Check ringkas dengan kategori:
  KNOWN / INFERRED / NEEDS RESEARCH.
- Buat Caption + Hashtag siap pakai.

Format JSON wajib:

{{
    "pilar": "Nama Pilar",
    "fact_check": "Ringkasan verifikasi...",
    "naskah": "Isi naskah utuh...",
    "caption": "Isi caption dan hashtag..."
}}
"""

    max_retries = 5

    for attempt in range(max_retries):

        try:

            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )

            break

        except errors.ServerError as e:

            if getattr(e, "code", None) == 503:

                if attempt == max_retries - 1:
                    raise

                wait_time = 10 * (2 ** attempt)

                print(
                    f"Gemini sedang penuh (503). "
                    f"Percobaan {attempt + 1}/{max_retries}. "
                    f"Menunggu {wait_time} detik..."
                )

                time.sleep(wait_time)

            else:
                raise

    return json.loads(response.text)


# =========================
# 3. GENERATE VOICEOVER
# =========================

async def generate_vo(text, output_file="vo.mp3"):

    communicate = edge_tts.Communicate(
        text,
        "id-ID-ArdiNeural"
    )

    await communicate.save(output_file)


# =========================
# 4. PUSH KE NOTION
# =========================

def push_to_notion(topic_title, data):

    notion.pages.create(

        parent={
            "database_id": NOTION_DATABASE_ID
        },

        properties={

            "Topik / Judul": {
                "title": [
                    {
                        "text": {
                            "content": topic_title
                        }
                    }
                ]
            },

            "Status": {
                "status": {
                    "name": "2. Menunggu Approve"
                }
            },

            "Pilar Topik": {
                "select": {
                    "name": data.get(
                        "pilar",
                        "Viral & Konteks"
                    )
                }
            },

            "Fact Check & Sumber": {
                "rich_text": [
                    {
                        "text": {
                            "content": data.get(
                                "fact_check",
                                ""
                            )
                        }
                    }
                ]
            },

            "Paket Caption & Hashtag": {
                "rich_text": [
                    {
                        "text": {
                            "content": data.get(
                                "caption",
                                ""
                            )
                        }
                    }
                ]
            }
        },

        children=[

            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {
                            "text": {
                                "content": "Draft Naskah Simpelin"
                            }
                        }
                    ]
                }
            },

            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "text": {
                                "content": data.get(
                                    "naskah",
                                    ""
                                )
                            }
                        }
                    ]
                }
            }
        ]
    )


# =========================
# 5. MAIN PROGRAM
# =========================

async def main():

    print("Memulai Simpelin Agent...")

    topic = get_trending_topic()

    print(
        f"Topik ditemukan: {topic['title']}"
    )

    script_data = generate_script(topic)

    print("Naskah berhasil dibuat oleh Gemini.")

    await generate_vo(
        script_data["naskah"]
    )

    print("Voiceover berhasil dibuat.")

    push_to_notion(
        topic["title"],
        script_data
    )

    print("Data berhasil dikirim ke Notion.")

    print("Simpelin Agent selesai.")


# =========================
# 6. JALANKAN PROGRAM
# =========================

if __name__ == "__main__":
    asyncio.run(main())
