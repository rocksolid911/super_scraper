import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("scraper", "0003_alter_scrapejob_max_pages"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScrapeRecipe",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                ("source_url", models.URLField(max_length=2048)),
                ("section_label", models.CharField(blank=True, max_length=255)),
                ("prompt", models.TextField(blank=True)),
                (
                    "items",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Selected entries as a list of {title, url}.",
                    ),
                ),
                ("selectors", models.JSONField(blank=True, default=dict)),
                ("use_js_rendering", models.BooleanField(default=False)),
                ("respect_robots_txt", models.BooleanField(default=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scrape_recipes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Scrape Recipe",
                "verbose_name_plural": "Scrape Recipes",
                "db_table": "scrape_recipes",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["user", "created_at"],
                        name="scrape_reci_user_id_a09c46_idx",
                    )
                ],
            },
        ),
    ]
