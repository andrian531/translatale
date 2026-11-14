# Translatale

Web-based AI Novel Translator with modular per-site scrapers, multi-provider LLM routing, context-aware translation, and an integrated web reader.

## Planned Architecture

- **Backend:** Python (FastAPI, SQLite, Playwright, BeautifulSoup4)
- **Frontend:** Vue 3 + Vite + Tailwind CSS
- **LLM Routing:** Configurable API providers (Gemini, OpenAI, OpenRouter, DeepSeek, Anthropic, Custom, and optional Ollama) with separate model selection for:
  - Translation
  - Scraping / Site Analysis
  - Story & Context Analysis
- **Input Modes:** Modular per-website scrapers (`scrapers/sites/<site>.py`) and manual chapter input (paste / upload).

## Running (Phase 1)

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

