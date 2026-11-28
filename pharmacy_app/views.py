import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.files.storage import default_storage
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_time
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from admin_app.models import ActivityLog
from home_app.models import MedicineCategory
from login_app.forms import AccountPasswordChangeForm
from login_app.utils import log_activity
from medfind_project.session_auth import ROLE_HOME, SESSION_ROLE, get_account, role_required
from register_app.forms import PharmacyRegisterForm

from .forms import InventoryForm, PharmacyProfileForm, VerificationUploadForm
from .models import Inventory, OperatingHours, PharmacyVerification
from .utils import format_hours_span, is_24_hours, open_now_map

INVENTORY_SORTS = {
    'name': 'medicine__medicine_name',
    'price_asc': 'price',
    'price_desc': '-price',
    'stock_asc': 'stock_quantity',
    'stock_desc': '-stock_quantity',
    'updated': '-updated_at',
}


def pharmacy_register_view(request):
    """Register a pharmacy (starts as 'pending' until an admin verifies it)."""
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])

    if request.method == 'POST':
        form = PharmacyRegisterForm(request.POST)
        if form.is_valid():
            pharmacy = form.save()
            log_activity('pharmacy', pharmacy.pk, 'register',
                         f'Pharmacy {pharmacy.business_name} registered.')
            messages.success(
                request,
                'Pharmacy registered! Log in and submit your documents so an admin can verify you.'
            )
            return redirect('pharmacy_login')
        messages.error(request, 'Please fix the errors below and try again.')
    else:
        form = PharmacyRegisterForm()

    return render(request, 'register_template/register_pharmacy.html', {
        'form': form,
        'title': 'Register your pharmacy',
    })


@role_required('pharmacy')
def dashboard_view(request):
    pharmacy = request.account
    items = Inventory.objects.filter(pharmacy=pharmacy).select_related('medicine')
    low_items = items.filter(
        availability_status__in=[Inventory.STATUS_LOW, Inventory.STATUS_OUT]
    ).order_by('stock_quantity', 'medicine__medicine_name')

    today_row = OperatingHours.objects.filter(
        pharmacy=pharmacy,
        days_of_week=timezone.localtime().weekday(),
    ).first()
    hours_text = (
        format_hours_span(today_row.opening_time, today_row.closing_time)
        if today_row and not today_row.is_closed
        else ''
    )

    context = {
        'pharmacy': pharmacy,
        'item_count': items.count(),
        'low_count': low_items.count(),
        'low_items': low_items[:5],
        'hours_set': OperatingHours.objects.filter(pharmacy=pharmacy).count(),
        'open_now': open_now_map([pharmacy.pk])[pharmacy.pk],
        'hours_text': hours_text,
        'favorite_count': pharmacy.favorites.count(),
        'latest_verification': pharmacy.verifications.first(),
        'recent_logs': ActivityLog.objects.filter(
            actor_type=ActivityLog.ACTOR_PHARMACY,
            actor_id=pharmacy.pk,
        )[:5],
    }
    return render(request, 'pharmacy_template/dashboard.html', context)


# Inventory

@role_required('pharmacy')
def inventory_list_view(request):
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    status = request.GET.get('status', '').strip()
    sort = request.GET.get('sort', 'name').strip()
    if sort not in INVENTORY_SORTS:
        sort = 'name'

    items = (
        Inventory.objects.filter(pharmacy=request.account)
        .select_related('medicine', 'medicine__category')
    )
    if q:
        items = items.filter(
            Q(medicine__medicine_name__icontains=q) | Q(medicine__generic_name__icontains=q)
        )
    if category_id.isdigit():
        items = items.filter(medicine__category_id=int(category_id))
    if status == 'low_or_out':
        items = items.filter(availability_status__in=[Inventory.STATUS_LOW, Inventory.STATUS_OUT])
    elif status in (Inventory.STATUS_AVAILABLE, Inventory.STATUS_LOW, Inventory.STATUS_OUT):
        items = items.filter(availability_status=status)

    items = items.order_by(INVENTORY_SORTS[sort], 'medicine__medicine_name')
    categories = MedicineCategory.objects.filter(
        medicines__inventory_items__pharmacy=request.account
    ).distinct().order_by('category_name')

    return render(request, 'pharmacy_template/inventory.html', {
        'items': items,
        'q': q,
        'category_id': category_id,
        'status': status,
        'sort': sort,
        'categories': categories,
        'availability_choices': Inventory.AVAILABILITY_CHOICES,
    })


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
def inventory_quick_update_view(request, inventory_id):
    item = get_object_or_404(Inventory, pk=inventory_id, pharmacy=request.account)
    try:
        price = Decimal((request.POST.get('price') or '').strip())
        stock_quantity = int((request.POST.get('stock_quantity') or '').strip())
    except (InvalidOperation, ValueError):
        messages.error(request, 'Please enter a valid price and whole-number stock quantity.')
        return redirect('pharmacy_inventory')

    if price < 0 or stock_quantity < 0:
        messages.error(request, 'Price and stock quantity cannot be negative.')
        return redirect('pharmacy_inventory')

    requested_status = request.POST.get('availability_status', item.availability_status)
    if stock_quantity == 0:
        availability_status = Inventory.STATUS_OUT
    elif requested_status == Inventory.STATUS_LOW:
        availability_status = Inventory.STATUS_LOW
    else:
        availability_status = Inventory.STATUS_AVAILABLE

    item.price = price
    item.stock_quantity = stock_quantity
    item.availability_status = availability_status
    item.save()

    log_activity(
        'pharmacy', request.account.pk, 'inventory_update',
        f'Quick-updated {item.medicine.medicine_name} (₱{item.price:.2f}, stock: {item.stock_quantity}).',
    )
    messages.success(request, f'Updated {item.medicine.medicine_name}.')

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('pharmacy_inventory')


