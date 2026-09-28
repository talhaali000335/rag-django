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

RUN SECRET_KEY=dummy-build-key python manage.py collectstatic --noinput --settings=config.settings.base || true

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=2 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# 1 worker only — saves ~400MB RAM
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "1", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]