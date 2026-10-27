import uuid

from django.contrib import messages
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_time
from django.views.decorators.http import require_POST

from login_app.utils import log_activity
from medfind_project.session_auth import role_required

from .forms import InventoryForm, VerificationUploadForm
from .models import Inventory, OperatingHours, PharmacyVerification


@role_required('pharmacy')
def dashboard_view(request):
    pharmacy = request.account
    items = Inventory.objects.filter(pharmacy=pharmacy)
    context = {
        'pharmacy': pharmacy,
        'item_count': items.count(),
        'low_count': items.filter(availability_status__in=['low_stock', 'out_of_stock']).count(),
        'hours_set': OperatingHours.objects.filter(pharmacy=pharmacy).count(),
        'latest_verification': pharmacy.verifications.first(),
    }
    return render(request, 'pharmacy_template/dashboard.html', context)


#Inventory

@role_required('pharmacy')
def inventory_list_view(request):
    items = (Inventory.objects.filter(pharmacy=request.account)
             .select_related('medicine', 'medicine__category')
             .order_by('medicine__medicine_name'))
    return render(request, 'pharmacy_template/inventory.html', {'items': items})


@role_required('pharmacy')
def inventory_add_view(request):
    if request.method == 'POST':
        form = InventoryForm(request.POST, pharmacy=request.account)
        if form.is_valid():
            item = form.save(commit=False)
            item.pharmacy = request.account
            item.save()
            log_activity('pharmacy', request.account.pk, 'inventory_add',
                         f'Added {item.medicine.medicine_name} to inventory.')
            messages.success(request, f'{item.medicine.medicine_name} added to your inventory.')
            return redirect('pharmacy_inventory')
    else:
        form = InventoryForm(pharmacy=request.account)
    return render(request, 'pharmacy_template/inventory_form.html', {'form': form, 'mode': 'Add'})


@role_required('pharmacy')
def inventory_edit_view(request, inventory_id):
    item = get_object_or_404(Inventory, pk=inventory_id, pharmacy=request.account)
    if request.method == 'POST':
        form = InventoryForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            log_activity('pharmacy', request.account.pk, 'inventory_update',
                         f'Updated {item.medicine.medicine_name}.')
            messages.success(request, 'Inventory item updated.')
            return redirect('pharmacy_inventory')
    else:
        form = InventoryForm(instance=item)
    return render(request, 'pharmacy_template/inventory_form.html', {'form': form, 'mode': 'Edit'})


@role_required('pharmacy')
@require_POST
def inventory_delete_view(request, inventory_id):
    item = get_object_or_404(Inventory, pk=inventory_id, pharmacy=request.account)
    name = item.medicine.medicine_name
    item.delete()
    log_activity('pharmacy', request.account.pk, 'inventory_remove', f'Removed {name}.')
    messages.info(request, f'{name} removed from your inventory.')
    return redirect('pharmacy_inventory')


#Operating hours

def _hours_rows(pharmacy):
    existing = {h.days_of_week: h for h in OperatingHours.objects.filter(pharmacy=pharmacy)}
    rows = []
    for day, label in OperatingHours.DAY_CHOICES:
        h = existing.get(day)
        rows.append({
            'day': day,
            'label': label,
            'opening': h.opening_time if h else None,
            'closing': h.closing_time if h else None,
            'is_closed': h.is_closed if h else False,
        })
    return rows


@role_required('pharmacy')
def hours_view(request):
    pharmacy = request.account

    if request.method == 'POST':
        rows, ok = [], True
        for day, label in OperatingHours.DAY_CHOICES:
            is_closed = request.POST.get(f'closed_{day}') == 'on'
            try:
                opening = parse_time(request.POST.get(f'open_{day}', '') or '')
                closing = parse_time(request.POST.get(f'close_{day}', '') or '')
            except ValueError:
                opening = closing = None
            if not is_closed and (opening is None or closing is None or opening >= closing):
                ok = False
            rows.append({'day': day, 'label': label, 'opening': opening,
                         'closing': closing, 'is_closed': is_closed})

        if ok:
            for r in rows:
                OperatingHours.objects.update_or_create(
                    pharmacy=pharmacy,
                    days_of_week=r['day'],
                    defaults={
                        'opening_time': None if r['is_closed'] else r['opening'],
                        'closing_time': None if r['is_closed'] else r['closing'],
                        'is_closed': r['is_closed'],
                    },
                )
            log_activity('pharmacy', pharmacy.pk, 'hours_update', 'Updated operating hours.')
            messages.success(request, 'Operating hours saved.')
            return redirect('pharmacy_hours')
        messages.error(
            request,
            'Every open day needs an opening time that is earlier than its closing time.'
        )
    else:
        rows = _hours_rows(pharmacy)

    return render(request, 'pharmacy_template/hours.html', {'rows': rows})


#Verification

@role_required('pharmacy')
def verification_view(request):
    pharmacy = request.account
    submissions = pharmacy.verifications.select_related('reviewed_by')
    has_pending = submissions.filter(status=PharmacyVerification.STATUS_PENDING).exists()

    if request.method == 'POST':
        if has_pending:
            messages.error(request, 'You already have a submission waiting for review.')
            return redirect('pharmacy_verification')
        form = VerificationUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.cleaned_data['document']
            saved_path = default_storage.save(
                f'verification_docs/pharmacy_{pharmacy.pk}/{uuid.uuid4().hex[:8]}_{doc.name}',
                doc,
            )
            PharmacyVerification.objects.create(
                pharmacy=pharmacy,
                document_path=saved_path,
                status=PharmacyVerification.STATUS_PENDING,
            )
            pharmacy.verification_status = pharmacy.VERIFICATION_PENDING
            pharmacy.save(update_fields=['verification_status', 'updated_at'])
            log_activity('pharmacy', pharmacy.pk, 'verification_submit', 'Submitted verification document.')
            messages.success(request, 'Document submitted. An admin will review it soon.')
            return redirect('pharmacy_verification')
    else:
        form = VerificationUploadForm()

    return render(request, 'pharmacy_template/verification.html', {
        'form': form,
        'submissions': submissions,
        'has_pending': has_pending,
        'pharmacy': pharmacy,
    })
