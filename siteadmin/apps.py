from django.apps import AppConfig


class SiteadminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "siteadmin"
    # "Admin panel" rather than "Siteadmin": this is what a person sees in
    # Django's own admin, and it should read like the thing it is.
    verbose_name = "Admin panel"
