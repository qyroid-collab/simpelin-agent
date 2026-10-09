import asyncio
import json
import os
import time
from pathlib import Path

import edge_tts
import feedparser
from google import genai
from google.genai import errors
from notion_client import Client


# ==========================================
# KONFIGURASI
# ==========================================

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATABASE_ID")
VOICE = os.getenv("EDGE_TTS_VOICE", "id-ID-ArdiNeural")
AUDIO_FILE = "vo.mp3"

REQUIRED_SECRETS = (
    "GEMINI_API_KEY",
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
)

for secret in REQUIRED_SECRETS:
    if not os.getenv(secret):
        raise RuntimeError(
            f"GitHub Secret {secret} belum diatur."
        )

gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

notion = Client(
    auth=os.getenv("NOTION_TOKEN")
)

VALID_PILARS = {
    "Kebijakan & Pemerintah",
    "Ekonomi & Harga",
    "Kejadian Daerah",
    "Viral & Konteks",
    "Bisnis & Tech",
    "Fact Check & Sumber",
    "Ekonomi Digital",
    "Bisnis Lokal",
}


# ==========================================
# 1. RADAR TREN GOOGLE
# ==========================================

def get_trending_topic():
    feed_url = (
        "https://trends.google.com/trending/rss?geo=ID"
    )

    feed = feedparser.parse(feed_url)

    for entry in getattr(feed, "entries", []):
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()

        if title:
            return {
                "title": title[:200],
                "link": link or (
                    "https://trends.google.com/trending?geo=ID"
                ),
            }

    raise RuntimeError(
        "Google Trends RSS kosong atau gagal diakses. "
        "Agent dihentikan agar tidak membuat topik palsu."
    )


# ==========================================
# 2. GENERATOR NASKAH GEMINI
# ==========================================

def generate_script(topic):
    prompt = f"""
Kamu adalah editor konten berita dan edukasi Indonesia
untuk akun Simpelin.

TOPIK TREN:
{topic["title"]}

TAUTAN TREN:
{topic["link"]}

Buat naskah video pendek maksimal 60 detik,
sekitar 100-130 kata.

GAYA:
- Bahasa Indonesia yang santai, jelas, dan tajam.
- Kalimat pendek dan mudah dibacakan.
- Struktur: Hook -> Inti -> Kenapa Penting -> Aksi/Penutup.
- Hindari clickbait yang menyesatkan.
- Jangan mengarang fakta, angka, kutipan, atau sumber.
- Tren bukan bukti bahwa suatu klaim benar.
- Jika fakta belum terverifikasi, tulis NEEDS RESEARCH
  dan jelaskan apa yang masih perlu diverifikasi.

Pilih satu pilar:
1. Kebijakan & Pemerintah
2. Ekonomi Digital
3. Bisnis Lokal

Kembalikan JSON valid dengan empat field:
{{
  "pilar": "Nama pilar",
  "fact_check": "Status dan catatan verifikasi",
  "naskah": "Naskah lengkap video",
  "caption": "Caption dan hashtag"
}}
"""

    response = None

    for attempt in range(5):
        try:
            response = gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                },
            )
            break

        except errors.ServerError as exc:
            if (
                getattr(exc, "code", None) != 503
                or attempt == 4
            ):
                raise

            delay = min(10 * (2 ** attempt), 60)

            print(
                f"Gemini sedang sibuk. "
                f"Percobaan {attempt + 1}/5, "
                f"menunggu {delay} detik."
            )

            time.sleep(delay)

    if not response or not response.text:
        raise RuntimeError(
            "Gemini tidak mengembalikan respons."
        )

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Respons Gemini bukan JSON valid."
        ) from exc

    required_fields = (
        "pilar",
        "fact_check",
        "naskah",
        "caption",
    )

    for field in required_fields:
        if (
            not isinstance(data.get(field), str)
            or not data[field].strip()
        ):
            raise ValueError(
                f"Field '{field}' kosong atau tidak valid."
            )

    # Sesuaikan nama pilar dengan opsi di Notion.
    pillar_map = {
        "Kebijakan & Pemerintah":
            "Kebijakan & Pemerintah",
        "Ekonomi Digital":
            "Ekonomi Digital",
        "Bisnis Lokal":
            "Bisnis Lokal",
    }

    data["pilar"] = pillar_map.get(
        data["pilar"],
        "Viral & Konteks",
    )

    if data["pilar"] not in VALID_PILARS:
        data["pilar"] = "Viral & Konteks"

    return data


