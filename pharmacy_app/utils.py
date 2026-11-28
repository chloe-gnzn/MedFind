from datetime import time

from django.db import transaction
from django.utils import timezone

from admin_app.models import ActivityLog

from .models import Inventory, OperatingHours, Reservation


def is_24_hours(opening_time, closing_time):
    """Return True when opening/closing times represent a 24-hour schedule."""
    if not opening_time or not closing_time:
        return False
    return opening_time == time(0, 0) and closing_time in (time(0, 0), time(23, 59))


def _short_time(t):
    """time(8, 0) -> '8AM', time(20, 30) -> '8:30PM'."""
    hour = t.hour % 12 or 12
    suffix = 'AM' if t.hour < 12 else 'PM'
    return f'{hour}{suffix}' if t.minute == 0 else f'{hour}:{t.minute:02d}{suffix}'


def format_hours_span(opening_time, closing_time):
    """Return a concise human-readable hours span for today's schedule."""
    if not opening_time or not closing_time:
        return ''
    if is_24_hours(opening_time, closing_time):
        return '24 hours'
    return f'{_short_time(opening_time)} - {_short_time(closing_time)}'


def open_now_map(pharmacy_ids):
    """
    {pharmacy_id: True/False/None} -- True = open right now, False = closed,
    None = the pharmacy hasn't set hours for today (or yesterday's overnight shift).
    """
    ids = list(pharmacy_ids)
    now = timezone.localtime()
    now_t = now.time()
    today_day = now.weekday()
    yesterday_day = (today_day - 1) % 7

    result = {pid: None for pid in ids}
    rows = OperatingHours.objects.filter(
        pharmacy_id__in=ids,
        days_of_week__in=[today_day, yesterday_day],
    )
    by_day = {(r.pharmacy_id, r.days_of_week): r for r in rows}

    for pid in ids:
        today_row = by_day.get((pid, today_day))
        yest_row = by_day.get((pid, yesterday_day))

        if (
            yest_row and not yest_row.is_closed
            and yest_row.opening_time and yest_row.closing_time
            and yest_row.opening_time > yest_row.closing_time
            and now_t <= yest_row.closing_time
        ):
            result[pid] = True
            continue

        if today_row is None:
            continue
        if today_row.is_closed or not today_row.opening_time or not today_row.closing_time:
            result[pid] = False
        elif is_24_hours(today_row.opening_time, today_row.closing_time):
            result[pid] = True
        elif today_row.opening_time < today_row.closing_time:
            result[pid] = today_row.opening_time <= now_t <= today_row.closing_time
        else:
            result[pid] = now_t >= today_row.opening_time

    return result


def _sync_inventory_status(item):
    """Keep availability_status aligned with stock_quantity after reserve/restore."""
    if item.stock_quantity <= 0:
        item.stock_quantity = 0
        item.availability_status = Inventory.STATUS_OUT
    elif item.stock_quantity < 10:
        item.availability_status = Inventory.STATUS_LOW
    else:
        item.availability_status = Inventory.STATUS_AVAILABLE


def _restore_inventory_stock(reservation):
    """Return reserved quantity back to the Inventory row if it still exists."""
    if not reservation.inventory_id:
        return
    item = Inventory.objects.select_for_update().filter(pk=reservation.inventory_id).first()
    if item is None:
        return
    item.stock_quantity += reservation.quantity
    _sync_inventory_status(item)
    item.save(update_fields=['stock_quantity', 'availability_status', 'updated_at'])


def expire_stale_reservations(pharmacy=None, user=None):
    """
    Move any pending reservations past their 24-hour window into `unclaimed`
    and return their reserved stock to Inventory.
    """
    now = timezone.now()
    qs = Reservation.objects.filter(status=Reservation.STATUS_PENDING, expires_at__lte=now)
    if pharmacy is not None:
        qs = qs.filter(pharmacy=pharmacy)
    if user is not None:
        qs = qs.filter(user=user)

    stale_ids = list(qs.values_list('reservation_id', flat=True))
    if not stale_ids:
        return 0

    expired_count = 0
    with transaction.atomic():
        for res in Reservation.objects.select_for_update().filter(pk__in=stale_ids):
            if res.status != Reservation.STATUS_PENDING or res.expires_at > now:
                continue
            res.status = Reservation.STATUS_UNCLAIMED
            res.resolved_at = now
            res.is_auto_expired = True
            res.save(update_fields=['status', 'resolved_at', 'is_auto_expired'])
            _restore_inventory_stock(res)
            ActivityLog.objects.create(
                actor_type=ActivityLog.ACTOR_PHARMACY,
                actor_id=res.pharmacy_id,
                action='reservation_expired',
                description=f'Reservation {res.reservation_code} expired after 24 hours and moved to unclaimed.',
            )
            expired_count += 1
    return expired_count


def create_reservation(user, inventory_id, quantity):
    """Atomically deduct stock and create a 24-hour reservation with RS#### code."""
    if quantity < 1:
        raise ValueError('Quantity must be at least 1.')

    expire_stale_reservations()

    with transaction.atomic():
        item = (
            Inventory.objects.select_for_update()
            .select_related('pharmacy', 'medicine')
            .filter(
                pk=inventory_id,
                pharmacy__verification_status='approved',
                pharmacy__is_active=True,
            )
            .first()
        )
        if item is None:
            raise ValueError('This medicine listing is not available for reservation.')
        if item.availability_status == Inventory.STATUS_OUT or item.stock_quantity <= 0:
            raise ValueError('This medicine is currently out of stock.')
        if quantity > item.stock_quantity:
            raise ValueError(f'Only {item.stock_quantity} in stock — please enter {item.stock_quantity} or fewer.')

        item.stock_quantity -= quantity
        _sync_inventory_status(item)
        item.save(update_fields=['stock_quantity', 'availability_status', 'updated_at'])

        reservation = Reservation.objects.create(
            user=user,
            pharmacy=item.pharmacy,
            medicine=item.medicine,
            inventory=item,
            quantity=quantity,
            unit_price=item.price,
        )
        return reservation


def resolve_reservation(pharmacy, reservation_id, decision):
    """Mark a pending reservation as 'claimed' or 'unclaimed' (restoring stock if unclaimed)."""
    if decision not in (Reservation.STATUS_CLAIMED, Reservation.STATUS_UNCLAIMED):
        raise ValueError('Invalid reservation action.')

    now = timezone.now()
    with transaction.atomic():
        res = (
            Reservation.objects.select_for_update()
            .filter(pk=reservation_id, pharmacy=pharmacy)
            .first()
        )
        if res is None:
            raise ValueError('Reservation not found.')
        if res.status != Reservation.STATUS_PENDING:
            raise ValueError(f'Reservation {res.reservation_code} is already {res.get_status_display().lower()}.')

        if res.expires_at <= now:
            res.status = Reservation.STATUS_UNCLAIMED
            res.resolved_at = now
            res.is_auto_expired = True
            res.save(update_fields=['status', 'resolved_at', 'is_auto_expired'])
            _restore_inventory_stock(res)
            if decision == Reservation.STATUS_CLAIMED:
                raise ValueError(
                    f'Reservation {res.reservation_code} already expired after 24 hours and moved to Unclaimed.'
                )
            return res

        res.status = decision
        res.resolved_at = now
        res.is_auto_expired = False
        res.save(update_fields=['status', 'resolved_at', 'is_auto_expired'])
        if decision == Reservation.STATUS_UNCLAIMED:
            _restore_inventory_stock(res)
        return res
