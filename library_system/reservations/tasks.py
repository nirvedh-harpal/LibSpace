from celery import shared_task
from django.utils import timezone
from reservations.models import Reservation
from django.core.mail import send_mail
from django.conf import settings

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

@shared_task
def send_email_task(subject, message, recipient_list, email_from=None):
    """
    Asynchronously send email using Celery
    """
    if email_from is None:
        email_from = settings.EMAIL_HOST_USER
    
    try:
        send_mail(
            subject,
            message,
            email_from,
            recipient_list,
            fail_silently=False,
        )
        return f"Email sent successfully to {recipient_list}"
    except Exception as e:
        print(f"Failed to send email: {e}")
        return f"Failed to send email: {e}"