# ==========================================
# 3. GENERATOR VOICEOVER
# ==========================================

async def generate_vo(
    text,
    output_file=AUDIO_FILE,
):
    await edge_tts.Communicate(
        text,
        VOICE,
    ).save(output_file)

    path = Path(output_file)

    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(
            "Voiceover gagal dibuat atau file kosong."
        )

    print(
        f"Voiceover berhasil dibuat: {path} "
        f"({path.stat().st_size} bytes)"
    )

    return path


# ==========================================
# 4. FORMAT TEKS UNTUK NOTION
# ==========================================

def notion_rich_text(value):
    """
    Notion membatasi satu objek teks hingga 2.000 karakter.
    Teks panjang dibagi menjadi beberapa bagian.
    """
    value = str(value or "")

    chunks = [
        value[i:i + 1900]
        for i in range(0, len(value), 1900)
    ]

    if not chunks:
        chunks = [""]

    return [
        {
            "type": "text",
            "text": {
                "content": chunk,
            },
        }
        for chunk in chunks
    ]


# ==========================================
# 5. KIRIM KONTEN KE NOTION
# ==========================================

def push_to_notion(topic, data):
    fact_check_text = (
        f'{data["fact_check"]}\n\n'
        f'Sumber tren awal: {topic["link"]}\n\n'
        "Catatan: tren menunjukkan popularitas topik, "
        "bukan bukti kebenaran informasi."
    )

    page = notion.pages.create(
        parent={
            "data_source_id": NOTION_DATA_SOURCE_ID
        },

        properties={
            "Topik / Judul": {
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": topic["title"][:2000]
                        },
                    }
                ]
            },

            "Status": {
                "select": {
                    "name": "Menunggu Approve"
                }
            },

            "Pilar Topik": {
                "select": {
                    "name": data["pilar"]
                }
            },

            "Fact Check & Sumber": {
                "rich_text": notion_rich_text(
                    fact_check_text
                )
            },

            "Paket Caption & Hashtag": {
                "rich_text": notion_rich_text(
                    data["caption"]
                )
            },

            "Tipe": {
                "rich_text": notion_rich_text(
                    "Video pendek"
                )
            },
        },

        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": notion_rich_text(
                        "Draft Naskah Simpelin"
                    )
                },
            },

            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": notion_rich_text(
                        data["naskah"]
                    )
                },
            },

            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": notion_rich_text(
                        "Informasi Voiceover"
                    )
                },
            },

            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": notion_rich_text(
                        "File vo.mp3 dibuat oleh workflow "
                        "GitHub Actions. Unduh file dari "
                        "artifact workflow jika artifact "
                        "audio sudah dikonfigurasi."
                    )
                },
            },
        ],
    )

    print(
        "Konten berhasil dikirim ke Notion: "
        f'{page.get("url", "(URL tidak tersedia)")}'
    )

    return page


# ==========================================
# 6. PROGRAM UTAMA
# ==========================================

async def main():
    print("================================")
    print("Memulai Simpelin Agent")
    print("================================")

    topic = get_trending_topic()

    print(f"Topik ditemukan: {topic['title']}")
    print(f"Sumber tren: {topic['link']}")

    script_data = generate_script(topic)

    print("Naskah, fact-check, dan caption dibuat.")

    await generate_vo(
        script_data["naskah"],
        AUDIO_FILE,
    )

    push_to_notion(
        topic,
        script_data,
    )

    print("================================")
    print("Simpelin Agent selesai.")
    print("================================")


if __name__ == "__main__":
    asyncio.run(main())
