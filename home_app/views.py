from django.contrib import messages
from django.db.models import Count, F, Max, Min, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from login_app.utils import log_activity
from medfind_project.session_auth import SESSION_ROLE, get_account, role_required
from pharmacy_app.models import Inventory, OperatingHours, Pharmacy, Reservation
from pharmacy_app.utils import create_reservation, expire_stale_reservations, format_hours_span, open_now_map

from .forms import UserPasswordChangeForm, UserProfileForm
from .models import Favorite, Medicine, MedicineCategory, SearchHistory

VISIBLE_PHARMACY = {'pharmacy__verification_status': 'approved', 'pharmacy__is_active': True}
IN_STOCK_STATUSES = ['available', 'low_stock']


def _attach_pharmacy_hours(pharmacies):
    """Attach `open_now` (True/False/None) and today's `hours_text` to Pharmacy objects."""
    ids = [p.pk for p in pharmacies]
    if not ids:
        return pharmacies
    open_map = open_now_map(ids)
    today = {
        h.pharmacy_id: h
        for h in OperatingHours.objects.filter(
            pharmacy_id__in=ids,
            days_of_week=timezone.localtime().weekday(),
        )
    }
    for p in pharmacies:
        p.open_now = open_map[p.pk]
        h = today.get(p.pk)
        if h and not h.is_closed and h.opening_time and h.closing_time:
            p.hours_text = format_hours_span(h.opening_time, h.closing_time)
        else:
            p.hours_text = ''
    return pharmacies


def _user_favorite_ids(user):
    """Return (medicine_ids_set, pharmacy_ids_set) favorited by `user`."""
    med_ids = set(
        Favorite.objects.filter(user=user, favorite_type='medicine', medicine_id__isnull=False)
        .values_list('medicine_id', flat=True)
    )
    pharm_ids = set(
        Favorite.objects.filter(user=user, favorite_type='pharmacy', pharmacy_id__isnull=False)
        .values_list('pharmacy_id', flat=True)
    )
    return med_ids, pharm_ids


@role_required('user')
def home_view(request):
    open_only = request.GET.get('open') == '1'
    pharmacies = list(Pharmacy.objects.filter(verification_status='approved', is_active=True))
    _attach_pharmacy_hours(pharmacies)

    _, fav_pharmacy_ids = _user_favorite_ids(request.account)
    for p in pharmacies:
        p.is_favorite = p.pk in fav_pharmacy_ids

    if open_only:
        pharmacies = [p for p in pharmacies if p.open_now]

    return render(request, 'home_template/home.html', {
        'pharmacies': pharmacies,
        'open_only': open_only,
    })


def _portal_url_names(is_guest):
    if is_guest:
        return {
            'is_guest': True,
            'base_template': 'public_browse_base.html',
            'browse_url_name': 'public_browse',
            'med_detail_url_name': 'public_medicine_detail',
            'pharm_detail_url_name': 'public_pharmacy_detail',
        }
    return {
        'is_guest': False,
        'base_template': 'user_base.html',
        'browse_url_name': 'search',
        'med_detail_url_name': 'medicine_detail',
        'pharm_detail_url_name': 'pharmacy_detail',
    }


