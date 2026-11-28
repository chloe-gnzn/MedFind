import re
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Min, ProtectedError, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from home_app.models import Medicine, MedicineCategory, User
from login_app.forms import AccountPasswordChangeForm
from login_app.utils import log_activity
from medfind_project.session_auth import role_required
from pharmacy_app.models import Inventory, OperatingHours, Pharmacy, PharmacyVerification
from pharmacy_app.utils import open_now_map

from .forms import AdminCreateForm, AdminProfileForm, CategoryForm, MedicineForm
from .models import ActivityLog, Admin

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')


def super_admin_required(view):
    """Restrict an already @role_required('admin') view to super_admin accounts."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.account.role != Admin.ROLE_SUPER_ADMIN:
            messages.error(request, 'Only Super Admins can manage admin accounts.')
            return redirect('admin_dashboard')
        return view(request, *args, **kwargs)
    return wrapper


def _paginate(request, queryset, per_page=25):
    """Paginate `queryset` and return `(page, querystring_without_page)`."""
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    keep = request.GET.copy()
    keep.pop('page', None)
    return page, keep.urlencode()


def _pretty_sql(queryset):
    """
    The SQL Django will run for `queryset`, formatted for display: values are
    quoted ('approved', TRUE, ...) and each clause starts on its own line.
    (Display only - the real query still uses safe parameters.)
    """
    sql, params = queryset.query.sql_with_params()
    sql = re.sub(r' (FROM|WHERE|ORDER BY|GROUP BY|INNER JOIN|LEFT OUTER JOIN) ', r'\n\1 ', sql)

    def literal(value):
        if isinstance(value, bool):
            return 'TRUE' if value else 'FALSE'
        if value is None:
            return 'NULL'
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    return sql % tuple(literal(v) for v in params)


@role_required('admin')
def dashboard_view(request):
    return render(request, 'admin_template/dashboard.html', {
        'user_count': User.objects.count(),
        'pharmacy_count': Pharmacy.objects.count(),
        'pending_count': PharmacyVerification.objects.filter(status='pending').count(),
        'medicine_count': Medicine.objects.count(),
        'category_count': MedicineCategory.objects.count(),
        'inventory_count': Inventory.objects.count(),
        'no_stock_count': _unavailable_medicines().count(),
        'recent_logs': _with_actor_names(ActivityLog.objects.all()[:8]),
    })


@role_required('admin')
def profile_view(request):
    admin = request.account
    profile_form = AdminProfileForm(instance=admin)
    password_form = AccountPasswordChangeForm(account=admin)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            profile_form = AdminProfileForm(request.POST, instance=admin)
            if profile_form.is_valid():
                saved = profile_form.save()
                log_activity('admin', saved.pk, 'profile_update', f'Updated admin profile for {saved.email}.')
                messages.success(request, 'Admin profile updated.')
                return redirect('admin_profile')
        elif action == 'change_password':
            password_form = AccountPasswordChangeForm(request.POST, account=admin)
            if password_form.is_valid():
                saved = password_form.save()
                log_activity('admin', saved.pk, 'password_change', f'Admin {saved.email} changed password.')
                messages.success(request, 'Your password has been changed.')
                return redirect('admin_profile')

    return render(request, 'admin_template/profile.html', {
        'admin': admin,
        'profile_form': profile_form,
        'password_form': password_form,
        'reviewed_count': admin.reviewed_verifications.count(),
    })


@role_required('admin')
@super_admin_required
def admins_view(request):
    q = request.GET.get('q', '').strip()
    admins = Admin.objects.annotate(reviewed_count=Count('reviewed_verifications')).order_by('email')
    if q:
        admins = admins.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
        )
    page, querystring = _paginate(request, admins, per_page=25)
    return render(request, 'admin_template/admins.html', {
        'page': page,
        'q': q,
        'querystring': querystring,
    })


@role_required('admin')
@super_admin_required
def admin_add_view(request):
    form = AdminCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        created = form.save()
        log_activity('admin', request.account.pk, 'admin_create',
                     f'Created {created.role} account {created.email}.')
        messages.success(request, f'Created admin account for {created.email}.')
        return redirect('admin_admins')
    return render(request, 'admin_template/form.html', {
        'form': form,
        'title': 'Add admin account',
        'back_url': 'admin_admins',
    })


@role_required('admin')
@super_admin_required
@require_POST
def admin_toggle_role_view(request, admin_id):
    target = get_object_or_404(Admin, pk=admin_id)
    if target.pk == request.account.pk:
        messages.error(request, 'You cannot change your own admin role.')
        return redirect('admin_admins')
    target.role = (
        Admin.ROLE_ADMIN if target.role == Admin.ROLE_SUPER_ADMIN else Admin.ROLE_SUPER_ADMIN
    )
    target.save(update_fields=['role'])
    log_activity('admin', request.account.pk, 'admin_role_change',
                 f'Changed {target.email} role to {target.role}.')
    messages.success(request, f'{target.email} is now {target.get_role_display()}.')
    return redirect('admin_admins')


@role_required('admin')
@super_admin_required
@require_POST
def admin_delete_view(request, admin_id):
    target = get_object_or_404(Admin, pk=admin_id)
    if target.pk == request.account.pk:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('admin_admins')
    email = target.email
    target.delete()
    log_activity('admin', request.account.pk, 'admin_delete', f'Deleted admin account {email}.')
    messages.info(request, f'Deleted admin account {email}.')
    return redirect('admin_admins')


@role_required('admin')
def verifications_view(request):
    status = request.GET.get('status', 'pending')
    q = request.GET.get('q', '').strip()

    rows = PharmacyVerification.objects.select_related('pharmacy', 'reviewed_by')
    if q:
        rows = rows.filter(
            Q(pharmacy__business_name__icontains=q) | Q(pharmacy__email__icontains=q)
        )

    counts = {
        r['status']: r['n']
        for r in rows.order_by().values('status').annotate(n=Count('verification_id'))
    }
    counts['all'] = sum(counts.values())

    if status in ('pending', 'approved', 'rejected'):
        rows = rows.filter(status=status)
    else:
        status = 'all'

    page, querystring = _paginate(request, rows, per_page=25)
    no_status = request.GET.copy()
    no_status.pop('page', None)
    no_status.pop('status', None)

    return render(request, 'admin_template/verifications.html', {
        'page': page,
        'status': status,
        'q': q,
        'counts': counts,
        'querystring': querystring,
        'filter_qs': no_status.urlencode(),
    })


@role_required('admin')
def verification_review_view(request, verification_id):
    verification = get_object_or_404(
        PharmacyVerification.objects.select_related('pharmacy', 'reviewed_by'),
        pk=verification_id,
    )
    verification.is_image = verification.document_path.lower().endswith(IMAGE_EXTENSIONS)

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

    return render(request, 'admin_template/verification_review.html', {'v': verification})


@role_required('admin')
def pharmacies_view(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    active = request.GET.get('active', '').strip()

    pharmacies = Pharmacy.objects.annotate(
        item_count=Count('inventory_items', distinct=True),
        favorite_count=Count('favorites', distinct=True),
    ).order_by('business_name')
    if q:
        pharmacies = pharmacies.filter(
            Q(business_name__icontains=q) | Q(email__icontains=q) | Q(address__icontains=q)
        )
    if status in (
        Pharmacy.VERIFICATION_PENDING,
        Pharmacy.VERIFICATION_APPROVED,
        Pharmacy.VERIFICATION_REJECTED,
    ):
        pharmacies = pharmacies.filter(verification_status=status)
    else:
        status = ''

    if active == 'active':
        pharmacies = pharmacies.filter(is_active=True)
    elif active == 'inactive':
        pharmacies = pharmacies.filter(is_active=False)
    else:
        active = ''

    page, querystring = _paginate(request, pharmacies, per_page=25)
    return render(request, 'admin_template/pharmacies.html', {
        'page': page,
        'q': q,
        'status': status,
        'active': active,
        'querystring': querystring,
    })


@role_required('admin')
def pharmacy_detail_view(request, pharmacy_id):
    pharmacy = get_object_or_404(Pharmacy, pk=pharmacy_id)
    hours = {h.days_of_week: h for h in OperatingHours.objects.filter(pharmacy=pharmacy)}
    hour_rows = [{'label': label, 'hours': hours.get(day)} for day, label in OperatingHours.DAY_CHOICES]
    items = (
        Inventory.objects.filter(pharmacy=pharmacy)
        .select_related('medicine', 'medicine__category')
        .order_by('medicine__medicine_name')
    )
    verifications = pharmacy.verifications.select_related('reviewed_by')
    return render(request, 'admin_template/pharmacy_detail.html', {
        'pharmacy': pharmacy,
        'hour_rows': hour_rows,
        'items': items,
        'verifications': verifications,
        'favorite_count': pharmacy.favorites.count(),
        'open_now': open_now_map([pharmacy.pk])[pharmacy.pk],
    })


@role_required('admin')
@require_POST
def pharmacy_toggle_view(request, pharmacy_id):
    pharmacy = get_object_or_404(Pharmacy, pk=pharmacy_id)
    pharmacy.is_active = not pharmacy.is_active
    pharmacy.save(update_fields=['is_active', 'updated_at'])
    state = 'activated' if pharmacy.is_active else 'deactivated'
    log_activity('admin', request.account.pk, f'pharmacy_{state}', f'{state.title()} {pharmacy.business_name}.')
    messages.success(request, f'{pharmacy.business_name} {state}.')

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('admin_pharmacies')


@role_required('admin')
def users_view(request):
    q = request.GET.get('q', '').strip()
    users = User.objects.annotate(
        favorite_count=Count('favorites', distinct=True),
        search_count=Count('search_history', distinct=True),
    ).order_by('-created_at')
    if q:
        users = users.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone_number__icontains=q)
        )
    page, querystring = _paginate(request, users, per_page=25)
    return render(request, 'admin_template/users.html', {
        'page': page,
        'q': q,
        'querystring': querystring,
    })


@role_required('admin')
def categories_view(request):
    q = request.GET.get('q', '').strip()
    categories = MedicineCategory.objects.annotate(med_count=Count('medicines')).order_by('category_name')
    if q:
        categories = categories.filter(Q(category_name__icontains=q) | Q(description__icontains=q))
    page, querystring = _paginate(request, categories, per_page=25)
    return render(request, 'admin_template/categories.html', {
        'page': page,
        'q': q,
        'querystring': querystring,
    })


@role_required('admin')
def category_form_view(request, category_id=None):
    category = get_object_or_404(MedicineCategory, pk=category_id) if category_id else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        log_activity('admin', request.account.pk, 'category_save', f'Saved category {saved.category_name}.')
        messages.success(request, 'Category saved.')
        return redirect('admin_categories')
    return render(request, 'admin_template/form.html', {
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
    return render(request, 'admin_template/confirm_delete.html', {
        'what': f'category "{category.category_name}"', 'back_url': 'admin_categories'})


@role_required('admin')
def medicines_view(request):
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    medicines = Medicine.objects.select_related('category')
    if q:
        medicines = medicines.filter(
            Q(medicine_name__icontains=q)
            | Q(generic_name__icontains=q)
            | Q(form__icontains=q)
            | Q(strength__icontains=q)
        )
    if category_id.isdigit():
        medicines = medicines.filter(category_id=int(category_id))

    page, querystring = _paginate(request, medicines, per_page=25)
    return render(request, 'admin_template/medicines.html', {
        'page': page,
        'q': q,
        'category_id': category_id,
        'categories': MedicineCategory.objects.all(),
        'querystring': querystring,
    })


@role_required('admin')
def medicine_form_view(request, medicine_id=None):
    medicine = get_object_or_404(Medicine, pk=medicine_id) if medicine_id else None
    form = MedicineForm(request.POST or None, instance=medicine)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        log_activity('admin', request.account.pk, 'medicine_save', f'Saved medicine {saved.medicine_name}.')
        messages.success(request, 'Medicine saved.')
        return redirect('admin_medicines')
    return render(request, 'admin_template/form.html', {
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
    return render(request, 'admin_template/confirm_delete.html', {
        'what': f'medicine "{medicine.medicine_name}" (this also removes it from every pharmacy inventory and favorites)',
        'back_url': 'admin_medicines'})


@role_required('admin')
def inventory_monitor_view(request):
    """
    Admin > Inventory monitoring            ->  /manage/inventory/

    SQL JOIN  (Inventory  x  Pharmacy  x  Medicine  x  Medicine_Category)
    """
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    pharmacy_id = request.GET.get('pharmacy', '')
    category_id = request.GET.get('category', '')

    rows = (Inventory.objects
            .select_related('pharmacy', 'medicine', 'medicine__category')
            .only('price', 'availability_status', 'stock_quantity', 'updated_at',
                  'pharmacy__business_name', 'pharmacy__address',
                  'medicine__medicine_name', 'medicine__generic_name',
                  'medicine__strength', 'medicine__form',
                  'medicine__category__category_name')
            .order_by('pharmacy__business_name', 'medicine__medicine_name'))

    if q:
        rows = rows.filter(
            Q(medicine__medicine_name__icontains=q)
            | Q(medicine__generic_name__icontains=q)
            | Q(pharmacy__business_name__icontains=q))
    if pharmacy_id.isdigit():
        rows = rows.filter(pharmacy_id=int(pharmacy_id))
    if category_id.isdigit():
        rows = rows.filter(medicine__category_id=int(category_id))

    counts = {r['availability_status']: r['n'] for r in
              rows.order_by().values('availability_status').annotate(n=Count('inventory_id'))}
    total = sum(counts.values())
    pharmacies_reporting = rows.order_by().values('pharmacy_id').distinct().count()

    if status in dict(Inventory.AVAILABILITY_CHOICES):
        rows = rows.filter(availability_status=status)
    else:
        status = ''

    page, querystring = _paginate(request, rows, per_page=25)

    no_status = request.GET.copy()
    no_status.pop('page', None)
    no_status.pop('status', None)

    return render(request, 'admin_template/inventory.html', {
        'page': page,
        'q': q,
        'status': status,
        'pharmacy_id': pharmacy_id,
        'category_id': category_id,
        'pharmacies': Pharmacy.objects.order_by('business_name'),
        'categories': MedicineCategory.objects.all(),
        'status_choices': Inventory.AVAILABILITY_CHOICES,
        'counts': counts,
        'total': total,
        'pharmacies_reporting': pharmacies_reporting,
        'querystring': querystring,
        'filter_qs': no_status.urlencode(),
        'sql': _pretty_sql(rows),
    })


def _available_medicine_ids():
    return (Inventory.objects
            .filter(availability_status__in=[Inventory.STATUS_AVAILABLE, Inventory.STATUS_LOW],
                    pharmacy__verification_status=Pharmacy.VERIFICATION_APPROVED,
                    pharmacy__is_active=True)
            .values('medicine_id'))


def _unavailable_medicines():
    return Medicine.objects.exclude(medicine_id__in=Subquery(_available_medicine_ids()))


@role_required('admin')
def stock_report_view(request):
    view = 'in' if request.GET.get('view') == 'in' else 'out'
    available_ids = _available_medicine_ids()

    base = (Medicine.objects.select_related('category')
            .only('medicine_name', 'generic_name', 'form', 'strength', 'category__category_name'))
    if view == 'in':
        medicines = base.filter(medicine_id__in=Subquery(available_ids))
    else:
        medicines = base.exclude(medicine_id__in=Subquery(available_ids))

    page, querystring = _paginate(request, medicines, per_page=25)
    ids = [m.medicine_id for m in page.object_list]

    listed = {r['medicine_id']: r['n'] for r in
              Inventory.objects.filter(medicine_id__in=ids)
              .values('medicine_id').annotate(n=Count('inventory_id'))}
    in_stock = {r['medicine_id']: r for r in
                available_ids.filter(medicine_id__in=ids)
                .values('medicine_id').annotate(n=Count('inventory_id'), cheapest=Min('price'))}
    for m in page.object_list:
        m.listed_count = listed.get(m.medicine_id, 0)
        m.stock_info = in_stock.get(m.medicine_id)

    total = Medicine.objects.count()
    no_stock = _unavailable_medicines().count()

    return render(request, 'admin_template/reports.html', {
        'view': view,
        'page': page,
        'total': total,
        'no_stock': no_stock,
        'in_stock': total - no_stock,
        'querystring': querystring,
        'sql': _pretty_sql(medicines),
    })


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
    actor_type = request.GET.get('actor', '').strip()
    q = request.GET.get('q', '').strip()

    logs = ActivityLog.objects.all()
    if actor_type in ('user', 'pharmacy', 'admin'):
        logs = logs.filter(actor_type=actor_type)
    else:
        actor_type = ''
    if q:
        logs = logs.filter(Q(action__icontains=q) | Q(description__icontains=q))

    page, querystring = _paginate(request, logs, per_page=30)
    page.object_list = _with_actor_names(page.object_list)

    no_actor = request.GET.copy()
    no_actor.pop('page', None)
    no_actor.pop('actor', None)

    return render(request, 'admin_template/activity.html', {
        'page': page,
        'logs': page.object_list,
        'actor_type': actor_type,
        'q': q,
        'querystring': querystring,
        'filter_qs': no_actor.urlencode(),
    })
