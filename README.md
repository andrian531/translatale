# Translatale — AI Web Novel & Light Novel Translator

**Language:** English | [Bahasa Indonesia](README.id.md)

**Translatale** (*Translate* + *Tale*) is an open-source, self-hosted **AI Novel Translator** and **Web Novel Reader** built for translating Chinese, Japanese, and Korean web novels / light novels (raws) with consistent character names, glossaries, and story context—powered by **Gemini, OpenAI, DeepSeek, OpenRouter, Anthropic, Ollama, or any OpenAI-compatible LLM**.

Whether you want to scrape raw chapters automatically, maintain a persistent story bible, generate book cover prompts, or export polished `.epub`, `.pdf`, and `.txt` books (with cover image) for offline reading, Translatale brings the entire workflow into one clean web app.

> **Background:** Translatale is an evolution and full rewrite of [andrian531/novel-translator](https://github.com/andrian531/novel-translator), carrying forward its context-aware, chunked, and reference-driven translation workflow onto a modern FastAPI + SQLite + Vue 3 architecture with modular per-site scrapers, multi-provider LLM routing, and a bilingual Dark/Light UI.

## Why Translatale?

- **Consistent Names & Terminology:** Automatic AI story analysis builds a living **Reference Sheet** (characters, aliases, relationships, locations, terms, and translation guide) that is injected into every translation prompt.
- **Zero-Cost Lock-in & Multi-LLM Routing:** Mix and match any LLM provider per task—including a **Default Provider & Model** fallback and an optional **Secondary Fallback Model** (e.g., an uncensored model) when primary models refuse or fail.
- **Built for Long Novels (100+ Chapters):** Background jobs with real-time SSE logs, one-click **Translate Next (5)**, **5-way parallel Apply Reference**, paginated & searchable chapter tables, and `.epub` / `.pdf` / `.txt` / `.json` export.

## Architecture

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS (English / Indonesian UI + Dark / Light global theme)
- **LLM Routing:** Configurable providers (**Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom OpenAI-compatible, Ollama**) with **Test & Get Model List** credential preview, a **Default Provider / Default Model** fallback, and separate primary + secondary fallback routing for 4 tasks:
  - `translate` — Chapter & title translation
  - `scrape_analysis` — Site / HTML structure analysis
  - `story_analysis` — Story & reference extraction
  - `cover_prompt` — Book cover image prompt generation
- **Input Modes:** Modular per-website scrapers (`scrapers/sites/<site>.py`) and manual chapter input (paste or `.txt` upload).

## Key Features

- **Modular Scrapers & Batch Fetch:** Per-site scrapers (`scrapers/sites/`) with URL preview, TOC sync (*Check for New Chapters*), clickable novel/chapter source URLs, and background batch fetching with rate-limit delay & circuit breaker.
- **Multi-Provider LLM Routing & Fallback:**
  - Set a **Default Provider & Default Model** so unconfigured task slots still work out of the box.
  - Optional **Fallback Model** per task automatically takes over if the primary model fails, returns empty output, refuses due to content filters, or produces invalid JSON.
- **Story Analysis & Living Reference Sheet:**
  - Extracts **Characters** (source name, romanization, gender, age, aliases/nicknames, relationships, notes), **Terms / Glossary**, **Locations**, and **Translation Guide** (with `target_lang`-aware glossary & location targets).
  - Supports **Romanized reading (Latin)** and a per-row **Latin** toggle (`Latin (Translation)`, e.g. `Dantian (Energy Core)`) on both Terms and Locations.
  - **5-Way Parallel Apply Reference:** Aligns already-translated chapters with updated character, glossary, and location settings concurrently (up to 5 chapters at once).
- **Context-Aware Chunked Translation:**
  - Splits long chapters cleanly at paragraph/sentence boundaries, injects the reference sheet + rolling chapter summaries (`STORY SO FAR`) + previous chunk tail, retries failed/empty chunks, and stops on chapter failure to preserve context continuity.
  - **Translate Next (5):** One-click continuation of the next 5 untranslated chapters right after your last translated chapter.
  - Warns before translating later chapters out of order, supports per-chapter **Auto-update reference**, and includes **Clear Translation / Reset TL** without deleting `raw_content`.
  - Automatic **SSE job resume** when returning to Workspace, detailed step-by-step logs, and startup cleanup for interrupted jobs.
- **Novel Cover Thumbnail & AI Cover Prompt Generator:**
  - Upload a custom **2:3 cover thumbnail** (PNG/JPG/WebP) displayed in Library cards and the Workspace header.
  - Generate detailed **2:3 Cover Image Prompts** from your novel's synopsis and reference sheet in two ready-to-use formats: **Positive + Negative Prompt** and structured **JSON Prompt**.
- **Workspace Chapter Table & Web Reader:**
  - Fast client-side **pagination** (`25/50/100/200`), **quick search** by chapter `#` or title, **column sorting**, responsive icon/text action buttons, and safety-locked chapter `Source URL` editing.
  - Integrated **Web Reader** with independent Dark / Sepia / Light reading themes, font controls, reading progress tracking, and one-click export to **`.epub`**, **`.pdf`** (with full-page cover & per-chapter page breaks), **`.txt`**, and **`.json`** backup.

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
