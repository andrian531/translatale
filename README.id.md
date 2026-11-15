# Translatale — Penerjemah Novel & Light Novel AI Berbasis Web

**Bahasa:** [English](README.md) | Bahasa Indonesia

**Translatale** (*Translate* + *Tale*) adalah aplikasi **penerjemah novel AI** dan **web reader** open-source yang berjalan lokal untuk menerjemahkan web novel / light novel Mandarin, Jepang, dan Korea dengan nama karakter, glosarium, dan alur cerita yang konsisten—didukung oleh **Gemini, OpenAI, DeepSeek, OpenRouter, Anthropic, Ollama, maupun API OpenAI-compatible lainnya**.

Mulai dari mengambil bab otomatis (*scraping*), menyusun lembar referensi cerita, membuat prompt ilustrasi cover novel, hingga mengekspor buku siap baca ke format `.epub`, `.pdf`, dan `.txt` (lengkap dengan cover), semuanya tersedia dalam satu antarmuka web modern.

> **Latar Belakang:** Translatale merupakan pengembangan dan penulisan ulang dari [andrian531/novel-translator](https://github.com/andrian531/novel-translator), meneruskan alur kerja terjemahan berbasis konteks, pemecahan chunk, dan referensi cerita ke atas arsitektur modern FastAPI + SQLite + Vue 3 dengan scraper modular per situs, routing LLM multi-provider, serta UI dwibahasa (EN/ID) bertema Gelap/Terang.

## Kenapa Translatale?

- **Nama & Istilah Konsisten:** Analisa cerita AI otomatis membangun **Lembar Referensi** hidup (karakter, julukan, relasi, lokasi, istilah/glosarium, dan panduan gaya bahasa) yang disuntikkan ke setiap prompt terjemahan.
- **Bebas Pilih Banyak LLM:** Gunakan provider/model berbeda untuk tiap proses—lengkap dengan **Default Provider & Model** otomatis serta **Model Cadangan (*Fallback*)** opsional (mis. model *uncensored*) saat model utama menolak atau gagal.
- **Nyaman untuk Novel Panjang (Ratusan Bab):** Job latar belakang dengan log SSE detail, tombol sekali klik **Translate Berikutnya (5)**, **Apply Reference paralel 5 bab sekaligus**, tabel bab dengan pencarian & pagination, serta ekspor `.epub` / `.pdf` / `.txt` / `.json`.

## Arsitektur

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS (UI Bahasa Inggris / Indonesia + Tema Gelap / Terang)
- **Routing LLM:** Dukungan multi-provider (**Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom OpenAI-compatible, Ollama**) dengan tombol **Test & Ambil Daftar Model** sebelum simpan, fallback **Default Provider / Model**, serta routing utama + cadangan terpisah untuk 4 slot proses:
  - `translate` — Terjemahan isi & judul bab
  - `scrape_analysis` — Analisa struktur situs / HTML
  - `story_analysis` — Analisa cerita & ekstraksi referensi
  - `cover_prompt` — Generator prompt gambar cover novel
- **Mode Input:** Scraper modular per situs (`scrapers/sites/<site>.py`) dan input bab manual (paste atau upload `.txt`).

## Fitur Utama

- **Scraper Modular & Batch Fetch:** Scraper per situs (`scrapers/sites/`) dengan pratinjau URL, sinkronisasi daftar bab (*Cek Bab Baru*), tautan URL sumber novel/bab yang dapat diklik, serta pengambilan massal di latar belakang dengan jeda rate-limit dan *circuit breaker*.
- **Routing LLM Multi-Provider & Model Cadangan:**
  - Atur **Default Provider & Model** agar slot proses yang belum diisi tetap langsung bisa dipakai.
  - **Model Cadangan** opsional otomatis mengambil alih saat model utama gagal, kosong, menolak konten, atau menghasilkan JSON analisa yang tidak valid.
- **Analisa Cerita & Lembar Referensi:**
  - Mengekstrak **Karakter** (nama asli, romanisasi, gender, usia, julukan/alias, relasi, catatan), **Terms / Glossary**, **Lokasi**, dan **Translation Guide** (target istilah & lokasi mengikuti `target_lang` novel).
  - Mendukung kolom **Cara Baca (Latin)** dan toggle **Latin** per baris (`Latin (Terjemahan)`, contoh: `Dantian (Pusat Energi)`) pada Terms dan Locations.
  - **Apply Reference Paralel 5×:** Menyelaraskan bab yang sudah diterjemahkan agar mengikuti pembaruan karakter, glosarium, dan lokasi secara paralel hingga 5 bab sekaligus.
- **Terjemahan Chunk Sadar-Konteks:**
  - Memecah bab panjang di batas paragraf/kalimat, menyuntikkan lembar referensi + ringkasan bab bergulir (`STORY SO FAR`) + akhir chunk sebelumnya, melakukan retry otomatis, dan menghentikan batch bila ada bab gagal agar konteks tidak terputus.
  - **Translate Berikutnya (5):** Menerjemahkan 5 bab berikutnya setelah bab terakhir yang sudah diterjemahkan hanya dengan satu klik.
  - Peringatan saat menerjemahkan melompati bab, dukungan **Auto-update referensi** per bab, dan **Hapus Terjemahan / Reset TL** tanpa menghapus teks sumber (`raw_content`).
  - **Auto-resume stream SSE** saat kembali ke Workspace, log langkah yang detail, dan pembersihan job terputus saat server startup.
- **Thumbnail Cover Novel & Generator Prompt Cover AI:**
  - Upload **thumbnail cover 2:3** (PNG/JPG/WebP) yang tampil di kartu Library dan header Workspace.
  - Buat **Prompt Gambar Cover 2:3** yang detail dari sinopsis & referensi cerita dalam 2 format siap pakai: **Positive + Negative Prompt** dan **JSON Prompt** terstruktur.
- **Tabel Bab Workspace & Web Reader:**
  - **Pagination** (`25/50/100/200`), **pencarian cepat** nomor/judul bab, **sorting kolom**, tombol aksi responsif (ikon/teks), serta edit `URL Sumber` per bab dengan checkbox pengaman.
  - **Web Reader** terintegrasi dengan tema baca independen (Gelap / Sepia / Terang), pengaturan font, pelacakan progres baca, serta ekspor ke **`.epub`**, **`.pdf`** (dengan halaman cover & bab dimulai di halaman baru), **`.txt`**, dan backup **`.json`**.

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
