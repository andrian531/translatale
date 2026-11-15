# Translatale

Web-based AI Novel Translator with modular per-site scrapers, multi-provider LLM routing, context-aware translation, and an integrated web reader.

> **Background:** Translatale is an evolution and full rewrite of [andrian531/novel-translator](https://github.com/andrian531/novel-translator), carrying forward its context-aware, chunked, and reference-driven translation workflow onto a modern FastAPI + SQLite + Vue 3 architecture with modular per-site scrapers and multi-provider LLM routing.

## Planned Architecture

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS
- **LLM Routing:** Configurable API providers (Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom, and optional Ollama) with separate model selection for:
  - Translation
  - Scraping / Site Analysis
  - Story & Context Analysis
- **Input Modes:** Modular per-website scrapers (`scrapers/sites/<site>.py`) and manual chapter input (paste / upload).

## Key Features

- **Modular Scrapers & Batch Fetch:** Per-site scrapers (`scrapers/sites/`) with URL preview, TOC sync (`Cek Bab Baru`), and background batch fetching with rate-limit delay & circuit breaker.
- **Multi-Provider LLM Routing:** Configure Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom OpenAI-compatible APIs, or Ollama, with separate model routing for **Translate**, **Scraping / Site Analysis**, and **Story & Context Analysis**.
- **Story Analysis & Reference Sheet:**
  - Extracts **Characters** (name, romanization, gender, age, aliases/nicknames, relationships, notes), **Terms / Glossary**, **Locations**, and **Translation Guide** (with `target_lang`-aware glossary & location targets).
  - Supports **Cara Baca (Latin)** and a per-row **Latin** toggle (`Latin (Terjemahan)`, e.g. `Dantian (Pusat Energi)`) on both Terms and Locations.
  - **Terapkan ke Bab Terjemahan:** Aligns already-translated chapters with updated character/glossary/location settings via background job.
- **Context-Aware Chunked Translation:**
  - Splits long chapters at paragraph/sentence boundaries, injects the reference sheet + rolling chapter summaries (`STORY SO FAR`) + previous chunk tail, retries failed/empty chunks (up to 3x), and stops on chapter failure to preserve context continuity.
  - Warns when translating later chapters before earlier chapters are translated, and supports **Auto-update referensi** per chapter.
  - **Hapus Terjemahan / Reset TL:** Clears translated output and resets status back to `raw` without deleting the chapter or `raw_content`.
- **Web Reader & Export:** Integrated reader with theme/font controls, reading progress tracking, and `.txt` / `.epub` export.

## Running

**Quick Start (Windows):**

Double-click `start.bat` (atau jalankan `.\start.bat` di terminal). Script ini otomatis:
- Membuat `backend\.venv` dan menginstall `requirements.txt` (saat pertama kali atau jika ada update)
- Menginstall `frontend\node_modules` via `npm` (saat pertama kali atau jika `package.json` berubah)
- Menjalankan backend (`8000`) & frontend (`5173`) dalam **1 window** dengan prefix log `[BE]` dan `[FE]`, lalu membuka `http://localhost:5173` di browser

Untuk menghentikan kedua server, cukup tekan `Ctrl+C` atau tutup window `start.bat` (atau jalankan `stop.bat` jika perlu membersihkan proses yang tersisa).

**Manual Setup:**

**Backend** (Python 3.10+):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs · health: http://127.0.0.1:8000/api/health

**Frontend** (Node 18+):

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`, so run both.

**Tests:**

```bash
cd backend
.venv\Scripts\python -m pytest
```

The SQLite database is created automatically at `backend/data/translatale.db`
(override with `TRANSLATALE_DB_PATH` / `TRANSLATALE_DATA_DIR`).

