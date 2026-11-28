import re

from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from home_app.models import User
from medfind_project.session_auth import get_account_model
from pharmacy_app.models import Pharmacy


def normalize_phone(value):
    """Strip formatting characters from a phone number for comparison."""
    digits = re.sub(r'[^\d+]', '', (value or '').strip())
    if digits.startswith('+63') and len(digits) == 13:
        return '0' + digits[3:]
    if digits.startswith('63') and len(digits) == 12:
        return '0' + digits[2:]
    return digits


class LoginForm(forms.Form):
    """Email (or phone number for users) + password login for ERD account types."""

    email = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'login-input',
            'placeholder': 'email/phone no.',
            'autocomplete': 'username',
            'autofocus': True,
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'login-input',
            'placeholder': 'password',
            'autocomplete': 'current-password',
        }),
    )

    account = None  # filled in by clean() when the credentials are valid

    def __init__(self, *args, role='user', **kwargs):
        # The role is decided by WHICH login page is used (/login/login/, /pharmacy-portal/login/,
        # /manage/login/), not by a dropdown the visitor can change.
        super().__init__(*args, **kwargs)
        self.role = role
        if role != 'user':
            self.fields['email'].widget.attrs['placeholder'] = 'email'

    def _find_user_account(self, identifier):
        model = get_account_model('user')
        by_email = model.objects.filter(email__iexact=identifier).first()
        if by_email is not None:
            return by_email

        norm = normalize_phone(identifier)
        if not norm:
            return None
        matches = [
            u for u in model.objects.exclude(phone_number='')
            if normalize_phone(u.phone_number) == norm
        ]
        if len(matches) > 1:
            raise ValidationError(
                'Multiple accounts share that phone number. Please log in with your email.'
            )
        return matches[0] if matches else None

    def clean(self):
        cleaned = super().clean()
        role = self.role
        identifier = (cleaned.get('email') or '').strip()
        password = cleaned.get('password')

        if role and identifier and password:
            if role == 'user':
                account = self._find_user_account(identifier)
                invalid_msg = 'Invalid email/phone number or password.'
            else:
                account = get_account_model(role).objects.filter(email__iexact=identifier).first()
                invalid_msg = 'Invalid email or password.'

            if account is None or not account.check_password(password):
                raise ValidationError(invalid_msg)
            if role == 'pharmacy' and not account.is_active:
                raise ValidationError('This pharmacy account has been deactivated.')
            self.account = account
        return cleaned


class BaseForgotPasswordForm(forms.Form):
    """Shared password-reset validation across User and Pharmacy accounts."""

    model = None
    phone_field = 'phone_number'
    phone_label = 'Registered Phone Number:'
    not_found_msg = 'No account matched that email and phone number.'

    email = forms.EmailField(
        label='Registered Email:',
        widget=forms.EmailInput(attrs={
            'class': 'login-input',
            'placeholder': 'email',
            'autocomplete': 'email',
            'autofocus': True,
        }),
    )
    phone_number = forms.CharField(
        label='Registered Phone Number:',
        widget=forms.TextInput(attrs={
            'class': 'login-input',
            'placeholder': '+63 XXX XXX XXXX',
            'autocomplete': 'tel',
        }),
    )
    new_password1 = forms.CharField(
        label='New Password:',
        widget=forms.PasswordInput(attrs={
            'class': 'login-input',
            'placeholder': 'new password',
            'autocomplete': 'new-password',
        }),
    )
    new_password2 = forms.CharField(
        label='Confirm New Password:',
        widget=forms.PasswordInput(attrs={
            'class': 'login-input',
            'placeholder': 'confirm new password',
            'autocomplete': 'new-password',
        }),
    )

    account = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone_number'].label = self.phone_label

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get('email') or '').strip().lower()
        phone = cleaned.get('phone_number') or ''
        p1 = cleaned.get('new_password1')
        p2 = cleaned.get('new_password2')

        if p1 and p2 and p1 != p2:
            self.add_error('new_password2', "The two passwords don't match.")

        if email and phone:
            account = self.model.objects.filter(email__iexact=email).first()
            norm_input = normalize_phone(phone)
            stored_phone = getattr(account, self.phone_field, '') if account else ''
            if account is None or not norm_input or normalize_phone(stored_phone) != norm_input:
                raise ValidationError(self.not_found_msg)
            self.account = account

        if p1 and self.account:
            try:
                password_validation.validate_password(p1)
            except ValidationError as error:
                self.add_error('new_password1', error)

        return cleaned

    def save(self):
        self.account.set_password(self.cleaned_data['new_password1'])
        fields = ['password_hash', 'updated_at'] if hasattr(self.account, 'updated_at') else ['password_hash']
        self.account.save(update_fields=fields)
        return self.account


class ForgotPasswordForm(BaseForgotPasswordForm):
    """Reset a user's password by verifying registered email and phone number."""

    model = User
    phone_field = 'phone_number'
    phone_label = 'Registered Phone Number:'


class PharmacyForgotPasswordForm(BaseForgotPasswordForm):
    """Reset a pharmacy's password by verifying registered email and contact number."""

    model = Pharmacy
    phone_field = 'contact_number'
    phone_label = 'Registered Contact Number:'
    not_found_msg = 'No pharmacy account matched that email and contact number.'


class AccountPasswordChangeForm(forms.Form):
    """Allow a logged-in User or Pharmacy account to change its password."""

    current_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Current password',
            'autocomplete': 'current-password',
        }),
    )
    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'New password',
            'autocomplete': 'new-password',
        }),
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
        }),
    )

    def __init__(self, *args, account=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account if account is not None else user

    def clean_current_password(self):
        current = self.cleaned_data.get('current_password')
        if self.account and not self.account.check_password(current):
            raise ValidationError('Current password is incorrect.')
        return current

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password1')
        p2 = cleaned.get('new_password2')
        if p1 and p2 and p1 != p2:
            self.add_error('new_password2', "The two new passwords don't match.")
        if p1:
            try:
                password_validation.validate_password(p1)
            except ValidationError as error:
                self.add_error('new_password1', error)
        return cleaned

    def save(self):
        self.account.set_password(self.cleaned_data['new_password1'])
        fields = ['password_hash', 'updated_at'] if hasattr(self.account, 'updated_at') else ['password_hash']
        self.account.save(update_fields=fields)
        return self.account
