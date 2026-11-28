"""
ERD entities in this app: User, Medicine_Category, Medicine, Favorite, Search_history
"""
from django.core.exceptions import ValidationError
from django.db import models

from medfind_project.session_auth import PasswordMixin


class User(PasswordMixin, models.Model):
    """ERD: User"""

    user_id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254, unique=True)
    password_hash = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def display_name(self):
        return self.first_name

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def __str__(self):
        return f'{self.full_name} <{self.email}>'


class MedicineCategory(models.Model):
    """ERD: Medicine_Category"""

    category_id = models.AutoField(primary_key=True)
    description = models.CharField(max_length=255, blank=True)
    category_name = models.TextField(unique=True)

    class Meta:
        verbose_name_plural = 'medicine categories'
        ordering = ['category_name']

    def __str__(self):
        return self.category_name


class Medicine(models.Model):
    """ERD: Medicine  (one category -> many medicines)"""

    medicine_id = models.AutoField(primary_key=True)
    category = models.ForeignKey(
        MedicineCategory,
        on_delete=models.PROTECT,
        related_name='medicines',
    )
    medicine_name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255)
    form = models.CharField(max_length=100)
    strength = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['medicine_name']

    def __str__(self):
        return f'{self.medicine_name} ({self.strength} {self.form})'


class Favorite(models.Model):
    """
    ERD: Favorite  (User, Medicine and Pharmacy each -> many favorites)

    favorite_type says what was favorited: a medicine or a pharmacy.
    The unused FK is left NULL, so medicine and pharmacy are nullable.
    """

    TYPE_MEDICINE = 'medicine'
    TYPE_PHARMACY = 'pharmacy'
    TYPE_CHOICES = [
        (TYPE_MEDICINE, 'Medicine'),
        (TYPE_PHARMACY, 'Pharmacy'),
    ]

    favorite_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        'home_app.User', on_delete=models.CASCADE, related_name='favorites'
    )
    medicine = models.ForeignKey(
        Medicine, on_delete=models.CASCADE, related_name='favorites',
        null=True, blank=True,
    )
    pharmacy = models.ForeignKey(
        'pharmacy_app.Pharmacy', on_delete=models.CASCADE, related_name='favorites',
        null=True, blank=True,
    )
    favorite_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        if self.favorite_type == self.TYPE_MEDICINE and not self.medicine_id:
            raise ValidationError('A medicine favorite needs a medicine.')
        if self.favorite_type == self.TYPE_PHARMACY and not self.pharmacy_id:
            raise ValidationError('A pharmacy favorite needs a pharmacy.')

    def __str__(self):
        target = self.medicine if self.favorite_type == self.TYPE_MEDICINE else self.pharmacy
        return f'{self.user_id} -> {target}'


class SearchHistory(models.Model):
    """ERD: Search_history  (one user -> many searches)"""

    search_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        'home_app.User', on_delete=models.CASCADE, related_name='search_history'
    )
    search_term = models.CharField(max_length=255)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'search history'
        ordering = ['-searched_at']

    def __str__(self):
        return self.search_term