def _build_search_context(request, user=None):
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    med_form = request.GET.get('form', '').strip()
    in_stock_only = request.GET.get('in_stock') == '1'
    open_now_only = request.GET.get('open_now') == '1'
    sort = request.GET.get('sort', 'name').strip()

    all_active_pharmacies = list(
        Pharmacy.objects.filter(verification_status='approved', is_active=True)
    )
    _attach_pharmacy_hours(all_active_pharmacies)
    open_pharmacy_ids = [p.pk for p in all_active_pharmacies if p.open_now]

    in_stock_filter = Q(
        inventory_items__pharmacy__verification_status='approved',
        inventory_items__pharmacy__is_active=True,
        inventory_items__availability_status__in=IN_STOCK_STATUSES,
    )
    if open_now_only:
        in_stock_filter &= Q(inventory_items__pharmacy_id__in=open_pharmacy_ids)

    medicines = (
        Medicine.objects.select_related('category')
        .annotate(
            pharmacy_count=Count('inventory_items', filter=in_stock_filter, distinct=True),
            min_price=Min('inventory_items__price', filter=in_stock_filter),
            max_price=Max('inventory_items__price', filter=in_stock_filter),
        )
    )
    if q:
        medicines = medicines.filter(Q(medicine_name__icontains=q) | Q(generic_name__icontains=q))

    selected_category = None
    if category_id.isdigit():
        selected_category = MedicineCategory.objects.filter(pk=int(category_id)).first()
        medicines = medicines.filter(category_id=int(category_id))
    if med_form:
        medicines = medicines.filter(form__iexact=med_form)
    if in_stock_only or open_now_only:
        medicines = medicines.filter(pharmacy_count__gt=0)

    if sort == 'price_asc':
        medicines = medicines.order_by(F('min_price').asc(nulls_last=True), 'medicine_name')
    elif sort == 'price_desc':
        medicines = medicines.order_by(F('min_price').desc(nulls_last=True), 'medicine_name')
    elif sort == 'availability':
        medicines = medicines.order_by('-pharmacy_count', 'medicine_name')
    else:
        sort = 'name'
        medicines = medicines.order_by('medicine_name')

    pharmacies = all_active_pharmacies
    if q:
        q_lower = q.lower()
        pharmacies = [
            p for p in pharmacies
            if q_lower in p.business_name.lower() or q_lower in p.address.lower()
        ]
        if user is not None:
            last = SearchHistory.objects.filter(user=user).first()
            if last is None or last.search_term.lower() != q_lower:
                SearchHistory.objects.create(user=user, search_term=q[:255])

    if open_now_only:
        pharmacies = [p for p in pharmacies if p.open_now]

    if user is not None:
        fav_medicine_ids, fav_pharmacy_ids = _user_favorite_ids(user)
    else:
        fav_medicine_ids, fav_pharmacy_ids = set(), set()

    medicine_forms = (
        Medicine.objects.exclude(form='')
        .values_list('form', flat=True)
        .distinct()
        .order_by('form')
    )

    context = {
        'q': q,
        'category_id': category_id,
        'selected_category': selected_category,
        'med_form': med_form,
        'medicine_forms': medicine_forms,
        'in_stock_only': in_stock_only,
        'open_now_only': open_now_only,
        'sort': sort,
        'categories': MedicineCategory.objects.all(),
        'medicines': medicines,
        'pharmacies': pharmacies,
        'fav_medicine_ids': fav_medicine_ids,
        'fav_pharmacy_ids': fav_pharmacy_ids,
    }
    context.update(_portal_url_names(user is None))
    return context


@role_required('user')
def search_view(request):
    return render(request, 'home_template/search.html', _build_search_context(request, user=request.account))


def public_browse_view(request):
    """Allow non-logged-in visitors to browse medicines and verified pharmacies without favorites."""
    if get_account(request) and request.session.get(SESSION_ROLE) == 'user':
        qs = request.META.get('QUERY_STRING', '')
        target = '/home/search/' + (f'?{qs}' if qs else '')
        return redirect(target)
    return render(request, 'home_template/search.html', _build_search_context(request, user=None))


def _build_medicine_detail_context(request, medicine_id, user=None):
    expire_stale_reservations()
    medicine = get_object_or_404(Medicine.objects.select_related('category'), pk=medicine_id)
    in_stock_only = request.GET.get('in_stock') == '1'
    open_now_only = request.GET.get('open_now') == '1'
    sort = request.GET.get('sort', 'price').strip()

    listings = list(
        Inventory.objects.filter(medicine=medicine, **VISIBLE_PHARMACY)
        .select_related('pharmacy')
        .order_by('price')
    )
    open_map = open_now_map([l.pharmacy_id for l in listings])
    _, fav_pharmacy_ids = _user_favorite_ids(user) if user is not None else (set(), set())
    for listing in listings:
        listing.open_now = open_map[listing.pharmacy_id]
        listing.is_pharmacy_favorite = listing.pharmacy_id in fav_pharmacy_ids

    if in_stock_only:
        listings = [l for l in listings if l.availability_status in IN_STOCK_STATUSES]
    if open_now_only:
        listings = [l for l in listings if l.open_now]

    if sort == 'stock':
        listings.sort(key=lambda l: (-l.stock_quantity, l.price))
    elif sort == 'name':
        listings.sort(key=lambda l: l.pharmacy.business_name.lower())
    else:
        sort = 'price'
        listings.sort(key=lambda l: l.price)

    best_price = min(
        (l.price for l in listings if l.availability_status in IN_STOCK_STATUSES),
        default=None,
    )
    is_favorite = (
        Favorite.objects.filter(user=user, medicine=medicine, favorite_type='medicine').exists()
        if user is not None else False
    )

    context = {
        'medicine': medicine,
        'listings': listings,
        'best_price': best_price,
        'in_stock_only': in_stock_only,
        'open_now_only': open_now_only,
        'sort': sort,
        'is_favorite': is_favorite,
    }
    context.update(_portal_url_names(user is None))
    return context


@role_required('user')
def medicine_detail_view(request, medicine_id):
    return render(
        request,
        'home_template/medicine_detail.html',
        _build_medicine_detail_context(request, medicine_id, user=request.account),
    )


