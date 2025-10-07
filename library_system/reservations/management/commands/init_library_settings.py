from django.core.management.base import BaseCommand
from reservations.models import LibrarySettings

class Command(BaseCommand):
    help = 'Initialize library settings with default values'

    def handle(self, *args, **kwargs):
        if not LibrarySettings.objects.exists():
            LibrarySettings.objects.create(
                max_booking_duration=180,  # 3 hours
                max_advance_booking_days=1,
                check_in_buffer=15,
                max_active_reservations=1,
                penalty_threshold=3,
                penalty_duration_days=7
            )
            self.stdout.write(self.style.SUCCESS('Successfully created default library settings'))
        else:
            self.stdout.write(self.style.WARNING('Library settings already exist'))