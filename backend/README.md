# Universal AI Web Scraper - Backend

Django REST Framework backend for the Universal AI Web Scraper application.

## Features

- **Django REST Framework** - RESTful API architecture
- **PostgreSQL** - Robust database for storing jobs, runs, and scraped data
- **JWT Authentication** - Secure token-based authentication
- **Celery** - Distributed task queue for scheduled scraping
- **Crawl4AI & Playwright** - Advanced web scraping with JavaScript rendering support
- **AI Schema Generation** - Automatic extraction schema inference using LLMs (OpenAI/Anthropic)
- **Robots.txt Compliance** - Respects website scraping policies
- **Rate Limiting** - Per-domain request throttling
- **Data Export** - CSV, JSON, and Excel export capabilities

## Tech Stack

- **Python 3.11+**
- **Django 5.0**
- **Django REST Framework 3.14**
- **PostgreSQL 15**
- **Redis 7** (for Celery)
- **Celery 5.3** with Beat scheduler
- **Playwright** for browser automation
- **OpenAI/Anthropic** APIs for AI features

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 15+
- Redis 7+
- Node.js (for Playwright)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd super_scraper/backend
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

### 5. Set up environment variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DATABASE_URL=postgresql://scraper_user:scraper_pass@localhost:5432/scraper_db

# Celery/Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# AI APIs
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
```

### 6. Set up database

Create PostgreSQL database:

```bash
createdb scraper_db
```

Or using psql:

```sql
CREATE DATABASE scraper_db;
CREATE USER scraper_user WITH PASSWORD 'scraper_pass';
GRANT ALL PRIVILEGES ON DATABASE scraper_db TO scraper_user;
```

### 7. Run migrations

```bash
python manage.py migrate
```

### 8. Create superuser

```bash
python manage.py createsuperuser
```

### 9. Collect static files

```bash
python manage.py collectstatic --noinput
```

## Running the Application

### Development Server

Start the Django development server:

```bash
python manage.py runserver
```

The API will be available at `http://localhost:8000`

### Celery Worker

In a separate terminal, start the Celery worker:

```bash
celery -A config worker -l info
```

### Celery Beat (Scheduler)

In another terminal, start Celery Beat for scheduled tasks:

```bash
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Celery Flower (Optional - Monitoring)

For task monitoring:

```bash
celery -A config flower --port=5555
```

Access Flower at `http://localhost:5555`

## Docker Deployment

### Using Docker Compose (Recommended)

From the project root directory:

```bash
docker-compose up -d
```

This will start:
- PostgreSQL database
- Redis
- Django backend
- Celery worker
- Celery beat
- Flower (monitoring)

### Individual Docker Build

```bash
cd backend
docker build -t scraper-backend .
docker run -p 8000:8000 scraper-backend
```

## API Documentation

### Authentication Endpoints

- `POST /api/auth/register/` - Register new user
- `POST /api/auth/login/` - Login and get JWT tokens
- `POST /api/auth/token/refresh/` - Refresh access token
- `POST /api/auth/logout/` - Logout
- `GET /api/auth/me/` - Get current user profile
- `PUT /api/auth/me/update/` - Update user profile
- `POST /api/auth/me/change-password/` - Change password

### Scraping Job Endpoints

- `GET /api/scraper/jobs/` - List all jobs
- `POST /api/scraper/jobs/` - Create new job
- `GET /api/scraper/jobs/{id}/` - Get job details
- `PUT /api/scraper/jobs/{id}/` - Update job
- `DELETE /api/scraper/jobs/{id}/` - Delete job
- `POST /api/scraper/jobs/{id}/run/` - Run job immediately
- `POST /api/scraper/jobs/{id}/pause/` - Pause scheduled job
- `POST /api/scraper/jobs/{id}/activate/` - Activate paused job
- `PUT /api/scraper/jobs/{id}/schedule/` - Update job schedule
- `GET /api/scraper/jobs/{id}/runs/` - Get job run history
- `GET /api/scraper/jobs/{id}/items/` - Get scraped items
- `POST /api/scraper/jobs/{id}/export/` - Export data (CSV/JSON/Excel)
- `GET /api/scraper/jobs/statistics/` - Get overall statistics

### Job Run Endpoints

- `GET /api/scraper/runs/` - List all runs
- `GET /api/scraper/runs/{id}/` - Get run details
- `POST /api/scraper/runs/{id}/cancel/` - Cancel running job
- `GET /api/scraper/runs/{id}/items/` - Get items from run

### Scraped Items Endpoints

- `GET /api/scraper/items/` - List scraped items (paginated)
- `GET /api/scraper/items/{id}/` - Get item details

### AI & Testing Endpoints

