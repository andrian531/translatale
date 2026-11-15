# Translatale

**Language:** English | [Bahasa Indonesia](README.id.md)

**Translatale** (*Translate* + *Tale*) is a web-based AI Novel Translator with modular per-site scrapers, multi-provider LLM routing, context-aware translation, and an integrated web reader.

> **Background:** Translatale is an evolution and full rewrite of [andrian531/novel-translator](https://github.com/andrian531/novel-translator), carrying forward its context-aware, chunked, and reference-driven translation workflow onto a modern FastAPI + SQLite + Vue 3 architecture with modular per-site scrapers and multi-provider LLM routing.

## Architecture

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS
- **LLM Routing:** Configurable API providers (Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom OpenAI-compatible, and optional Ollama) with separate primary & optional secondary/fallback models for:
  - Translation
  - Scraping / Site Analysis
  - Story & Context Analysis
- **Input Modes:** Modular per-website scrapers (`scrapers/sites/<site>.py`) and manual chapter input (paste / `.txt` upload).

## Key Features

- **Modular Scrapers & Batch Fetch:** Per-site scrapers (`scrapers/sites/`) with URL preview, TOC sync (*Check New Chapters*), and background batch fetching with rate-limit delay & circuit breaker.
- **Multi-Provider LLM Routing & Secondary Fallback:** Assign separate providers/models per task, plus an optional **Fallback Model** (e.g., an uncensored model) that automatically takes over when the primary model fails, returns empty output, refuses due to content filters, or produces invalid analysis JSON.
- **Story Analysis & Reference Sheet:**
  - Extracts **Characters** (source name, romanization, gender, age, aliases/nicknames, relationships, notes), **Terms / Glossary**, **Locations**, and **Translation Guide** (with `target_lang`-aware glossary & location targets).
  - Supports **Romanized reading (Latin)** and a per-row **Latin** toggle (`Latin (Translation)`, e.g. `Dantian (Energy Core)`) on both Terms and Locations.
  - **Apply Reference to Translated Chapters:** Aligns already-translated chapters with updated character, glossary, and location settings via a background job.
- **Context-Aware Chunked Translation:**
  - Splits long chapters at paragraph/sentence boundaries, injects the reference sheet + rolling chapter summaries (`STORY SO FAR`) + previous chunk tail, retries failed/empty chunks (up to 3x), and stops on chapter failure to preserve context continuity.
  - Warns before translating later chapters if earlier chapters are still untranslated, and supports per-chapter **Auto-update reference**.
  - **Clear Translation / Reset TL:** Clears translated output and resets chapter status back to `raw` without deleting the chapter or its `raw_content`.
- **Web Reader & Export:** Integrated reader with theme/font controls, reading progress tracking, and `.txt` / `.epub` export.

## Running

**Quick Start (Windows):**

Double-click `start.bat` (or run `.\start.bat` in a terminal). The script automatically:
- Creates `backend\.venv` and installs `requirements.txt` (on first run or when updated)
- Installs `frontend\node_modules` via `npm` (on first run or when `package.json` changes)
- Starts both backend (`8000`) and frontend (`5173`) in **one window** with `[BE]` and `[FE]` log prefixes, then opens `http://localhost:5173` in your browser

To stop both servers, press `Ctrl+C` or close the `start.bat` window (or run `stop.bat` to clean up any remaining processes).

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
