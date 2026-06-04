from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0004_scraperecipe"),
    ]

    operations = [
        migrations.AddField(
            model_name="scrapejob",
            name="notify_on_change",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scrapejob",
            name="notify_config",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="jobrun",
            name="content_index",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
