# Translatale

**Bahasa:** [English](README.md) | Bahasa Indonesia

Penerjemah Novel AI berbasis web dengan scraper modular per situs, routing LLM multi-provider, terjemahan sadar-konteks, dan web reader terintegrasi.

> **Latar Belakang:** Translatale merupakan pengembangan dan penulisan ulang dari [andrian531/novel-translator](https://github.com/andrian531/novel-translator), meneruskan alur kerja terjemahan berbasis konteks, pemecahan chunk, dan referensi cerita ke atas arsitektur modern FastAPI + SQLite + Vue 3 dengan scraper modular per situs serta routing LLM multi-provider.

## Arsitektur

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS
- **Routing LLM:** Dukungan multi-provider (Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom OpenAI-compatible, dan Ollama opsional) dengan pemilihan model utama dan model cadangan (*fallback*) terpisah untuk:
  - Translate (Penerjemahan)
  - Scraping / Analisa Situs
  - Analisa Cerita & Konteks
- **Mode Input:** Scraper modular per situs (`scrapers/sites/<site>.py`) dan input bab manual (paste / upload `.txt`).

## Fitur Utama

- **Scraper Modular & Batch Fetch:** Scraper per situs (`scrapers/sites/`) dengan pratinjau URL, sinkronisasi daftar bab (*Cek Bab Baru*), serta pengambilan massal di latar belakang dengan jeda rate-limit dan *circuit breaker*.
- **Routing LLM Multi-Provider & Model Cadangan (Fallback):** Atur provider/model berbeda untuk tiap proses, ditambah **Model Cadangan** opsional (misalnya model *uncensored*) yang otomatis mengambil alih saat model utama gagal, mengembalikan respons kosong, menolak karena filter konten, atau menghasilkan JSON analisa yang tidak valid.
- **Analisa Cerita & Lembar Referensi:**
  - Mengekstrak **Karakter** (nama asli, romanisasi, gender, usia, julukan/alias, relasi antar karakter, catatan), **Terms / Glossary**, **Lokasi**, dan **Translation Guide** (dengan target istilah & lokasi mengikuti `target_lang` novel).
  - Mendukung kolom **Cara Baca (Latin)** dan toggle **Latin** per baris (`Latin (Terjemahan)`, contoh: `Dantian (Pusat Energi)`) pada Terms dan Locations.
  - **Terapkan ke Bab Terjemahan:** Menyelaraskan bab yang sudah diterjemahkan agar mengikuti pengaturan karakter, glosarium, dan lokasi terbaru lewat background job.
- **Terjemahan Chunk Sadar-Konteks:**
  - Memecah bab panjang di batas paragraf/kalimat, menyuntikkan lembar referensi + ringkasan bab bergulir (`STORY SO FAR`) + akhir chunk sebelumnya, melakukan retry otomatis (hingga 3x) untuk chunk gagal/kosong, dan menghentikan batch bila ada bab gagal agar konteks tidak terputus.
  - Memberi peringatan saat menerjemahkan bab lanjutan sebelum bab sebelumnya diterjemahkan, serta mendukung **Auto-update referensi** per bab.
  - **Hapus Terjemahan / Reset TL:** Menghapus hasil terjemahan dan mengembalikan status bab ke `raw` tanpa menghapus bab maupun teks sumber (`raw_content`).
- **Web Reader & Ekspor:** Reader terintegrasi dengan pengaturan tema/font, pelacakan progres baca, dan ekspor `.txt` / `.epub`.

## Menjalankan Aplikasi

**Cara Cepat (Windows):**

Klik dua kali `start.bat` (atau jalankan `.\start.bat` di terminal). Script ini otomatis:
- Membuat `backend\.venv` dan menginstall `requirements.txt` (saat pertama kali atau jika ada pembaruan)
- Menginstall `frontend\node_modules` via `npm` (saat pertama kali atau jika `package.json` berubah)
- Menjalankan backend (`8000`) dan frontend (`5173`) dalam **1 window** dengan prefix log `[BE]` dan `[FE]`, lalu membuka `http://localhost:5173` di browser

Untuk menghentikan kedua server, cukup tekan `Ctrl+C` atau tutup window `start.bat` (atau jalankan `stop.bat` jika perlu membersihkan proses yang tersisa).

**Setup Manual:**

**Backend** (Python 3.10+):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Dokumentasi API: http://127.0.0.1:8000/docs · health: http://127.0.0.1:8000/api/health

**Frontend** (Node 18+):

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Dev server Vite meneruskan `/api` ke `http://127.0.0.1:8000`, jadi jalankan keduanya.

**Pengujian (Tests):**

```bash
cd backend
.venv\Scripts\python -m pytest
```

Database SQLite dibuat otomatis di `backend/data/translatale.db`
(dapat diubah lewat `TRANSLATALE_DB_PATH` / `TRANSLATALE_DATA_DIR`).
