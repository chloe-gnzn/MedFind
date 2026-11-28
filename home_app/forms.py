from django import forms
from django.core.exceptions import ValidationError

from login_app.forms import AccountPasswordChangeForm
from .models import User

UserPasswordChangeForm = AccountPasswordChangeForm


class UserProfileForm(forms.ModelForm):
    """Edit the logged-in user's ERD profile fields."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number']
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email Address',
            'phone_number': 'Phone Number',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First name', 'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last name', 'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@example.com', 'autocomplete': 'email'}),
            'phone_number': forms.TextInput(attrs={'placeholder': '+63 XXX XXX XXXX', 'autocomplete': 'tel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Another account is already using this email address.')
        return email
