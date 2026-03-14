FROM python:3.11-slim

# ── System dependencies ───────────────────────────────────────────────────────
# ffmpeg: audio/video processing (TTS mixing, video generation, RTMP streaming)
# libxml2/libxslt: lxml → newspaper3k article scraping
# libjpeg/zlib: Pillow image processing
# build-essential: compile C extensions (datasketch, lxml, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies (separate layer for cache efficiency) ─────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Persistent data directories ───────────────────────────────────────────────
# These are declared as VOLUME mount points — created here so they exist
# even when not mounted externally.
RUN mkdir -p database video/output video/assets channel_assets

EXPOSE 8000

CMD ["python", "main.py"]
