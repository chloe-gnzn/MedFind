from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from login_app.utils import log_activity
from medfind_project.session_auth import role_required
from pharmacy_app.models import Inventory, OperatingHours, Pharmacy
from pharmacy_app.utils import open_now_map

from .models import Favorite, Medicine, MedicineCategory, SearchHistory

VISIBLE_PHARMACY = {'pharmacy__verification_status': 'approved', 'pharmacy__is_active': True}


def _short_time(t):
    """time(8, 0) -> '8AM', time(20, 30) -> '8:30PM' (matches the Figma card)."""
    hour = t.hour % 12 or 12
    suffix = 'AM' if t.hour < 12 else 'PM'
    return f'{hour}{suffix}' if t.minute == 0 else f'{hour}:{t.minute:02d}{suffix}'


# Demo cards shown only while there are no approved pharmacies in the database.
# They disappear automatically once real pharmacies exist.
PLACEHOLDER_PHARMACIES = [
    {'business_name': 'Rosepharmacy', 'address': 'Circo Centrum Building, Fuente Osmena Circle, Cebu City',
     'open_now': True, 'hours_text': '8AM - 10PM'},
    {'business_name': 'Mercury Drug', 'address': 'Osmena Boulevard, Capitol Site, Cebu City',
     'open_now': True, 'hours_text': '24 hours'},
    {'business_name': 'Watsons Pharmacy', 'address': 'Ayala Center Cebu, Cebu Business Park, Cebu City',
     'open_now': False, 'hours_text': '10AM - 9PM'},
    {'business_name': 'Generika Drugstore', 'address': 'Jones Avenue, Cebu City',
     'open_now': True, 'hours_text': '7AM - 9PM'},
    {'business_name': 'South Star Drug', 'address': 'Colon Street, Cebu City',
     'open_now': None, 'hours_text': ''},
    {'business_name': 'Rose Pharmacy IT Park', 'address': 'Lahug, Cebu IT Park, Cebu City',
     'open_now': True, 'hours_text': '8AM - 10PM'},
]


@role_required('user')
def home_view(request):
    pharmacies = list(Pharmacy.objects.filter(verification_status='approved', is_active=True))
    ids = [p.pk for p in pharmacies]

    open_map = open_now_map(ids)
    today = {h.pharmacy_id: h for h in OperatingHours.objects.filter(
        pharmacy_id__in=ids, days_of_week=timezone.localtime().weekday())}

    for p in pharmacies:
        p.open_now = open_map[p.pk]            # True / False / None (hours not set)
        h = today.get(p.pk)
        if h and not h.is_closed and h.opening_time and h.closing_time:
            p.hours_text = f'{_short_time(h.opening_time)} - {_short_time(h.closing_time)}'
        else:
            p.hours_text = ''

    use_placeholders = not pharmacies
    if use_placeholders:
        pharmacies = PLACEHOLDER_PHARMACIES

    return render(request, 'home_template/home.html', {
        'pharmacies': pharmacies,
        'use_placeholders': use_placeholders,
    })


@role_required('user')
def search_view(request):
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()

    in_stock_here = Q(
        inventory_items__pharmacy__verification_status='approved',
        inventory_items__pharmacy__is_active=True,
        inventory_items__availability_status__in=['available', 'low_stock'],
    )
    medicines = (Medicine.objects.select_related('category')
                 .annotate(pharmacy_count=Count('inventory_items', filter=in_stock_here, distinct=True)))
    if q:
        medicines = medicines.filter(Q(medicine_name__icontains=q) | Q(generic_name__icontains=q))
    if category_id.isdigit():
        medicines = medicines.filter(category_id=int(category_id))
    medicines = medicines.order_by('medicine_name')

    pharmacies = Pharmacy.objects.none()
    if q:
        pharmacies = Pharmacy.objects.filter(
            Q(business_name__icontains=q) | Q(address__icontains=q),
            verification_status='approved', is_active=True,
        )
        # remember what the user searched for (skip an immediate repeat)
        last = SearchHistory.objects.filter(user=request.account).first()
        if last is None or last.search_term.lower() != q.lower():
            SearchHistory.objects.create(user=request.account, search_term=q[:255])

    return render(request, 'home_template/search.html', {
        'q': q,
        'category_id': category_id,
        'categories': MedicineCategory.objects.all(),
        'medicines': medicines,
        'pharmacies': pharmacies,
    })


@role_required('user')
def medicine_detail_view(request, medicine_id):
    medicine = get_object_or_404(Medicine.objects.select_related('category'), pk=medicine_id)
    listings = list(
        Inventory.objects.filter(medicine=medicine, **VISIBLE_PHARMACY)
        .select_related('pharmacy').order_by('price')
    )
    open_map = open_now_map([l.pharmacy_id for l in listings])
    for listing in listings:
        listing.open_now = open_map[listing.pharmacy_id]

    return render(request, 'home_template/medicine_detail.html', {
        'medicine': medicine,
        'listings': listings,
        'is_favorite': Favorite.objects.filter(
            user=request.account, medicine=medicine, favorite_type='medicine').exists(),
    })


@role_required('user')
def pharmacy_detail_view(request, pharmacy_id):
    pharmacy = get_object_or_404(
        Pharmacy, pk=pharmacy_id, verification_status='approved', is_active=True)
    hours = {h.days_of_week: h for h in OperatingHours.objects.filter(pharmacy=pharmacy)}
    hour_rows = [{'label': label, 'hours': hours.get(day)} for day, label in OperatingHours.DAY_CHOICES]
    items = (Inventory.objects.filter(pharmacy=pharmacy)
             .select_related('medicine').order_by('medicine__medicine_name'))

    return render(request, 'home_template/pharmacy_detail.html', {
        'pharmacy': pharmacy,
        'hour_rows': hour_rows,
        'items': items,
        'open_now': open_now_map([pharmacy.pk])[pharmacy.pk],
        'is_favorite': Favorite.objects.filter(
            user=request.account, pharmacy=pharmacy, favorite_type='pharmacy').exists(),
    })


@role_required('user')
def favorites_view(request):
    favorites = Favorite.objects.filter(user=request.account).select_related(
        'medicine', 'medicine__category', 'pharmacy')
    return render(request, 'home_template/favorites.html', {
        'medicine_favs': [f for f in favorites if f.favorite_type == 'medicine' and f.medicine],
        'pharmacy_favs': [f for f in favorites if f.favorite_type == 'pharmacy' and f.pharmacy],
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
        messages.info(request, f'Removed {label} from your favorites.')
    else:
        Favorite.objects.create(user=request.account, favorite_type=kind, **lookup)
        log_activity('user', request.account.pk, 'favorite_add', f'Favorited {kind}: {label}.')
        messages.success(request, f'Added {label} to your favorites.')

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
def clear_history_view(request):
    SearchHistory.objects.filter(user=request.account).delete()
    messages.info(request, 'Search history cleared.')
    return redirect('history')
