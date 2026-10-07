FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORM_FILLER_HEADLESS=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    xvfb \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxrender1 \
    libxshmfence1 \
    libasound2 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libx11-xcb1 \
    libxext6 \
    libx11-6 \
    libxcb-dri3-0 \
    libxcb1 \
    libglib2.0-0 \
    libdbus-1-3 \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install chromium && python -m playwright install-deps chromium

COPY . .
RUN mkdir -p /app/responses && chmod +x /app/docker-entrypoint.sh

VOLUME ["/app/responses"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "app.py"]
