# Backend – Django API

Content API for the portfolio site and its admin dashboard.

| Endpoint | Purpose |
|---|---|
| `GET /api/portfolio/` | All homepage content in one request |
| `GET /api/profile/` | Small payload for the live API panel in the hero |
| `GET /api/projects/<slug>/` | One project |
| `POST /api/contact/` | Contact form (validated, spam honeypot, 5 per hour per visitor) |
| `GET /api/health/` | Health check, including the database |
| `/api/admin/…` | Staff-only API used by the Next.js dashboard (token auth, 7-day sign-ins) |
| `/media/…` | Uploaded images and the résumé |

## Structure

```
backend/
├── src/
│   ├── apps/
│   │   └── portfolio/
│   │       ├── api/
│   │       │   ├── public/        serializers.py, views.py, urls.py   → /api/...
│   │       │   └── admin/         auth.py, serializers.py, views.py, urls.py   → /api/admin/...
│   │       ├── management/commands/   seed_portfolio, wait_for_db, ensure_superuser
│   │       ├── migrations/
│   │       ├── tests/             base.py + test_seed, test_public_api, test_admin_api, test_startup
│   │       ├── models.py          content models
│   │       ├── admin.py           Django admin (emergency use only)
│   │       └── media.py           public URLs for uploaded files
│   └── config/
│       ├── settings/
│       │   ├── base.py            shared settings, read from the environment
│       │   ├── development.py     DEBUG on (manage.py default)
│       │   ├── production.py      DEBUG off, HTTPS, refuses a placeholder secret (Docker default)
│       │   └── test.py            used automatically by `manage.py test`
│       ├── urls.py
│       ├── wsgi.py                gunicorn entry point
│       └── asgi.py
├── seed/                          portfolio.json + media/ (starting content, images, résumé)
├── scripts/start.sh               wait for DB → migrate → seed → create admin → serve
├── manage.py                      adds src/ to the path
├── Dockerfile                     runs as a non-root user with production settings
├── docker-compose.yml             PostgreSQL + API
├── .github/workflows/ci.yml       lint → tests → Docker build/push
├── .pre-commit-config.yaml        black, isort, flake8, mypy + hygiene hooks
├── pyproject.toml  .flake8        lint, formatting and type-checking settings
├── requirements.txt               runtime dependencies
└── requirements-dev.txt           + pre-commit, black, isort, flake8, mypy and stubs
```

