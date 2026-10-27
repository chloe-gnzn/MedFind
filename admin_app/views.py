from django.contrib import messages
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from home_app.models import Medicine, MedicineCategory, User
from login_app.utils import log_activity
from medfind_project.session_auth import role_required
from pharmacy_app.models import Pharmacy, PharmacyVerification

from .forms import CategoryForm, MedicineForm
from .models import ActivityLog, Admin


@role_required('admin')
def dashboard_view(request):
    return render(request, 'admin_template/dashboard.html', {
        'user_count': User.objects.count(),
        'pharmacy_count': Pharmacy.objects.count(),
        'pending_count': PharmacyVerification.objects.filter(status='pending').count(),
        'medicine_count': Medicine.objects.count(),
        'category_count': MedicineCategory.objects.count(),
        'recent_logs': _with_actor_names(ActivityLog.objects.all()[:8]),
    })


# ------------------------------------------------------------ Verifications

@role_required('admin')
def verifications_view(request):
    status = request.GET.get('status', 'pending')
    rows = PharmacyVerification.objects.select_related('pharmacy', 'reviewed_by')
    if status in ('pending', 'approved', 'rejected'):
        rows = rows.filter(status=status)
    else:
        status = 'all'
    return render(request, 'admin_app/verifications.html', {'rows': rows, 'status': status})


@role_required('admin')
def verification_review_view(request, verification_id):
    verification = get_object_or_404(
        PharmacyVerification.objects.select_related('pharmacy', 'reviewed_by'),
        pk=verification_id,
    )

    if request.method == 'POST':
        decision = request.POST.get('decision')
        remarks = request.POST.get('remarks', '').strip()

        if verification.status != PharmacyVerification.STATUS_PENDING:
            messages.error(request, 'This submission has already been reviewed.')
        elif decision not in ('approved', 'rejected'):
            messages.error(request, 'Please choose approve or reject.')
        elif decision == 'rejected' and not remarks:
            messages.error(request, 'Please add remarks explaining the rejection.')
        else:
            verification.status = decision
            verification.reviewed_by = request.account
            verification.reviewed_at = timezone.now()
            verification.remarks = remarks
            verification.save()

            pharmacy = verification.pharmacy
            pharmacy.verification_status = decision
            pharmacy.save(update_fields=['verification_status', 'updated_at'])

            log_activity('admin', request.account.pk, f'verification_{decision}',
                         f'{decision.title()} pharmacy {pharmacy.business_name}.')
            messages.success(request, f'{pharmacy.business_name} was {decision}.')
            return redirect('admin_verifications')

    return render(request, 'admin_app/verification_review.html', {'v': verification})


# ---------------------------------------------------------- Pharmacies/users

@role_required('admin')
def pharmacies_view(request):
    return render(request, 'admin_app/pharmacies.html', {'pharmacies': Pharmacy.objects.all()})


@role_required('admin')
@require_POST
def pharmacy_toggle_view(request, pharmacy_id):
    pharmacy = get_object_or_404(Pharmacy, pk=pharmacy_id)
    pharmacy.is_active = not pharmacy.is_active
    pharmacy.save(update_fields=['is_active', 'updated_at'])
    state = 'activated' if pharmacy.is_active else 'deactivated'
    log_activity('admin', request.account.pk, f'pharmacy_{state}', f'{state.title()} {pharmacy.business_name}.')
    messages.success(request, f'{pharmacy.business_name} {state}.')
    return redirect('admin_pharmacies')


@role_required('admin')
def users_view(request):
    return render(request, 'admin_app/users.html', {'users': User.objects.all()})


# --------------------------------------------------------------- Categories

@role_required('admin')
def categories_view(request):
    categories = MedicineCategory.objects.annotate(med_count=Count('medicines'))
    return render(request, 'admin_app/categories.html', {'categories': categories})


@role_required('admin')
def category_form_view(request, category_id=None):
    category = get_object_or_404(MedicineCategory, pk=category_id) if category_id else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        log_activity('admin', request.account.pk, 'category_save', f'Saved category {saved.category_name}.')
        messages.success(request, 'Category saved.')
        return redirect('admin_categories')
    return render(request, 'admin_app/form.html', {
        'form': form,
        'title': 'Edit category' if category else 'Add category',
        'back_url': 'admin_categories',
    })


@role_required('admin')
def category_delete_view(request, category_id):
    category = get_object_or_404(MedicineCategory, pk=category_id)
    if request.method == 'POST':
        try:
            category.delete()
            log_activity('admin', request.account.pk, 'category_delete', f'Deleted category {category.category_name}.')
            messages.info(request, 'Category deleted.')
        except ProtectedError:
            messages.error(request, 'This category still has medicines. Move or delete them first.')
        return redirect('admin_categories')
    return render(request, 'admin_app/confirm_delete.html', {
        'what': f'category "{category.category_name}"', 'back_url': 'admin_categories'})


# ---------------------------------------------------------------- Medicines

@role_required('admin')
def medicines_view(request):
    return render(request, 'admin_app/medicines.html', {
        'medicines': Medicine.objects.select_related('category')})


@role_required('admin')
def medicine_form_view(request, medicine_id=None):
    medicine = get_object_or_404(Medicine, pk=medicine_id) if medicine_id else None
    form = MedicineForm(request.POST or None, instance=medicine)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        log_activity('admin', request.account.pk, 'medicine_save', f'Saved medicine {saved.medicine_name}.')
        messages.success(request, 'Medicine saved.')
        return redirect('admin_medicines')
    return render(request, 'admin_app/form.html', {
        'form': form,
        'title': 'Edit medicine' if medicine else 'Add medicine',
        'back_url': 'admin_medicines',
    })


@role_required('admin')
def medicine_delete_view(request, medicine_id):
    medicine = get_object_or_404(Medicine, pk=medicine_id)
    if request.method == 'POST':
        name = medicine.medicine_name
        medicine.delete()
        log_activity('admin', request.account.pk, 'medicine_delete', f'Deleted medicine {name}.')
        messages.info(request, 'Medicine deleted.')
        return redirect('admin_medicines')
    return render(request, 'admin_app/confirm_delete.html', {
        'what': f'medicine "{medicine.medicine_name}" (this also removes it from every pharmacy inventory and favorites)',
        'back_url': 'admin_medicines'})


# ------------------------------------------------------------- Activity log

def _with_actor_names(logs):
    """Attach a readable `actor_name` to each log row (actor_id has no FK)."""
    logs = list(logs)
    models = {'user': User, 'pharmacy': Pharmacy, 'admin': Admin}
    names = {}
    for actor_type, model in models.items():
        ids = {l.actor_id for l in logs if l.actor_type == actor_type}
        for obj in model.objects.filter(pk__in=ids):
            label = obj.business_name if actor_type == 'pharmacy' else obj.email
            names[(actor_type, obj.pk)] = label
    for log in logs:
        log.actor_name = names.get((log.actor_type, log.actor_id), f'#{log.actor_id} (deleted)')
    return logs


@role_required('admin')
def activity_view(request):
    actor_type = request.GET.get('actor', '')
    logs = ActivityLog.objects.all()
    if actor_type in ('user', 'pharmacy', 'admin'):
        logs = logs.filter(actor_type=actor_type)
    return render(request, 'admin_app/activity.html', {
        'logs': _with_actor_names(logs[:200]),
        'actor_type': actor_type,
    })
