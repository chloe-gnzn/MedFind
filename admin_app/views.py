import re
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Min, ProtectedError, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from home_app.models import Medicine, MedicineCategory, User
from login_app.utils import log_activity
from medfind_project.session_auth import role_required
from pharmacy_app.models import Inventory, Pharmacy, PharmacyVerification

from .forms import CategoryForm, MedicineForm
from .models import ActivityLog, Admin


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


# ------------------------------------------------------------ Verifications

@role_required('admin')
def verifications_view(request):
    status = request.GET.get('status', 'pending')
    rows = PharmacyVerification.objects.select_related('pharmacy', 'reviewed_by')
    if status in ('pending', 'approved', 'rejected'):
        rows = rows.filter(status=status)
    else:
        status = 'all'
    return render(request, 'admin_template/verifications.html', {'rows': rows, 'status': status})


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

    return render(request, 'admin_template/verification_review.html', {'v': verification})


# ---------------------------------------------------------- Pharmacies/users

@role_required('admin')
def pharmacies_view(request):
    return render(request, 'admin_template/pharmacies.html', {'pharmacies': Pharmacy.objects.all()})


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
    return render(request, 'admin_template/users.html', {'users': User.objects.all()})


# --------------------------------------------------------------- Categories

@role_required('admin')
def categories_view(request):
    categories = MedicineCategory.objects.annotate(med_count=Count('medicines'))
    return render(request, 'admin_template/categories.html', {'categories': categories})


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


# ---------------------------------------------------------------- Medicines

@role_required('admin')
def medicines_view(request):
    return render(request, 'admin_template/medicines.html', {
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



# ------------------------------------------------- Inventory monitoring (JOIN)

@role_required('admin')
def inventory_monitor_view(request):
    """
    Admin > Inventory monitoring            ->  /manage/inventory/

    SQL JOIN  (Inventory  x  Pharmacy  x  Medicine  x  Medicine_Category)
    -------------------------------------------------------------------
    Every row of the Inventory table only stores two numbers (pharmacy_id and
    medicine_id).  To show "WHO sells WHAT, in which category" the admin needs
    columns from the other three tables as well, so we JOIN them:

        pharmacy_app_inventory.pharmacy_id  = pharmacy_app_pharmacy.pharmacy_id
        pharmacy_app_inventory.medicine_id  = home_app_medicine.medicine_id
        home_app_medicine.category_id       = home_app_medicinecategory.category_id

    In Django ORM, select_related() is what turns those foreign keys into
    INNER JOINs, so everything arrives in ONE query (no N+1 queries).
    """
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    pharmacy_id = request.GET.get('pharmacy', '')
    category_id = request.GET.get('category', '')

    # ---- the JOIN -------------------------------------------------------
    rows = (Inventory.objects
            .select_related('pharmacy', 'medicine', 'medicine__category')
            .only('price', 'availability_status', 'stock_quantity', 'updated_at',      # only the columns the page shows
                  'pharmacy__business_name', 'pharmacy__address',
                  'medicine__medicine_name', 'medicine__generic_name',
                  'medicine__strength', 'medicine__form',
                  'medicine__category__category_name')
            .order_by('pharmacy__business_name', 'medicine__medicine_name'))
    # ---------------------------------------------------------------------

    if q:
        rows = rows.filter(
            Q(medicine__medicine_name__icontains=q)
            | Q(medicine__generic_name__icontains=q)
            | Q(pharmacy__business_name__icontains=q))
    if pharmacy_id.isdigit():
        rows = rows.filter(pharmacy_id=int(pharmacy_id))
    if category_id.isdigit():
        rows = rows.filter(medicine__category_id=int(category_id))

    # status counts for the chips / stat tiles (respect every filter except status)
    counts = {r['availability_status']: r['n'] for r in
              rows.order_by().values('availability_status').annotate(n=Count('inventory_id'))}
    total = sum(counts.values())
    pharmacies_reporting = rows.order_by().values('pharmacy_id').distinct().count()

    if status in dict(Inventory.AVAILABILITY_CHOICES):
        rows = rows.filter(availability_status=status)
    else:
        status = ''

    page = Paginator(rows, 25).get_page(request.GET.get('page'))

    # keep the filters in the pagination links
    keep = request.GET.copy()
    keep.pop('page', None)
    # same, but without 'status' too: used by the availability chips so they keep the other filters
    no_status = keep.copy()
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
        'querystring': keep.urlencode(),
        'filter_qs': no_status.urlencode(),
        'sql': _pretty_sql(rows),              # shown in the "Generated SQL" box
    })


# ---------------------------------------------------- Stock report (SUBQUERY)

def _available_medicine_ids():
    """
    INNER QUERY of the subquery.

    "Which medicine_ids can a customer actually get right now?"  ->  rows of
    Inventory that are Available / Low stock AND belong to an approved, active
    pharmacy (only those pharmacies are visible to users).

        SELECT U0.medicine_id
        FROM pharmacy_app_inventory U0
        INNER JOIN pharmacy_app_pharmacy U1 ON U0.pharmacy_id = U1.pharmacy_id
        WHERE U0.availability_status IN ('available', 'low_stock')
          AND U1.verification_status = 'approved' AND U1.is_active
    """
    return (Inventory.objects
            .filter(availability_status__in=[Inventory.STATUS_AVAILABLE, Inventory.STATUS_LOW],
                    pharmacy__verification_status=Pharmacy.VERIFICATION_APPROVED,
                    pharmacy__is_active=True)
            .values('medicine_id'))


def _unavailable_medicines():
    """OUTER QUERY: catalog medicines that are NOT IN the inner query's result."""
    return Medicine.objects.exclude(medicine_id__in=Subquery(_available_medicine_ids()))


@role_required('admin')
def stock_report_view(request):
    """
    Admin > Reports (stock gaps)            ->  /manage/reports/

    SQL SUBQUERY
    ------------
    Question the admin needs answered: "Which medicines in our catalog can
    nobody buy right now?"  (users searching for them find nothing)

    The answer needs TWO queries, one inside the other:

      inner query : medicine_ids that ARE in stock at an approved pharmacy
      outer query : Medicine rows whose medicine_id is NOT IN that list

        SELECT * FROM home_app_medicine
        WHERE medicine_id NOT IN (SELECT medicine_id FROM <inner query>);

    Toggling to "Available somewhere" flips NOT IN to IN with the SAME inner query.
    """
    view = 'in' if request.GET.get('view') == 'in' else 'out'
    available_ids = _available_medicine_ids()                       # INNER query

    base = (Medicine.objects.select_related('category')
            .only('medicine_name', 'generic_name', 'form', 'strength', 'category__category_name'))
    if view == 'in':
        medicines = base.filter(medicine_id__in=Subquery(available_ids))     # OUTER query (IN)
    else:
        medicines = base.exclude(medicine_id__in=Subquery(available_ids))    # OUTER query (NOT IN)

    page = Paginator(medicines, 25).get_page(request.GET.get('page'))
    ids = [m.medicine_id for m in page.object_list]

    # extra facts for the rows on this page (separate, small queries)
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

    keep = request.GET.copy()
    keep.pop('page', None)

    return render(request, 'admin_template/reports.html', {
        'view': view,
        'page': page,
        'total': total,
        'no_stock': no_stock,
        'in_stock': total - no_stock,
        'querystring': keep.urlencode(),
        'sql': _pretty_sql(medicines),
    })


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
    return render(request, 'admin_template/activity.html', {
        'logs': _with_actor_names(logs[:200]),
        'actor_type': actor_type,
    })
