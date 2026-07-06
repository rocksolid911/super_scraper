# Universal AI Web Scraper

A powerful, AI-driven web scraping platform that can crawl and extract data from most websites using visual selectors or natural language prompts.

## 🚀 Features

### Backend (Python/Django)
- **Django REST Framework** - RESTful API architecture
- **Crawl4AI Integration** - Advanced web crawling and parsing
- **Playwright Support** - JavaScript-heavy site rendering
- **AI Schema Generation** - Automatic extraction schema inference using GPT-4 or Claude
- **Celery Task Queue** - Distributed job scheduling and execution
- **PostgreSQL Database** - Robust data storage
- **JWT Authentication** - Secure token-based auth
- **Robots.txt Compliance** - Respects website scraping policies
- **Rate Limiting** - Per-domain request throttling
- **Data Export** - CSV, JSON, and Excel formats

### Frontend (Next.js)
- **Next.js App Router** - Modern, server-rendered React framework
- **TypeScript** - Strongly typed for reliability
- **Visual Selector Mode** - Click-to-select fields from live website preview
- **AI Prompt Mode** - Describe what you want in natural language
- **Job Scheduling** - Hourly, daily, weekly, or custom CRON expressions
- **Real-time Monitoring** - Live job status and progress tracking
- **Data Viewer** - Paginated tables with search, filter, and export
- **Responsive Layout** - Desktop-first design
- **Dark Mode** - Theme switching support

## 📋 Prerequisites

### Backend
- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Node.js (for Playwright)

### Frontend
- Node.js 18+
- npm or yarn
- Chrome browser

### AI Features (Optional)
- OpenAI API key (for GPT models)
- Anthropic API key (for Claude models)

## 🛠️ Quick Start

### Using Docker Compose (Recommended)

1. **Clone the repository**
```bash
git clone <repository-url>
cd super_scraper
```

2. **Set up environment variables**
```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your settings
```

3. **Start all services**
```bash
docker-compose up -d
```

This starts:
- PostgreSQL database (port 5432)
- Redis (port 6379)
- Django backend (port 8000)
- Celery worker
- Celery beat scheduler
- Flower monitoring (port 5555)

4. **Create superuser**
```bash
docker-compose exec backend python manage.py createsuperuser
```

5. **Access the application**
- Backend API: http://localhost:8000
- Admin Panel: http://localhost:8000/admin
- Flower: http://localhost:5555

### Manual Installation

See detailed installation instructions in:
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)

## 📖 Documentation

- **[Backend Documentation](backend/README.md)** - API endpoints, configuration, deployment
- **[Frontend Documentation](frontend/README.md)** - UI features, development, building

## 🎯 Usage Examples

### Visual Selector Mode
1. Create new job
2. Enter target URL
3. Select "Visual Selector" mode
4. Click elements to define fields
5. Preview and save

### AI Prompt Mode
1. Create new job
2. Enter URLs
3. Write natural language prompt
4. AI generates extraction schema
5. Review and save

## 🏗️ Architecture

```
Next.js (React) → Django REST API → PostgreSQL
                ↓
            Celery (Redis)
                ↓
        Crawl4AI + Playwright
                ↓
          OpenAI/Claude
```

## 📊 Project Structure

```
super_scraper/
├── backend/                # Django backend
│   ├── config/            # Settings
│   ├── apps/              # Django apps
│   └── README.md
├── frontend/              # Next.js web application
│   ├── app/               # Next.js App Router pages
│   ├── components/        # React components
│   └── README.md
├── docker-compose.yml
└── README.md
```

## 🚀 Deployment

See detailed deployment instructions in component READMEs.

## 📝 License

MIT License

## 🤝 Contributing

Contributions welcome! Please read the component READMEs for guidelines.

---

Built with Django, Next.js, Crawl4AI, and AI