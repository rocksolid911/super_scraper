# Universal AI Web Scraper - Frontend

Flutter Web frontend for the Universal AI Web Scraper application.

## Features

- **Material Design 3** - Modern, beautiful UI
- **Responsive Layout** - Desktop-first design that adapts to all screen sizes
- **Clean Architecture** - Organized codebase with separation of concerns
- **Riverpod State Management** - Robust and scalable state management
- **JWT Authentication** - Secure token-based auth with refresh tokens
- **Job Management** - Create, schedule, and monitor scraping jobs
- **Visual Selector Mode** - Click-to-select fields from live website preview
- **AI-Powered Scraping** - Natural language prompts to define scraping tasks
- **Scheduling UI** - Intuitive CRON expression builder
- **Data Viewer** - Paginated tables with search, filter, and export
- **Real-time Updates** - Live job status and progress tracking
- **Dark Mode Support** - Theme switching capability

## Tech Stack

- **Flutter 3.0+**
- **Dart 3.0+**
- **Riverpod** for state management
- **GoRouter** for navigation
- **Dio** for HTTP requests
- **Google Fonts** for typography
- **Syncfusion Charts** for data visualization
- **Pluto Grid** for advanced data tables

## Prerequisites

- Flutter SDK 3.0 or higher
- Dart SDK 3.0 or higher
- Chrome (for web development)
- Backend API running (see backend README)

## Installation

### 1. Install Flutter

Follow the official Flutter installation guide:
https://docs.flutter.dev/get-started/install

### 2. Clone the repository

```bash
git clone <repository-url>
cd super_scraper/frontend
```

### 3. Install dependencies

```bash
flutter pub get
```

### 4. Configure API endpoint

The API endpoint is configured in `lib/config/app_config.dart`.

For development:
- Default: `http://localhost:8000/api`

For production:
- Update in `AppConfig.prod`

### 5. Generate code (if using code generation)

```bash
flutter pub run build_runner build --delete-conflicting-outputs
```

## Running the Application

### Development Mode

Run with hot reload:

```bash
flutter run -d chrome --dart-define=ENV=dev
```

Or use the development entry point:

```bash
flutter run -t lib/main_dev.dart -d chrome
```

### Production Mode

```bash
flutter run -d chrome --dart-define=ENV=prod
```

Or:

```bash
flutter run -t lib/main_prod.dart -d chrome
```

### Build for Web

Development build:

```bash
flutter build web --dart-define=ENV=dev
```

Production build:

```bash
flutter build web --release --dart-define=ENV=prod
```

The built files will be in `build/web/`

## Project Structure

```
frontend/
├── lib/
│   ├── main_dev.dart          # Dev entry point
│   ├── main_prod.dart         # Prod entry point
│   ├── app.dart               # Main app widget
│   ├── config/                # Configuration
│   │   └── app_config.dart    # Environment configs
│   ├── core/                  # Core functionality
│   │   ├── api/               # API client
│   │   │   ├── api_client.dart
│   │   │   ├── dio_client.dart
│   │   │   └── interceptors/
│   │   ├── router/            # Navigation
│   │   │   └── app_router.dart
│   │   ├── theme/             # Theming
│   │   │   └── app_theme.dart
│   │   ├── models/            # Core models
│   │   └── utils/             # Utilities
│   ├── features/              # Feature modules
│   │   ├── auth/              # Authentication
│   │   │   ├── data/
│   │   │   │   ├── models/
│   │   │   │   ├── repositories/
│   │   │   │   └── datasources/
│   │   │   ├── domain/
│   │   │   │   ├── entities/
│   │   │   │   └── repositories/
│   │   │   └── presentation/
│   │   │       ├── pages/
│   │   │       ├── widgets/
│   │   │       └── providers/
│   │   ├── dashboard/         # Dashboard
│   │   │   └── presentation/
│   │   │       └── pages/
│   │   ├── jobs/              # Job management
│   │   │   ├── data/
│   │   │   ├── domain/
│   │   │   └── presentation/
│   │   ├── selector/          # Visual selector
│   │   │   └── presentation/
│   │   ├── data_viewer/       # Data viewing & export
│   │   │   └── presentation/
│   │   └── scheduling/        # Job scheduling
│   │       └── presentation/
│   └── shared/                # Shared widgets
│       ├── widgets/
│       └── constants/
├── web/                       # Web-specific files
│   ├── index.html
│   ├── manifest.json
│   └── icons/
├── assets/                    # Assets
│   ├── images/
│   ├── icons/
│   └── animations/
├── test/                      # Tests
├── pubspec.yaml              # Dependencies
└── README.md                 # This file
```

## Features Guide

### 1. Authentication

Login and registration with JWT tokens:

```dart
// Login
final authProvider = Provider((ref) => AuthRepository());
await ref.read(authProvider).login(email, password);

// Register
await ref.read(authProvider).register(userData);

// Logout
await ref.read(authProvider).logout();
```

### 2. Creating a Scraping Job

#### Visual Selector Mode

1. Go to "New Job"
2. Select "Visual Selector" mode
3. Enter target URL
4. Click "Select Fields"
5. Hover and click on elements to define fields
6. Preview extracted data
7. Save job configuration

#### AI Prompt Mode

1. Go to "New Job"
2. Select "AI Prompt" mode
3. Enter target URLs (comma-separated)
4. Write natural language prompt:
   - Example: "Extract all product listings with name, price, rating, and image"
5. Click "Generate Schema"
6. Review and adjust AI-generated selectors
7. Save job

### 3. Scheduling Jobs

Configure job schedules:

- **Interval**: Every N minutes/hours/days/weeks
- **CRON**: Custom CRON expressions
- **One-time**: Run once at specific time

