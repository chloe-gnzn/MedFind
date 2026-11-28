from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from home_app.models import Medicine, MedicineCategory

from .models import Admin


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')


class CategoryForm(StyledModelForm):
    class Meta:
        model = MedicineCategory
        fields = ['category_name', 'description']
        widgets = {
            # category_name is a text column in the ERD; a one-line input is friendlier
            'category_name': forms.TextInput(attrs={'placeholder': 'e.g. Pain relievers'}),
            'description': forms.TextInput(attrs={'placeholder': 'Short description'}),
        }


class MedicineForm(StyledModelForm):
    class Meta:
        model = Medicine
        fields = ['medicine_name', 'generic_name', 'category', 'form', 'strength', 'description']
        widgets = {
            'medicine_name': forms.TextInput(attrs={'placeholder': 'Brand name, e.g. Biogesic'}),
            'generic_name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol'}),
            'form': forms.TextInput(attrs={'placeholder': 'tablet, capsule, syrup...'}),
            'strength': forms.TextInput(attrs={'placeholder': 'e.g. 500 mg'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class AdminProfileForm(StyledModelForm):
    """Edit the logged-in admin's ERD profile fields."""

    class Meta:
        model = Admin
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email Address',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'admin@example.com'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if Admin.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Another admin account is already using this email.')
        return email


class AdminCreateForm(StyledModelForm):
    """Allow a super_admin to create a new Admin account."""

    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm password', 'autocomplete': 'new-password'}),
    )

    class Meta:
        model = Admin
        fields = ['first_name', 'last_name', 'email', 'role']
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email Address',
            'role': 'Role',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'admin@example.com'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if Admin.objects.filter(email__iexact=email).exists():
            raise ValidationError('An admin account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', "The two passwords don't match.")
        if p1:
            try:
                password_validation.validate_password(p1)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned

    def save(self, commit=True):
        admin = super().save(commit=False)
        admin.set_password(self.cleaned_data['password1'])
        if commit:
            admin.save()
        return admin
