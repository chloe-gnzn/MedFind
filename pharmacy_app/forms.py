import re

from django import forms
from django.core.exceptions import ValidationError

from home_app.models import Medicine, MedicineCategory

from .models import Inventory, Pharmacy


def _norm_text(value):
    return ' '.join((value or '').split())


def _norm_key(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def _norm_strength(value):
    cleaned = _norm_text(value)
    return re.sub(r'(\d)\s+(?=[a-zA-Z])', r'\1', cleaned)


def _norm_form(value):
    cleaned = _norm_text(value)
    return cleaned.title() if cleaned else ''


def _norm_display_name(value):
    cleaned = _norm_text(value)
    if not cleaned:
        return ''
    return cleaned.title() if cleaned == cleaned.lower() else cleaned

ALLOWED_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png')
ALLOWED_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')
MAX_UPLOAD_MB = 5


class InventoryForm(forms.ModelForm):
    medicine_query = forms.CharField(
        required=False,
        max_length=255,
        label='Medicine',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Type a medicine name (e.g. Biogesic, Amoxicillin)...',
                'autocomplete': 'off',
            }
        ),
    )
    new_category = forms.ModelChoiceField(
        required=False,
        queryset=MedicineCategory.objects.all().order_by('category_name'),
        empty_label='Default category (General)',
        label='Category (optional)',
    )
    new_generic_name = forms.CharField(
        required=False,
        max_length=255,
        label='Generic name (optional)',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol'}),
    )
    new_form = forms.CharField(
        required=False,
        max_length=100,
        label='Dosage form (optional)',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Tablet, Syrup, Capsule'}),
    )
    new_strength = forms.CharField(
        required=False,
        max_length=100,
        label='Strength (optional)',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. 500mg, 100mg/5mL'}),
    )

    class Meta:
        model = Inventory
        fields = ['medicine', 'price', 'availability_status', 'stock_quantity']
        widgets = {
            'price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'stock_quantity': forms.NumberInput(attrs={'min': '0'}),
        }

    def __init__(self, *args, pharmacy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pharmacy = pharmacy
        self._new_medicine_attrs = None
        if self.instance.pk:
            # editing: the medicine can't be swapped, only its price/stock
            self.fields['medicine'].disabled = True
            for extra in (
                'medicine_query',
                'new_category',
                'new_generic_name',
                'new_form',
                'new_strength',
            ):
                self.fields.pop(extra, None)
        else:
            self.fields['medicine'].required = False
            self.fields['medicine'].widget = forms.HiddenInput()
            if pharmacy is not None:
                self.fields['medicine'].queryset = Medicine.objects.exclude(
                    inventory_items__pharmacy=pharmacy
                )
            self.order_fields([
                'medicine_query',
                'medicine',
                'new_category',
                'new_generic_name',
                'new_form',
                'new_strength',
                'price',
                'availability_status',
                'stock_quantity',
            ])
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault('class', 'form-input')

    def _match_catalog_candidates(self, query, new_form='', new_strength=''):
        """Find catalog medicines matching a typed query + optional form/strength without creating duplicates."""
        q_lower = query.lower()
        q_key = _norm_key(query)
        form_key = _norm_key(new_form)
        strength_key = _norm_key(new_strength)

        matches = []
        for med in Medicine.objects.select_related('category').all():
            label = f'{med.medicine_name} ({med.strength} {med.form})'
            name_key = _norm_key(med.medicine_name)
            name_strength_key = _norm_key(f'{med.medicine_name} {med.strength}')
            full_key = _norm_key(label)

            if not (
                label.lower() == q_lower
                or name_key == q_key
                or name_strength_key == q_key
                or full_key == q_key
            ):
                continue

            if form_key and _norm_key(med.form) != form_key:
                continue
            if strength_key and _norm_key(med.strength) != strength_key:
                continue
            matches.append(med)
        return matches

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            med = cleaned.get('medicine')
            query = _norm_text(cleaned.get('medicine_query'))
            new_form = _norm_form(cleaned.get('new_form'))
            new_strength = _norm_strength(cleaned.get('new_strength'))

            if med is None:
                if not query:
                    self.add_error('medicine_query', 'Please type the medicine you want to add.')
                else:
                    all_matches = self._match_catalog_candidates(query, new_form, new_strength)
                    stocked_ids = set()
                    if self.pharmacy is not None:
                        stocked_ids = set(
                            Inventory.objects.filter(pharmacy=self.pharmacy).values_list('medicine_id', flat=True)
                        )

                    available_matches = [m for m in all_matches if m.pk not in stocked_ids]
                    stocked_matches = [m for m in all_matches if m.pk in stocked_ids]

                    if len(available_matches) == 1:
                        cleaned['medicine'] = available_matches[0]
                    elif len(available_matches) > 1:
                        self.add_error(
                            'medicine_query',
                            'Multiple strengths or forms match that name. Please pick one from the dropdown.',
                        )
                    elif stocked_matches:
                        m = stocked_matches[0]
                        self.add_error(
                            'medicine_query',
                            f'"{m.medicine_name} ({m.strength} {m.form})" is already in your inventory.',
                        )
                    else:
                        display_name = _norm_display_name(query)
                        generic_raw = _norm_text(cleaned.get('new_generic_name'))
                        self._new_medicine_attrs = {
                            'medicine_name': display_name,
                            'category': cleaned.get('new_category'),
                            'generic_name': _norm_display_name(generic_raw) if generic_raw else display_name,
                            'form': new_form or 'Unit',
                            'strength': new_strength or 'Standard',
                        }

        stock = cleaned.get('stock_quantity')
        status = cleaned.get('availability_status')
        if stock is not None and status:
            if stock == 0 and status != Inventory.STATUS_OUT:
                self.add_error(
                    'availability_status',
                    'Stock quantity is 0, so availability must be Out of stock.',
                )
            elif stock > 0 and status == Inventory.STATUS_OUT:
                self.add_error(
                    'availability_status',
                    'Out of stock items must have a stock quantity of 0.',
                )
        return cleaned

    def save(self, commit=True):
        if not self.instance.pk and self.cleaned_data.get('medicine') is None and self._new_medicine_attrs:
            attrs = self._new_medicine_attrs
            # Double-check catalog one more time right before insert to avoid duplicates across concurrent adds
            existing = self._match_catalog_candidates(
                attrs['medicine_name'], attrs['form'], attrs['strength']
            )
            if existing:
                self.instance.medicine = existing[0]
            else:
                category = attrs['category']
                if category is None:
                    category = MedicineCategory.objects.order_by('category_id').first()
                    if category is None:
                        category, _ = MedicineCategory.objects.get_or_create(
                            category_name='General',
                            defaults={'description': 'General medicines and pharmacy essentials.'},
                        )
                self.instance.medicine = Medicine.objects.create(
                    category=category,
                    medicine_name=attrs['medicine_name'],
                    generic_name=attrs['generic_name'],
                    form=attrs['form'],
                    strength=attrs['strength'],
                )
        return super().save(commit=commit)


class VerificationUploadForm(forms.Form):
    document = forms.FileField(
        label='Business permit / license (PDF, JPG or PNG, max 5 MB)',
        widget=forms.ClearableFileInput(attrs={'class': 'form-input'}),
    )

    def clean_document(self):
        doc = self.cleaned_data['document']
        if not doc.name.lower().endswith(ALLOWED_EXTENSIONS):
            raise forms.ValidationError('Please upload a PDF, JPG or PNG file.')
        if doc.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f'File is too large (max {MAX_UPLOAD_MB} MB).')
        return doc