def public_medicine_detail_view(request, medicine_id):
    """Public medicine detail view for non-logged-in visitors (no favorites)."""
    if get_account(request) and request.session.get(SESSION_ROLE) == 'user':
        return redirect('medicine_detail', medicine_id=medicine_id)
    return render(
        request,
        'home_template/medicine_detail.html',
        _build_medicine_detail_context(request, medicine_id, user=None),
    )


def _build_pharmacy_detail_context(request, pharmacy_id, user=None):
    pharmacy = get_object_or_404(
        Pharmacy, pk=pharmacy_id, verification_status='approved', is_active=True)
    expire_stale_reservations(pharmacy=pharmacy)
    hours = {h.days_of_week: h for h in OperatingHours.objects.filter(pharmacy=pharmacy)}
    hour_rows = [{'label': label, 'hours': hours.get(day)} for day, label in OperatingHours.DAY_CHOICES]

    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    status = request.GET.get('status', '').strip()

    items = (
        Inventory.objects.filter(pharmacy=pharmacy)
        .select_related('medicine', 'medicine__category')
        .order_by('medicine__medicine_name')
    )
    if q:
        items = items.filter(
            Q(medicine__medicine_name__icontains=q) | Q(medicine__generic_name__icontains=q)
        )
    if category_id.isdigit():
        items = items.filter(medicine__category_id=int(category_id))
    if status == 'in_stock':
        items = items.filter(availability_status__in=IN_STOCK_STATUSES)
    elif status in ('available', 'low_stock', 'out_of_stock'):
        items = items.filter(availability_status=status)

    fav_medicine_ids, _ = _user_favorite_ids(user) if user is not None else (set(), set())
    categories = MedicineCategory.objects.filter(
        medicines__inventory_items__pharmacy=pharmacy
    ).distinct().order_by('category_name')
    is_favorite = (
        Favorite.objects.filter(user=user, pharmacy=pharmacy, favorite_type='pharmacy').exists()
        if user is not None else False
    )

    context = {
        'pharmacy': pharmacy,
        'hour_rows': hour_rows,
        'items': items,
        'q': q,
        'category_id': category_id,
        'status': status,
        'categories': categories,
        'fav_medicine_ids': fav_medicine_ids,
        'open_now': open_now_map([pharmacy.pk])[pharmacy.pk],
        'is_favorite': is_favorite,
    }
    context.update(_portal_url_names(user is None))
    return context


@role_required('user')
def pharmacy_detail_view(request, pharmacy_id):
    return render(
        request,
        'home_template/pharmacy_detail.html',
        _build_pharmacy_detail_context(request, pharmacy_id, user=request.account),
    )


def public_pharmacy_detail_view(request, pharmacy_id):
    """Public pharmacy detail view for non-logged-in visitors (no favorites)."""
    if get_account(request) and request.session.get(SESSION_ROLE) == 'user':
        return redirect('pharmacy_detail', pharmacy_id=pharmacy_id)
    return render(
        request,
        'home_template/pharmacy_detail.html',
        _build_pharmacy_detail_context(request, pharmacy_id, user=None),
    )


@role_required('user')
def favorites_view(request):
    favorites = list(
        Favorite.objects.filter(user=request.account).select_related(
            'medicine', 'medicine__category', 'pharmacy')
    )
    medicine_favs = [f for f in favorites if f.favorite_type == 'medicine' and f.medicine]
    pharmacy_favs = [f for f in favorites if f.favorite_type == 'pharmacy' and f.pharmacy]

    if medicine_favs:
        med_ids = [f.medicine_id for f in medicine_favs]
        in_stock_filter = Q(
            inventory_items__pharmacy__verification_status='approved',
            inventory_items__pharmacy__is_active=True,
            inventory_items__availability_status__in=IN_STOCK_STATUSES,
        )
        stats = {
            m.medicine_id: m
            for m in Medicine.objects.filter(pk__in=med_ids).annotate(
                pharmacy_count=Count('inventory_items', filter=in_stock_filter, distinct=True),
                min_price=Min('inventory_items__price', filter=in_stock_filter),
            )
        }
        for f in medicine_favs:
            s = stats.get(f.medicine_id)
            f.pharmacy_count = s.pharmacy_count if s else 0
            f.min_price = s.min_price if s else None

    if pharmacy_favs:
        _attach_pharmacy_hours([f.pharmacy for f in pharmacy_favs])

    return render(request, 'home_template/favorites.html', {
        'medicine_favs': medicine_favs,
        'pharmacy_favs': pharmacy_favs,
    })