New Django apps go in `src/apps/<name>/` and are registered as `apps.<name>` in
`src/config/settings/base.py`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db              # PostgreSQL on localhost:5434
./scripts/start.sh dev               # waits for the DB, migrates, seeds, runs on :8000
python manage.py createsuperuser     # once, to sign in to the dashboard
python manage.py test apps           # run the tests
pre-commit run --all-files           # lint (after: pip install -r requirements-dev.txt)
```

## Code quality

```bash
pip install -r requirements-dev.txt
pre-commit install            # checks run automatically on every commit
pre-commit run --all-files    # run them on everything now
```

Hooks: Black (formatting), isort (imports), Flake8 with Bugbear (lint), mypy with the Django and
DRF plugins (types: it knows your models' fields and querysets), plus whitespace, YAML/TOML,
merge-conflict, private-key and large-file checks. Settings: `pyproject.toml`, `.flake8`.

Run the type checker on its own with `mypy` (it reads `pyproject.toml`).

## CI/CD (GitHub Actions)

Two workflows in `.github/workflows/`:

**`ci.yml` – every pull request** (no credentials, nothing published)

| Job | What it does |
|---|---|
| **Lint** | All pre-commit hooks: Black, isort, Flake8, mypy and the hygiene checks |
| **Tests** | Django checks, migrations up to date, the test suite on PostgreSQL 16, production settings refuse a placeholder secret |
| **Docker image (build check)** | Builds the production image to prove the Dockerfile works |

Each job runs only if the previous one passed.

**`release.yml` – merge to `main`** (and version tags)

Builds the image and pushes it to Docker Hub as `latest` and `sha-<commit>`. Pushing a tag such as
`v1.2.0` also publishes `1.2.0` and `1.2`. A first step checks the credentials and names any that
are missing. The job runs in a `production` environment, where you can add required reviewers
(**Settings → Environments**) if releases should need approval.

Setup, once (**Settings → Secrets and variables → Actions**):

| Kind | Name | Value |
|---|---|---|
| Secret | `DOCKERHUB_USERNAME` | your Docker Hub username |
| Secret | `DOCKERHUB_TOKEN` | a Docker Hub access token (Account settings → Personal access tokens, Read & Write) |
| Variable | `DOCKERHUB_REPOSITORY` | optional, defaults to `<username>/merci-portfolio-api` |

Credentials must be **Secrets**, not Variables: variables are stored and shown in plain text.

**Dependabot** (`.github/dependabot.yml`) opens grouped pull requests every Monday for Python
packages, GitHub Actions and the Docker base image; they go through CI like any other change.

Recommended: in **Settings → Branches**, protect `main` and require the *Lint*, *Tests* and
*Docker image (build check)* checks before merging.

## Deploy to a Hostinger server (Docker)

Requires Docker with the Compose plugin on the server.

```bash
git clone <your repo> && cd merci-portfolio/backend
cp .env.example .env
nano .env                            # fill in the production values below
docker compose up -d --build
docker compose ps                    # api and db should show (healthy)
```

Production values in `.env`:

| Setting | Example |
|---|---|
| `DJANGO_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `POSTGRES_PASSWORD` | a strong random value |
| `DJANGO_ALLOWED_HOSTS` | `api.ruyanga.tech` |
| `PUBLIC_URL` | `https://api.ruyanga.tech` |
| `CORS_ALLOWED_ORIGINS` | `https://ruyanga.tech,https://www.ruyanga.tech` |
| `CORS_ALLOWED_ORIGIN_REGEXES` | optional, for Vercel previews: `^https://merci-portfolio-[a-z0-9-]+\.vercel\.app$` |
| `DJANGO_SUPERUSER_USERNAME` / `PASSWORD` / `EMAIL` | your dashboard login, created on first start |

**HTTPS is required.** The Vercel site is served over HTTPS, and browsers block plain-HTTP
images and form posts from it. Point `api.your-domain` at the server and put a reverse proxy
with a certificate in front of port `API_PORT` (8000), for example Nginx with Certbot.
If you use Nginx, allow résumé and image uploads with `client_max_body_size 10m;`.

On every start the container waits for the database, applies migrations, seeds missing
content (never overwriting dashboard edits) and creates the admin account if it's set.
It refuses to start with a missing or placeholder `DJANGO_SECRET_KEY`.

### Updating

With the image CI publishes (set `API_IMAGE=<username>/merci-portfolio-api:latest` in `.env`):

```bash
docker compose pull api && docker compose up -d --no-build
```

To roll back, set `API_IMAGE` to an earlier `sha-<commit>` tag and run the same command.
Without `API_IMAGE`, build from source instead: `git pull && docker compose up -d --build`.

The database (`pgdata`) and uploads (`media`) live in Docker volumes and survive rebuilds.
Back them up with:

```bash
docker compose exec db pg_dump -U portfolio portfolio > backup.sql
docker run --rm -v merci-portfolio_media:/media -v "$PWD":/out alpine tar czf /out/media.tgz -C /media .
```

## Seed data

`seed/portfolio.json` holds the starting content; `seed/media/` holds its images and the résumé.

| Command | Effect |
|---|---|
| `python manage.py seed_portfolio` | Add anything missing, restore lost seed images. Never overwrites dashboard edits. Runs on every start. |
| `python manage.py seed_portfolio --update` | Overwrite existing records with the seed values. |
| `python manage.py seed_portfolio --reset` | Delete all portfolio content and reload it (contact messages are kept). |

## Contact-form emails (optional)

Set `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `CONTACT_NOTIFY_EMAIL`
(for Gmail, use an App Password). Without them, messages are still saved and shown in the
dashboard inbox.

## Emergency access

Django's built-in admin is off. Set `DJANGO_ADMIN_ENABLED=true` to reach it at `/django-admin/`.