class PharmacyProfileForm(forms.ModelForm):
    """Edit the logged-in pharmacy's ERD profile fields and storefront photo."""

    class Meta:
        model = Pharmacy
        fields = ['business_name', 'email', 'contact_number', 'address', 'photo']
        labels = {
            'business_name': 'Pharmacy Name',
            'email': 'Email Address',
            'contact_number': 'Contact Number',
            'address': 'Address',
            'photo': 'Storefront / Profile Picture (JPG, PNG, WebP, max 5 MB)',
        }
        widgets = {
            'business_name': forms.TextInput(attrs={'placeholder': 'Pharmacy / drugstore name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@example.com', 'autocomplete': 'email'}),
            'contact_number': forms.TextInput(attrs={'placeholder': '+63 XXX XXX XXXX', 'autocomplete': 'tel'}),
            'address': forms.TextInput(attrs={'placeholder': 'Street, barangay, city'}),
            'photo': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-input')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if Pharmacy.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Another pharmacy account is already using this email address.')
        return email

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        # Only validate newly uploaded files, not an already-saved FieldFile
        if photo and hasattr(photo, 'content_type'):
            if not photo.name.lower().endswith(ALLOWED_IMAGE_EXTENSIONS):
                raise ValidationError('Please upload a JPG, PNG, or WebP image.')
            if photo.size > MAX_UPLOAD_MB * 1024 * 1024:
                raise ValidationError(f'Image is too large (max {MAX_UPLOAD_MB} MB).')
        return photo
