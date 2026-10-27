from django import forms

from medfind_project.session_auth import get_account_model


class LoginForm(forms.Form):
    """Email + password login for any of the three ERD account types."""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
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
        # The role is decided by WHICH login page is used (/, /pharmacy-portal/login/,
        # /manage/login/), not by a dropdown the visitor can change.
        super().__init__(*args, **kwargs)
        self.role = role

    def clean(self):
        cleaned = super().clean()
        role = self.role
        email = cleaned.get('email')
        password = cleaned.get('password')

        if role and email and password:
            account = get_account_model(role).objects.filter(email__iexact=email.strip()).first()
            if account is None or not account.check_password(password):
                raise forms.ValidationError(
                    'Invalid email or password.'
                )
            if role == 'pharmacy' and not account.is_active:
                raise forms.ValidationError('This pharmacy account has been deactivated.')
            self.account = account
        return cleaned
