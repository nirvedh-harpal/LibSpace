from celery import shared_task
from django.utils import timezone
from reservations.models import Reservation

@shared_task
def auto_cancel_overdue_reservations():
    print("Running auto-cancel overdue reservations task...")
    now = timezone.now()
    overdue = Reservation.objects.filter(
        status='reserved',
        start_time__lt=now
    )
    count = 0
    for reservation in overdue:
        reservation.status = 'cancelled'
        reservation.save()
        count += 1
    print(f'Auto-cancelled {count} overdue reservations.')
    return f'Auto-cancelled {count} overdue reservations.'