```dart
// Schedule configuration
{
  "is_scheduled": true,
  "schedule_config": {
    "type": "interval",
    "interval_value": 24,
    "interval_unit": "hours"
  }
}
```

### 4. Monitoring Jobs

Dashboard shows:
- Active jobs count
- Recent runs
- Success/failure rates
- Items scraped
- Next scheduled run

Job detail page shows:
- Configuration
- Run history
- Latest scraped data
- Error logs
- Statistics & charts

### 5. Viewing & Exporting Data

Data viewer features:
- Paginated table view
- Search across all fields
- Filter by date range or run
- Sort by any column
- Export as CSV, JSON, or Excel

## Development Guidelines

### Code Style

Follow Flutter best practices:
- Use `flutter analyze` to check for issues
- Format code with `flutter format`
- Follow naming conventions
- Add documentation comments

### State Management with Riverpod

```dart
// Provider example
final jobsProvider = FutureProvider<List<Job>>((ref) async {
  final api = ref.watch(apiClientProvider);
  return api.getJobs();
});

// StateNotifier example
class JobsNotifier extends StateNotifier<AsyncValue<List<Job>>> {
  JobsNotifier(this.ref) : super(const AsyncValue.loading());

  final Ref ref;

  Future<void> loadJobs() async {
    state = const AsyncValue.loading();
    try {
      final api = ref.read(apiClientProvider);
      final jobs = await api.getJobs();
      state = AsyncValue.data(jobs);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }
}

final jobsNotifierProvider =
    StateNotifierProvider<JobsNotifier, AsyncValue<List<Job>>>((ref) {
  return JobsNotifier(ref);
});
```

### API Integration

```dart
// API client with Dio
class ApiClient {
  final Dio dio;

  ApiClient(this.dio);

  Future<List<Job>> getJobs() async {
    final response = await dio.get('/scraper/jobs/');
    return (response.data as List)
        .map((json) => Job.fromJson(json))
        .toList();
  }

  Future<Job> createJob(JobRequest request) async {
    final response = await dio.post(
      '/scraper/jobs/',
      data: request.toJson(),
    );
    return Job.fromJson(response.data);
  }
}
```

### Routing

```dart
// Navigate to job detail
context.push('/jobs/$jobId');

// Navigate with parameters
context.pushNamed(
  'job-detail',
  pathParameters: {'id': jobId},
  queryParameters: {'tab': 'runs'},
);

// Go back
context.pop();
```

## Building for Production

### Web

```bash
# Production build
flutter build web --release --dart-define=ENV=prod

# Deploy to hosting
# The build/web/ directory contains all files needed
```

### Optimize Build

Add to `web/index.html`:

```html
<!-- Preload fonts -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>

<!-- Service worker for PWA -->
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
      navigator.serviceWorker.register('flutter_service_worker.js');
    });
  }
</script>
```

## Environment Configuration

### Development

```dart
// lib/config/app_config.dart
static const dev = AppConfig(
  appName: 'Super Scraper (Dev)',
  apiBaseUrl: 'http://localhost:8000/api',
  environment: 'development',
  debugMode: true,
);
```

### Production

```dart
static const prod = AppConfig(
  appName: 'Super Scraper',
  apiBaseUrl: 'https://api.yourdomain.com/api',
  environment: 'production',
  debugMode: false,
);
```

## Deployment

### Firebase Hosting

```bash
# Install Firebase CLI
npm install -g firebase-tools

# Initialize
firebase init hosting

# Deploy
flutter build web --release
firebase deploy --only hosting
```

### Netlify

```bash
# Build
flutter build web --release

# Deploy (drag build/web folder to Netlify)
# Or use Netlify CLI
netlify deploy --prod --dir=build/web
```

### Vercel

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
vercel --prod
```

## Testing

### Unit Tests

```bash
flutter test
```

### Widget Tests

```bash
flutter test test/widgets/
```

### Integration Tests

```bash
flutter test integration_test/
```

### Test Coverage

```bash
flutter test --coverage
genhtml coverage/lcov.info -o coverage/html
open coverage/html/index.html
```

## Troubleshooting

### CORS Issues

If you encounter CORS errors:
1. Ensure backend CORS settings include your frontend URL
2. Check `config/settings.py` in backend:
   ```python
   CORS_ALLOWED_ORIGINS = [
       'http://localhost:3000',
       'http://localhost:8080',
   ]
   ```

### Build Errors

Clear Flutter cache:

```bash
flutter clean
flutter pub get
flutter pub run build_runner clean
flutter pub run build_runner build --delete-conflicting-outputs
```

### Hot Reload Not Working

Restart the app:

```bash
# Press 'r' in terminal for hot reload
# Press 'R' for hot restart
# Press 'q' to quit
```

## Performance Optimization

1. **Lazy Loading**: Load data on demand
2. **Pagination**: Implement infinite scroll for large lists
3. **Caching**: Cache API responses with Riverpod
4. **Image Optimization**: Use cached_network_image
5. **Code Splitting**: Use deferred loading for large features
6. **Tree Shaking**: Production builds automatically remove unused code

## Accessibility

- Semantic labels for screen readers
- Keyboard navigation support
- Sufficient color contrast
- Scalable text
- Focus indicators

## Contributing

1. Follow Flutter style guide
2. Write tests for new features
3. Update documentation
4. Run `flutter analyze` before committing
5. Format code with `flutter format`

## Support

For issues and questions:
- Check browser console for errors
- Review API responses in Network tab
- Check backend logs
- Verify API endpoints are accessible

## License

MIT License - See LICENSE file for details
