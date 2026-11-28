from datetime import time

from django.utils import timezone

from .models import OperatingHours


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

        # Check if still within yesterday's overnight shift (e.g., 18:00 -> 02:00)
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
            # Overnight shift starting today (e.g., 18:00 -> 02:00)
            result[pid] = now_t >= today_row.opening_time

    return result
