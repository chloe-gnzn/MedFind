"""
ERD entities in this app: Pharmacy, Inventory, Operating_hours, Pharmacy_verification
"""
from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from medfind_project.session_auth import PasswordMixin


class Pharmacy(PasswordMixin, models.Model):
    """ERD: Pharmacy"""

    VERIFICATION_PENDING = 'pending'
    VERIFICATION_APPROVED = 'approved'
    VERIFICATION_REJECTED = 'rejected'
    VERIFICATION_CHOICES = [                                          # enum
        (VERIFICATION_PENDING, 'Pending'),
        (VERIFICATION_APPROVED, 'Approved'),
        (VERIFICATION_REJECTED, 'Rejected'),
    ]

    pharmacy_id = models.AutoField(primary_key=True)                  # PK  int
    email = models.EmailField(max_length=254, unique=True)            # UK  varchar
    business_name = models.CharField(max_length=255)                  # varchar
    password_hash = models.CharField(max_length=255)                  # varchar
    contact_number = models.CharField(max_length=20)                  # varchar
    address = models.CharField(max_length=255)                        # varchar
    photo = models.FileField(upload_to='pharmacy_photos/', blank=True)
    verification_status = models.CharField(                           # enum
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default=VERIFICATION_PENDING,
    )
    is_active = models.BooleanField(default=True)                     # boolean
    created_at = models.DateTimeField(auto_now_add=True)              # datetime
    updated_at = models.DateTimeField(auto_now=True)                  # datetime

    class Meta:
        verbose_name_plural = 'pharmacies'
        ordering = ['business_name']

    @property
    def display_name(self):
        return self.business_name

    @property
    def is_approved(self):
        return self.verification_status == self.VERIFICATION_APPROVED

    def __str__(self):
        return self.business_name


class Inventory(models.Model):
    """ERD: Inventory  (a pharmacy stocks many medicines; a medicine is stocked by many pharmacies)"""

    STATUS_AVAILABLE = 'available'
    STATUS_LOW = 'low_stock'
    STATUS_OUT = 'out_of_stock'
    AVAILABILITY_CHOICES = [                                          # enum
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_LOW, 'Low stock'),
        (STATUS_OUT, 'Out of stock'),
    ]

    inventory_id = models.AutoField(primary_key=True)                 # PK  int
    pharmacy = models.ForeignKey(                                     # FK  int
        'pharmacy_app.Pharmacy', on_delete=models.CASCADE, related_name='inventory_items'
    )
    medicine = models.ForeignKey(                                     # FK  int
        'home_app.Medicine', on_delete=models.CASCADE, related_name='inventory_items'
    )
    price = models.DecimalField(                                      # decimal
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    availability_status = models.CharField(                           # enum
        max_length=20, choices=AVAILABILITY_CHOICES, default=STATUS_AVAILABLE
    )
    stock_quantity = models.IntegerField(                             # int
        default=0, validators=[MinValueValidator(0)]
    )
    updated_at = models.DateTimeField(auto_now=True)                  # datetime

    class Meta:
        verbose_name_plural = 'inventory'
        constraints = [
            models.UniqueConstraint(
                fields=['pharmacy', 'medicine'], name='unique_medicine_per_pharmacy'
            )
        ]

    def __str__(self):
        return f'{self.pharmacy} - {self.medicine}'


class OperatingHours(models.Model):
    """ERD: Operating_hours  (one pharmacy -> up to 7 rows, one per weekday)"""

    DAY_CHOICES = [                                                   # tinyint 0-6
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
        (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]

    hours_id = models.AutoField(primary_key=True)                     # PK  int
    pharmacy = models.ForeignKey(                                     # FK  int
        'pharmacy_app.Pharmacy', on_delete=models.CASCADE, related_name='operating_hours'
    )
    days_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)   # tinyint
    # times are blank on days the pharmacy is closed
    opening_time = models.TimeField(null=True, blank=True)            # time
    closing_time = models.TimeField(null=True, blank=True)            # time
    is_closed = models.BooleanField(default=False)                    # boolean

    class Meta:
        verbose_name_plural = 'operating hours'
        ordering = ['pharmacy', 'days_of_week']
        constraints = [
            models.UniqueConstraint(
                fields=['pharmacy', 'days_of_week'], name='unique_day_per_pharmacy'
            )
        ]

    def __str__(self):
        return f'{self.pharmacy} - {self.get_days_of_week_display()}'


class PharmacyVerification(models.Model):
    """ERD: Pharmacy_verification  (pharmacy submits documents; an Admin reviews them)"""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [                                                # enum
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    verification_id = models.AutoField(primary_key=True)              # PK  int
    pharmacy = models.ForeignKey(                                     # FK  int
        'pharmacy_app.Pharmacy', on_delete=models.CASCADE, related_name='verifications'
    )
    reviewed_by = models.ForeignKey(                                  # FK  int  -> Admin (empty until reviewed)
        'admin_app.Admin', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_verifications',
    )
    document_path = models.CharField(max_length=255)                  # varchar
    status = models.CharField(                                        # enum
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)         # datetime
    remarks = models.TextField(blank=True)                            # text

    class Meta:
        ordering = ['-verification_id']

    @property
    def document_url(self):
        return default_storage.url(self.document_path)

    def __str__(self):
        return f'{self.pharmacy} - {self.status}'


class Reservation(models.Model):
    """User medicine reservation held for 24 hours until claimed or moved to unclaimed."""

    STATUS_PENDING = 'pending'
    STATUS_CLAIMED = 'claimed'
    STATUS_UNCLAIMED = 'unclaimed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_CLAIMED, 'Claimed'),
        (STATUS_UNCLAIMED, 'Unclaimed'),
    ]

    reservation_id = models.AutoField(primary_key=True)
    reservation_code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    user = models.ForeignKey(
        'home_app.User', on_delete=models.CASCADE, related_name='reservations'
    )
    pharmacy = models.ForeignKey(
        'pharmacy_app.Pharmacy', on_delete=models.CASCADE, related_name='reservations'
    )
    medicine = models.ForeignKey(
        'home_app.Medicine', on_delete=models.CASCADE, related_name='reservations'
    )
    inventory = models.ForeignKey(
        'pharmacy_app.Inventory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reservations',
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_auto_expired = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)
        if not self.reservation_code:
            self.reservation_code = f'RS{self.reservation_id:04d}'
            super().save(update_fields=['reservation_code'])

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f'{self.reservation_code or self.pk} - {self.medicine} ({self.quantity})'
