from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0003_reminders"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="meeting_link",
            field=models.URLField(blank=True, help_text="Video call link for this booking."),
        ),
        migrations.AddField(
            model_name="booking",
            name="meeting_provider",
            field=models.CharField(blank=True, help_text="Provider that created the video call.", max_length=20),
        ),
        migrations.AddField(
            model_name="bookingsettings",
            name="video_provider",
            field=models.CharField(
                choices=[("manual", "Manual link"), ("google_meet", "Google Meet"), ("microsoft_teams", "Microsoft Teams")],
                default="manual",
                help_text="How video calls are created for bookings.",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="bookingsettings",
            name="meeting_link",
            field=models.URLField(blank=True, help_text="Default video call link added to every invitation."),
        ),
    ]