@role_required('user')
@require_POST
def toggle_favorite_view(request, kind, obj_id):
    if kind == 'medicine':
        target = get_object_or_404(Medicine, pk=obj_id)
        lookup = {'medicine': target}
        label = target.medicine_name
    elif kind == 'pharmacy':
        target = get_object_or_404(Pharmacy, pk=obj_id, verification_status='approved', is_active=True)
        lookup = {'pharmacy': target}
        label = target.business_name
    else:
        raise Http404

    existing = Favorite.objects.filter(user=request.account, favorite_type=kind, **lookup).first()
    if existing:
        existing.delete()
        favorited = False
        msg = f'Removed {label} from your favorites.'
        level = messages.info
    else:
        Favorite.objects.create(user=request.account, favorite_type=kind, **lookup)
        log_activity('user', request.account.pk, 'favorite_add', f'Favorited {kind}: {label}.')
        favorited = True
        msg = f'Added {label} to your favorites.'
        level = messages.success

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'favorited': favorited,
            'message': msg,
            'kind': kind,
        })

    level(request, msg)
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('favorites')


@role_required('user')
def history_view(request):
    return render(request, 'home_template/history.html', {
        'searches': SearchHistory.objects.filter(user=request.account)[:50],
    })


@role_required('user')
@require_POST
def delete_history_item_view(request, search_id):
    item = get_object_or_404(SearchHistory, pk=search_id, user=request.account)
    item.delete()
    messages.info(request, f'Removed “{item.search_term}” from your search history.')
    return redirect('history')


@role_required('user')
@require_POST
def clear_history_view(request):
    SearchHistory.objects.filter(user=request.account).delete()
    messages.info(request, 'Search history cleared.')
    return redirect('history')


@role_required('user')
def profile_view(request):
    profile_form = UserProfileForm(instance=request.account)
    password_form = UserPasswordChangeForm(user=request.account)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            profile_form = UserProfileForm(request.POST, instance=request.account)
            if profile_form.is_valid():
                user = profile_form.save()
                log_activity('user', user.pk, 'profile_update', f'Updated profile for {user.email}.')
                messages.success(request, 'Your profile has been updated.')
                return redirect('user_profile')
        elif action == 'change_password':
            password_form = UserPasswordChangeForm(request.POST, user=request.account)
            if password_form.is_valid():
                user = password_form.save()
                log_activity('user', user.pk, 'password_change', f'User {user.email} changed password.')
                messages.success(request, 'Your password has been changed.')
                return redirect('user_profile')

    return render(request, 'home_template/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'favorite_count': Favorite.objects.filter(user=request.account).count(),
        'search_count': SearchHistory.objects.filter(user=request.account).count(),
    })


@role_required('user')
@require_POST
def reserve_medicine_view(request, inventory_id):
    raw_qty = (request.POST.get('quantity') or '').strip()
    next_url = request.POST.get('next', '')
    safe_next = (
        next_url if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})
        else ''
    )

    try:
        quantity = int(raw_qty)
    except ValueError:
        messages.error(request, 'Please enter a valid whole number quantity.')
        return redirect(safe_next or 'search')

    try:
        reservation = create_reservation(request.account, inventory_id, quantity)
    except ValueError as err:
        messages.error(request, str(err))
        return redirect(safe_next or 'search')

    log_activity(
        'user',
        request.account.pk,
        'reserve_create',
        f'Reserved {reservation.quantity}x {reservation.medicine.medicine_name} '
        f'at {reservation.pharmacy.business_name} ({reservation.reservation_code}).',
    )
    messages.success(
        request,
        f'Reserved {reservation.quantity}× {reservation.medicine.medicine_name}! '
        f'Code: {reservation.reservation_code} (valid for 24 hours).',
    )
    return redirect('user_reservations')


@role_required('user')
def reservations_view(request):
    expire_stale_reservations(user=request.account)
    folder = request.GET.get('folder', 'all').strip()

    all_rows = (
        Reservation.objects.filter(user=request.account)
        .select_related('pharmacy', 'medicine', 'medicine__category')
    )
    counts = {
        'all': all_rows.count(),
        'pending': all_rows.filter(status=Reservation.STATUS_PENDING).count(),
        'claimed': all_rows.filter(status=Reservation.STATUS_CLAIMED).count(),
        'unclaimed': all_rows.filter(status=Reservation.STATUS_UNCLAIMED).count(),
    }
    if folder in ('pending', 'claimed', 'unclaimed'):
        rows = all_rows.filter(status=folder)
    else:
        folder = 'all'
        rows = all_rows

    return render(request, 'home_template/reservations.html', {
        'reservations': rows,
        'folder': folder,
        'counts': counts,
    })
