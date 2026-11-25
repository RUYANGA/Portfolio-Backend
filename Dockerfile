FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings.base python manage.py collectstatic --noinput \
 && chmod +x scripts/start.sh \
 && useradd --create-home --uid 1000 app \
 && mkdir -p /app/media \
 && chown -R app:app /app/media /app/staticfiles

USER app
EXPOSE 8000

# Waits for the database, migrates, seeds missing content, then starts gunicorn.
CMD ["./scripts/start.sh", "prod"]
