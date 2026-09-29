FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Cache model here inside the image
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download model during build — not at runtime
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# Your settings read DJANGO_SECRET_KEY, DATABASE_URL and REDIS_URL, so all three
# need dummy values at build time or collectstatic fails.
RUN DJANGO_SECRET_KEY=dummy-build-key \
    DATABASE_URL=sqlite:///tmp.db \
    REDIS_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput --settings=config.settings.base

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=2 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# Run migrations first, then start gunicorn (1 worker only — saves ~400MB RAM)
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --timeout 120 --access-logfile - --error-logfile -"]