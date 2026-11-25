FROM python:3.12-slim

# Commit the image was built from; printed at startup and returned by /api/health/.
ARG APP_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings.base python manage.py collectstatic --noinput \
 && chmod +x scripts/start.sh scripts/entrypoint.sh \
 && useradd --create-home --uid 1000 app \
 && mkdir -p /app/media \
 && chown -R app:app /app/media /app/staticfiles

USER app
EXPOSE 8000

# Every start: wait for the database, migrate, seed missing content, then run the command.
# The entrypoint does this even when the hosting panel overrides the start command.
ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["./scripts/start.sh", "prod"]
