from django.apps import AppConfig


class ReelsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reels'
    
    def ready(self):
        import reels.signals  # Register signals