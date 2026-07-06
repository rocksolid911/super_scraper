import json
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.scraper.models import ScrapeRecipe

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with pre-built community recipes for better user retention'

    def handle(self, *args, **options):
        # We assign community recipes to the first superuser
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            self.stdout.write(self.style.ERROR('No superuser found. Please create one first.'))
            return

        recipes = [
            {
                'name': 'Amazon Product Prices',
                'source_url': 'https://www.amazon.com/s?k=laptops',
                'section_label': 'Search Results',
                'prompt': 'Extract the product name, price, rating, and number of reviews for each laptop.',
                'use_js_rendering': True,
                'respect_robots_txt': True,
                'items': [{'title': 'Sample Laptop', 'url': 'https://amazon.com/sample'}]
            },
            {
                'name': 'YCombinator Top Companies',
                'source_url': 'https://www.ycombinator.com/topcompanies',
                'section_label': 'Company List',
                'prompt': 'Extract the company name, description, batch, and URL.',
                'use_js_rendering': False,
                'respect_robots_txt': True,
                'items': [{'title': 'Stripe', 'url': 'https://ycombinator.com/companies/stripe'}]
            },
            {
                'name': 'Hacker News Frontpage',
                'source_url': 'https://news.ycombinator.com/',
                'section_label': 'Articles',
                'prompt': 'Extract the article title, link, points, and submitter username.',
                'use_js_rendering': False,
                'respect_robots_txt': True,
                'items': [{'title': 'Sample Article', 'url': 'https://news.ycombinator.com/item?id=1'}]
            }
        ]

        created_count = 0
        for data in recipes:
            recipe, created = ScrapeRecipe.objects.get_or_create(
                name=data['name'],
                user=user,
                defaults={
                    'source_url': data['source_url'],
                    'section_label': data['section_label'],
                    'prompt': data['prompt'],
                    'use_js_rendering': data['use_js_rendering'],
                    'respect_robots_txt': data['respect_robots_txt'],
                    'items': data['items']
                }
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully seeded {created_count} community recipes.'))
