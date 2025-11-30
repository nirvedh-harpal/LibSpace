from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from compartments.models import Student

class LibrarySettings(models.Model):
    max_booking_duration = models.IntegerField(
        default=180,  # 3 hours in minutes
        validators=[MinValueValidator(30), MaxValueValidator(720)],
        help_text="Maximum booking duration in minutes"
    )
    max_advance_booking_days = models.IntegerField(
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
        help_text="Maximum days in advance a booking can be made"
    )
    check_in_buffer = models.IntegerField(
        default=15,
        validators=[MinValueValidator(5), MaxValueValidator(60)],
        help_text="Minutes allowed for check-in after reservation start"
    )
    max_active_reservations = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Maximum number of active reservations per user"
    )
    penalty_threshold = models.IntegerField(
        default=3,
        help_text="Number of no-shows before penalties apply"
    )
    penalty_duration_days = models.IntegerField(
        default=7,
        help_text="Number of days user is restricted after exceeding threshold"
    )

    class Meta:
        verbose_name_plural = "Library Settings"

    @classmethod
    def get_settings(cls):
        return cls.objects.first() or cls.objects.create()



class Seat(models.Model):
    number = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=50, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"Seat {self.number}"

    def is_available(self, start_time, end_time):
        return not self.reservation_set.filter(
            status__in=['reserved', 'checked_in'],
            start_time__lt=end_time,
            end_time__gt=start_time
        ).exists()

    @classmethod
    def get_available_seats(cls, start_time, end_time):
        from django.db.models import Exists, OuterRef
    
        # Subquery to find conflicting reservations
        conflicting = Reservation.objects.filter(
            seat_id=OuterRef('pk'),
            status__in=['reserved', 'checked_in'],
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        
        # Get seats with NO conflicts
        return cls.objects.filter(
            is_active=True
        ).annotate(
            has_conflict=Exists(conflicting)
        ).filter(
            has_conflict=False
        )

class Reservation(models.Model):
    STATUS_CHOICES = [
        ('reserved', 'reserved'),
        ('checked_in', 'checked_in'),
        ('cancelled', 'cancelled'),
        ('completed', 'completed'),
        ('no_show', 'no_show'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reserved')
    created_at = models.DateTimeField(auto_now_add=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    otp = models.CharField(max_length=6, null=True, blank=True)
    otp_generated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['seat']),
            models.Index(fields=['status']),
            models.Index(fields=['start_time']),
            models.Index(fields=['end_time']),
            models.Index(fields=['student', 'status', 'end_time']),  # for active reservations
        ]

    def __str__(self):
        return f"{self.student.user.username} - Seat {self.seat.number} - {self.start_time}"

    def clean(self):
        # Only validate for new reservations
        if self.pk is None or self.status == 'reserved':
            if self.start_time >= self.end_time:
                raise ValidationError("End time must be after start time")

            duration = (self.end_time - self.start_time).total_seconds() / 60
            settings = LibrarySettings.get_settings()

            if duration > settings.max_booking_duration:
                raise ValidationError(f"Maximum booking duration is {settings.max_booking_duration} minutes")

            max_future = timezone.now() + timedelta(days=settings.max_advance_booking_days)
            if self.start_time > max_future:
                raise ValidationError(f"Cannot book more than {settings.max_advance_booking_days} days in advance")

            # Only check seat availability for new reservations
            if self.pk is None:
                if not self.seat.is_available(self.start_time, self.end_time):
                    raise ValidationError("This seat is not available for the selected time period")

            # Check for other active reservations only for new bookings
            active_reservations_query = Reservation.objects.filter(
                student=self.student,
                status__in=['reserved', 'checked_in'],
                end_time__gt=timezone.now()
            )
            
            # For existing reservations, exclude the current one from the count
            if self.pk:
                active_reservations_query = active_reservations_query.exclude(pk=self.pk)
            
            active_reservations = active_reservations_query
            # Only check max active reservations for new bookings
            if self.pk is None and active_reservations.count() >= settings.max_active_reservations:
                raise ValidationError(f"Maximum {settings.max_active_reservations} active reservations allowed")

    def save(self, *args, **kwargs):
        # Always validate for new reservations
        # For existing ones, only validate if it's still in reserved status
        if self.pk is None or self.status == 'reserved':
            self.full_clean()
        
        super().save(*args, **kwargs)
        
        if self.status == 'reserved':
            self.send_confirmation_email()

    def is_active(self):
        return self.status in ['reserved', 'checked_in'] and self.end_time > timezone.now()

    def auto_cancel_deadline(self):
        settings = LibrarySettings.get_settings()
        return self.start_time + timedelta(minutes=settings.check_in_buffer)

    def can_check_in(self):
        return (
            self.status == 'reserved'
        )

    def check_in(self, otp=None):
        if not self.can_check_in():
            raise ValidationError("Check-in not allowed at this time")
            
        if otp and self.otp and otp != self.otp:
            raise ValidationError("Invalid OTP")
            
        self.status = 'checked_in'
        self.check_in_time = timezone.now()
        self.save()

    def generate_otp(self):
        import random
        self.otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        self.otp_generated_at = timezone.now()
        self.save()
        self.send_otp_email()

    def send_confirmation_email(self):
        subject = 'Library Seat Reservation Confirmation'
        message = f'''
        Your seat reservation has been confirmed:
        
        Seat: {self.seat.number}
        Date: {self.start_time.date()}
        Time: {self.start_time.time()} - {self.end_time.time()}
        
        Please check in within {LibrarySettings.get_settings().check_in_buffer} minutes of your start time.
        '''
        self._send_email(subject, message)

    def send_otp_email(self):
        subject = 'Library Seat Reservation OTP'
        message = f'''
        Your OTP for seat {self.seat.number} is: {self.otp}
        
        This OTP will expire in 5 minutes.
        '''
        self._send_email(subject, message)

    def _send_email(self, subject, message):
        try:
            from reservations.tasks import send_email_task
            send_email_task.delay(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [self.student.user.email],
                fail_silently=False,
            )
        except Exception as e:
            # Log the error but don't prevent the save
            print(f"Failed to send email: {e}")

class Payment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount paid in rupees")
    status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed')],
        default='pending'
    )
    stripe_session_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['stripe_session_id']),
        ]

    def __str__(self):
        return f"Payment {self.id} - ₹{self.amount} - {self.status}"
    
    def clear_student_fines(self):
        """
        Clear student fines based on payment status and amount.
        Called when payment is successfully completed.
        """
        if self.status == 'completed':
            # Reduce student fines by the payment amount
            if self.student.fines > 0:
                self.student.fines = max(0, self.student.fines - self.amount)
                self.student.save()
