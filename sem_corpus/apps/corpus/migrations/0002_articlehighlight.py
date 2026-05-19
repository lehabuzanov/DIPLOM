from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("corpus", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticleHighlight",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("char_start", models.PositiveIntegerField(verbose_name="символ начала")),
                ("char_end", models.PositiveIntegerField(verbose_name="символ конца")),
                ("selected_text", models.TextField(verbose_name="выделенный фрагмент")),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="highlights",
                        to="corpus.article",
                        verbose_name="статья",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="article_highlights",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "пометка в статье",
                "verbose_name_plural": "пометки в статьях",
                "ordering": ["article_id", "char_start", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="articlehighlight",
            index=models.Index(fields=["user", "article", "char_start"], name="corpus_arti_user_id_49b57d_idx"),
        ),
        migrations.AddConstraint(
            model_name="articlehighlight",
            constraint=models.UniqueConstraint(
                fields=("user", "article", "char_start", "char_end"),
                name="unique_article_highlight_range_per_user",
            ),
        ),
    ]
