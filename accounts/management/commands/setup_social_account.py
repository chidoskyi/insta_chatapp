from django.core.management.base import BaseCommand
from django.conf import settings
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site


class Command(BaseCommand):
    help = 'Setup Google OAuth application'

    def handle(self, *args, **options):
        # Get or create site
        site, created = Site.objects.get_or_create(
            id=1,
            defaults={
                'domain': 'localhost:8000',
                'name': 'Instagram Clone'
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created site: {site.domain}'))
        else:
            self.stdout.write(f'Using existing site: {site.domain}')
        
        # Get Google OAuth credentials from settings
        try:
            google_config = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']
            client_id = google_config.get('client_id')
            secret = google_config.get('secret')
            
            if not client_id or not secret:
                self.stdout.write(
                    self.style.ERROR(
                        'Google OAuth credentials not found in settings. '
                        'Please set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env'
                    )
                )
                return
            
            # Create or update social app
            social_app, created = SocialApp.objects.get_or_create(
                provider='google',
                defaults={
                    'name': 'Google OAuth',
                    'client_id': client_id,
                    'secret': secret,
                }
            )
            
            if not created:
                # Update existing
                social_app.client_id = client_id
                social_app.secret = secret
                social_app.save()
                self.stdout.write(
                    self.style.SUCCESS('Updated existing Google OAuth app')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS('Created new Google OAuth app')
                )
            
            # Add site to social app
            if site not in social_app.sites.all():
                social_app.sites.add(site)
                self.stdout.write(
                    self.style.SUCCESS(f'Added site {site.domain} to Google OAuth app')
                )
            
            self.stdout.write(
                self.style.SUCCESS(
                    '\n✅ Google OAuth setup complete!\n\n'
                    'Next steps:\n'
                    '1. Make sure your Google Cloud Console redirect URIs include:\n'
                    f'   - http://{site.domain}/accounts/google/login/callback/\n'
                    '2. Test OAuth flow from your frontend\n'
                )
            )
            
        except KeyError:
            self.stdout.write(
                self.style.ERROR(
                    'SOCIALACCOUNT_PROVIDERS not properly configured in settings.py'
                )
            )