- `POST /api/scraper/test-selectors/` - Test CSS selectors on a URL
- `POST /api/scraper/ai-generate-schema/` - Generate schema using AI
- `GET /api/scraper/task-status/{task_id}/` - Check Celery task status

### Health Check

- `GET /api/health/` - System health check

## Configuration Examples

### Visual Selector Job

```json
{
  "name": "Product Scraper",
  "description": "Scrape products from e-commerce site",
  "mode": "visual",
  "configuration": {
    "urls": ["https://example.com/products"],
    "selectors": {
      "container": ".product-card",
      "fields": {
        "title": {
          "selector": "h2.product-title",
          "attr": "text",
          "type": "string"
        },
        "price": {
          "selector": ".price",
          "attr": "text",
          "type": "number"
        },
        "image": {
          "selector": "img",
          "attr": "src",
          "type": "url"
        },
        "url": {
          "selector": "a.product-link",
          "attr": "href",
          "type": "url"
        }
      }
    },
    "pagination": {
      "type": "selector",
      "next_selector": "a.next-page"
    }
  },
  "use_js_rendering": false,
  "max_pages": 10,
  "rate_limit": 1.0
}
```

### Schedule Configuration

```json
{
  "is_scheduled": true,
  "schedule_config": {
    "type": "interval",
    "interval_value": 24,
    "interval_unit": "hours"
  }
}
```

Or with CRON:

```json
{
  "is_scheduled": true,
  "schedule_config": {
    "type": "cron",
    "cron_expression": "0 0 * * *"
  }
}
```

### AI Schema Generation Request

```json
{
  "urls": ["https://example.com/jobs"],
  "scrape_prompt": "Extract all job postings with title, company, location, salary, and apply link",
  "use_js_rendering": false
}
```

## Project Structure

```
backend/
├── config/                 # Django configuration
│   ├── __init__.py
│   ├── settings.py        # Main settings
│   ├── urls.py            # URL routing
│   ├── wsgi.py            # WSGI config
│   └── celery.py          # Celery config
├── apps/
│   ├── authentication/    # User authentication
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── views.py
│   │   └── urls.py
│   ├── core/              # Core utilities
│   │   ├── models.py      # Base models
│   │   ├── utils.py       # Utility functions
│   │   └── views.py
│   └── scraper/           # Main scraping app
│       ├── models.py      # ScrapeJob, JobRun, ScrapedItem
│       ├── serializers.py
│       ├── views.py       # API views
│       ├── urls.py
│       ├── tasks.py       # Celery tasks
│       ├── scraping_engine.py        # Crawl4AI/Playwright
│       ├── ai_schema_generator.py    # AI integration
│       ├── signals.py
│       └── admin.py
├── logs/                  # Application logs
├── staticfiles/          # Static files
├── media/                # Uploaded files
├── requirements.txt      # Python dependencies
├── Dockerfile           # Docker build file
├── .env.example         # Environment template
└── manage.py            # Django management script
```

## Testing

Run tests:

```bash
pytest
```

With coverage:

```bash
pytest --cov=apps
```

## Troubleshooting

### Playwright Installation Issues

If Playwright browsers fail to install:

```bash
playwright install-deps
playwright install chromium
```

### Database Connection Issues

Verify PostgreSQL is running:

```bash
sudo service postgresql status
```

Test connection:

```bash
psql -U scraper_user -d scraper_db -h localhost
```

### Celery Not Processing Tasks

Check Redis connection:

```bash
redis-cli ping
```

Verify Celery worker is running:

```bash
celery -A config inspect active
```

### Permission Issues

Ensure proper permissions for logs and media directories:

```bash
chmod -R 755 logs media
```

## Production Deployment

### Environment Variables

Set these in production:

```env
DEBUG=False
DJANGO_SECRET_KEY=<strong-random-secret>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DATABASE_URL=postgresql://user:pass@prod-db:5432/db
CELERY_BROKER_URL=redis://prod-redis:6379/0
```

### Security Checklist

- ✅ Set strong `DJANGO_SECRET_KEY`
- ✅ Set `DEBUG=False`
- ✅ Configure `ALLOWED_HOSTS`
- ✅ Use HTTPS (SSL/TLS)
- ✅ Enable CSRF protection
- ✅ Set up firewall rules
- ✅ Use environment variables for secrets
- ✅ Regular security updates
- ✅ Configure CORS properly
- ✅ Use strong database passwords

### Performance Optimization

- Use connection pooling for database
- Configure Celery concurrency based on CPU cores
- Enable Redis persistence for task results
- Use CDN for static files
- Implement caching (Redis/Memcached)
- Monitor with tools like Sentry

## Support

For issues and questions:
- Check the logs in `logs/django.log`
- Review Django admin at `/admin/`
- Monitor Celery tasks in Flower at `:5555`
- Check API responses for error messages

## License

MIT License - See LICENSE file for details
