from django.apps import AppConfig


class DjangoSupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.django_support"
    label = "fencekit_django_support"
    verbose_name = "fencekit Django test support"
