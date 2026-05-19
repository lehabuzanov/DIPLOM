from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("corpus", "0002_articlehighlight"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="articlehighlight",
            new_name="corpus_arti_user_id_e35982_idx",
            old_name="corpus_arti_user_id_49b57d_idx",
        ),
    ]
