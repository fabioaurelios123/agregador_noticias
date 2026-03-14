# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Brasil24 is a Portuguese-language news aggregator that automatically collects Brazilian news, generates podcast-style AI dialogue, synthesizes speech, and streams 24/7 to YouTube Live.

## Commands

### Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**System requirement**: FFmpeg must be installed for audio/video processing.

### Run the server
```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Manual operations
```bash
# Force fetch news
curl -X POST http://localhost:8000/api/admin/fetch

# Generate video for a specific article
curl -X POST http://localhost:8000/api/admin/generate/{article_id}

# Generate top N articles
curl -X POST "http://localhost:8000/api/admin/process-top?n=3"

# Simple reader mode (no AI, direct article→TTS, no video)
python run_simple_reader.py --top 5 --fetch --music

# Full channel production (batch + stream)
python run_channel.py

# System diagnostics
python diagnose.py
```

### Testing individual modules
```bash
python -m aggregator.feed_fetcher       # Test RSS fetching
python -m tts.voice_engine "Test"       # Test TTS
python python_summary_news_test.py      # Test enrichment/summarization
curl http://localhost:8000/api/health   # Check AI provider + system health
```

## Architecture

### Data Flow
```
RSS Feeds → feed_fetcher → scraper (Newspaper3K) → deduplicator (MinHash)
  → ranker → enricher (entities/sentiment/topics via AI) → SQLite DB
  → AI Pipeline: summarizer → dialogue_generator → voice_engine (edge-tts)
    → audio_mixer (FFmpeg) → compositor (MoviePy) → streamer (FFmpeg RTMP)
```

The `aggregator/scheduler.py` triggers a fetch cycle every 15 minutes via APScheduler.

### Key Module Responsibilities

- **`aggregator/`** — News collection pipeline. `enricher.py` calls AI to extract structured metadata (entities, sentiment, impact, discussion angles) from articles before DB storage.
- **`ai/client.py`** — Unified AI client that switches between `anthropic`, `ollama`, or `none` based on `AI_PROVIDER` env var. All AI calls go through this.
- **`ai/dialogue_generator.py`** — Creates 3-persona podcast scripts (Ana anchor + Carlos analyst + guest expert chosen by category) using enrichment context.
- **`tts/voice_engine.py`** — edge-tts (primary, PT-BR neural voices) with gTTS fallback. Each persona has a distinct voice defined in `config/personas.yaml`.
- **`video/compositor.py`** — MoviePy assembly: Ken Burns effect on real article images, or animated gradient + lines if no image. 1920×1080 @ 30fps.
- **`stream/scheduler.py`** — Day mode (06:00–23:00) streams new videos live; night mode replays the day's episodes.
- **`api/job_manager.py`** — Tracks background jobs (fetch, generate, stream) and broadcasts progress via WebSocket `/ws/admin`.
- **`reader/`** — Alternative pipeline that skips AI entirely: article text → TTS → audio output.

### Database Models (`database/models.py`)
- **Article** — Raw fetched articles with enrichment metadata, score, and `processed` flag
- **Episode** — Generated content: JSON script, audio/video paths, duration, `streamed` flag
- **StreamQueue** — Scheduled/played stream entries with `live`/`replay` mode
- **BatchRun** — Full batch run logs with stats

### Configuration Files
- **`.env`** — Primary configuration (AI provider, API keys, YouTube stream key, paths)
- **`config/sources.yaml`** — RSS feed URLs + weights + keyword categories
- **`config/personas.yaml`** — Anchor/guest personas with names, roles, edge-tts voices, colors
- **`config/schedule.yaml`** — Stream hours, video resolution/duration limits, articles-per-cycle

### AI Provider Modes
Set via `AI_PROVIDER` in `.env`:
- `anthropic` — Claude API (requires `ANTHROPIC_API_KEY`)
- `ollama` — Local Ollama (requires `OLLAMA_BASE_URL` + `OLLAMA_MODEL`)
- `none` — No AI: skips summarization, uses template-based fallback dialogues

### API Endpoints
- `GET /api/news/top?n=10`, `GET /api/news`, `GET /api/news/{id}`
- `GET /api/health`, `GET /api/stream/status`
- `POST /api/admin/fetch`, `/admin/generate/{id}`, `/admin/process-top?n=3`, `/admin/start-stream`, `/admin/stop-stream`
- `GET /api/reader/top`, `POST /api/reader/generate`
- `WS /ws/news` — real-time article updates; `WS /ws/admin` — job progress

### Frontend (`frontend/`)
CNN-style dark theme dashboard at `http://localhost:8000`. `app.js` maintains WebSocket connections to both `/ws/news` and `/ws/admin` for live updates without polling.