@role_required('pharmacy')
@require_POST
def inventory_delete_view(request, inventory_id):
    item = get_object_or_404(Inventory, pk=inventory_id, pharmacy=request.account)
    name = item.medicine.medicine_name
    item.delete()
    log_activity('pharmacy', request.account.pk, 'inventory_remove', f'Removed {name}.')
    messages.info(request, f'{name} removed from your inventory.')
    return redirect('pharmacy_inventory')


# Operating hours

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
            if not is_closed:
                if opening is None or closing is None:
                    ok = False
                elif opening == closing and not is_24_hours(opening, closing):
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
            'Each open day needs valid opening and closing times (use 00:00–23:59 or 00:00–00:00 for 24 hours).'
        )
    else:
        rows = _hours_rows(pharmacy)

    return render(request, 'pharmacy_template/hours.html', {'rows': rows})


# Verification

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


@role_required('pharmacy')
@require_POST
def verification_cancel_view(request, verification_id):
    pharmacy = request.account
    submission = get_object_or_404(
        PharmacyVerification,
        pk=verification_id,
        pharmacy=pharmacy,
        status=PharmacyVerification.STATUS_PENDING,
    )
    doc_path = submission.document_path
    submission.delete()
    if doc_path and default_storage.exists(doc_path):
        default_storage.delete(doc_path)

    previous = pharmacy.verifications.first()
    if previous and previous.status == PharmacyVerification.STATUS_REJECTED:
        pharmacy.verification_status = pharmacy.VERIFICATION_REJECTED
    elif previous and previous.status == PharmacyVerification.STATUS_APPROVED:
        pharmacy.verification_status = pharmacy.VERIFICATION_APPROVED
    else:
        pharmacy.verification_status = pharmacy.VERIFICATION_PENDING
    pharmacy.save(update_fields=['verification_status', 'updated_at'])

    log_activity('pharmacy', pharmacy.pk, 'verification_cancel', 'Withdrew pending verification submission.')
    messages.info(request, 'Pending verification submission withdrawn. You can upload a new file.')
    return redirect('pharmacy_verification')


# Profile & Activity

ACTIVITY_GROUPS = {
    'inventory': ('inventory_add', 'inventory_update', 'inventory_remove'),
    'hours': ('hours_update',),
    'verification': ('verification_submit', 'verification_cancel'),
    'account': ('register', 'login', 'logout', 'profile_update', 'password_change', 'password_reset', 'photo_remove'),
}


@role_required('pharmacy')
def profile_view(request):
    pharmacy = request.account
    profile_form = PharmacyProfileForm(instance=pharmacy)
    password_form = AccountPasswordChangeForm(account=pharmacy)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            old_photo_name = pharmacy.photo.name if pharmacy.photo else ''
            profile_form = PharmacyProfileForm(request.POST, request.FILES, instance=pharmacy)
            if profile_form.is_valid():
                updated = profile_form.save()
                if old_photo_name and updated.photo.name != old_photo_name and default_storage.exists(old_photo_name):
                    default_storage.delete(old_photo_name)
                log_activity('pharmacy', updated.pk, 'profile_update',
                             f'Updated pharmacy profile for {updated.business_name}.')
                messages.success(request, 'Pharmacy profile updated.')
                return redirect('pharmacy_profile')
        elif action == 'remove_photo':
            if pharmacy.photo:
                old_photo_name = pharmacy.photo.name
                pharmacy.photo = ''
                pharmacy.save(update_fields=['photo', 'updated_at'])
                if old_photo_name and default_storage.exists(old_photo_name):
                    default_storage.delete(old_photo_name)
                log_activity('pharmacy', pharmacy.pk, 'photo_remove', 'Removed pharmacy storefront photo.')
                messages.info(request, 'Storefront photo removed.')
            return redirect('pharmacy_profile')
        elif action == 'change_password':
            password_form = AccountPasswordChangeForm(request.POST, account=pharmacy)
            if password_form.is_valid():
                updated = password_form.save()
                log_activity('pharmacy', updated.pk, 'password_change',
                             f'Pharmacy {updated.email} changed password.')
                messages.success(request, 'Your password has been changed.')
                return redirect('pharmacy_profile')

    return render(request, 'pharmacy_template/profile.html', {
        'pharmacy': pharmacy,
        'profile_form': profile_form,
        'password_form': password_form,
        'favorite_count': pharmacy.favorites.count(),
        'item_count': Inventory.objects.filter(pharmacy=pharmacy).count(),
        'activity_count': ActivityLog.objects.filter(
            actor_type=ActivityLog.ACTOR_PHARMACY, actor_id=pharmacy.pk
        ).count(),
    })


@role_required('pharmacy')
def activity_view(request):
    pharmacy = request.account
    group = request.GET.get('group', 'all').strip()
    logs = ActivityLog.objects.filter(
        actor_type=ActivityLog.ACTOR_PHARMACY,
        actor_id=pharmacy.pk,
    )
    if group in ACTIVITY_GROUPS:
        logs = logs.filter(action__in=ACTIVITY_GROUPS[group])
    else:
        group = 'all'

    return render(request, 'pharmacy_template/activity.html', {
        'logs': logs[:200],
        'group': group,
    })
