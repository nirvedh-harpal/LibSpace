from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roll_number = models.CharField(max_length=20, unique=True, default='Unknown')
    branch = models.CharField(max_length=100, default='Unknown')
    # reservation system fields
    no_show_count = models.IntegerField(default=0)
    last_penalty_date = models.DateTimeField(null=True, blank=True)
    is_restricted = models.BooleanField(default=False)
    # fine payment fields
    fines = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Outstanding fines in rupees")

    def __str__(self):
        return self.user.username
        
    def increment_no_shows(self):
        from reservations.models import LibrarySettings  # Import here to avoid circular import
        self.no_show_count += 1
        settings = LibrarySettings.get_settings()
        
        if self.no_show_count >= settings.penalty_threshold:
            self.is_restricted = True
            self.last_penalty_date = timezone.now()
        
        self.save()

    def check_restrictions(self):
        if not self.is_restricted:
            return False
        
        from reservations.models import LibrarySettings  # Import here to avoid circular import
        settings = LibrarySettings.get_settings()
        penalty_end_date = self.last_penalty_date + timedelta(days=settings.penalty_duration_days)
        
        if timezone.now() > penalty_end_date:
            self.is_restricted = False
            self.no_show_count = 0
            self.last_penalty_date = None
            self.save()
            return False
            
        return True

class Compartment(models.Model):
    number = models.PositiveIntegerField(unique=True)
    is_empty = models.BooleanField(default=True)
    student = models.OneToOneField(Student, null=True, blank=True, on_delete=models.SET_NULL)
    otp_expiration = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Compartment {self.number}"

class OTP(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField()  # Add this field

    class Meta:
        indexes = [
            models.Index(fields=['student']),
            models.Index(fields=['code']),
        ]

    def save(self, *args, **kwargs):
        if not self.generated_at:
            self.generated_at = timezone.now()  # Set the generated time
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OTP for {self.student.user.username} - {self.code}"
