from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corpus", "0003_rename_articlehighlight_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="articlehighlight",
            name="note_text",
            field=models.TextField(blank=True, verbose_name="комментарий"),
        ),
    ]
