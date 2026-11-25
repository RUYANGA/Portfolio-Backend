from django.apps import AppConfig


class PortfolioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.portfolio"
    # Label kept as "portfolio" so existing tables and migrations stay valid.
    label = "portfolio"
    verbose_name = "Portfolio"
