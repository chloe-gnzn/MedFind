"""
ERD entities in this app: Admin, Activity_Log

Activity_Log: every login / logout / registration / admin action is written
here through login_app.utils.log_activity().
"""
from django.db import models

from medfind_project.session_auth import PasswordMixin


class Admin(PasswordMixin, models.Model):
    """ERD: Admin"""

    ROLE_SUPER_ADMIN = 'super_admin'
    ROLE_ADMIN = 'admin'
    ROLE_CHOICES = [
        (ROLE_SUPER_ADMIN, 'Super Admin'),
        (ROLE_ADMIN, 'Admin'),
    ]

    admin_id = models.AutoField(primary_key=True)
    email = models.EmailField(max_length=254, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_ADMIN
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']

    @property
    def display_name(self):
        return self.first_name

    def __str__(self):
        return f'{self.first_name} {self.last_name} <{self.email}>'


class ActivityLog(models.Model):
    """ERD: Activity_Log"""

    ACTOR_USER = 'user'
    ACTOR_PHARMACY = 'pharmacy'
    ACTOR_ADMIN = 'admin'
    ACTOR_CHOICES = [
        (ACTOR_USER, 'User'),
        (ACTOR_PHARMACY, 'Pharmacy'),
        (ACTOR_ADMIN, 'Admin'),
    ]

    log_id = models.AutoField(primary_key=True)
    actor_type = models.CharField(max_length=20, choices=ACTOR_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)
    action = models.CharField(max_length=100)
    # actor_id points at a row in User / Pharmacy / Admin depending on
    # actor_type, so (as in the ERD) it is a plain int and not a foreign key.
    actor_id = models.IntegerField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.actor_type}#{self.actor_id}] {self.action}'
