"""Donation-cooldown rules. Small pure functions, easy to test with a fixed date."""
from datetime import timedelta

from django.utils import timezone

from core.constants import DONATION_COOLDOWN_DAYS


def _resolve_today(today):
    return today if today is not None else timezone.localdate()


def next_eligible_date(last_donation_date):
    """First date the donor may give again, or None if they never donated."""
    if last_donation_date is None:
        return None
    return last_donation_date + timedelta(days=DONATION_COOLDOWN_DAYS)


def is_eligible(last_donation_date, today=None):
    """Eligible if never donated, or today is on/after the next eligible date."""
    next_date = next_eligible_date(last_donation_date)
    return next_date is None or _resolve_today(today) >= next_date


def days_until_eligible(last_donation_date, today=None):
    """Days left in the cooldown (0 if already eligible)."""
    next_date = next_eligible_date(last_donation_date)
    if next_date is None:
        return 0
    return max((next_date - _resolve_today(today)).days, 0)


def eligibility_cutoff(today=None):
    """Latest last_donation_date that is still eligible today.
    Used by matching to filter in the database: last_donation_date <= cutoff."""
    return _resolve_today(today) - timedelta(days=DONATION_COOLDOWN_DAYS)


def cooldown_progress(last_donation_date, today=None):
    """0 to 100: how much of the 90-day rest period has passed (100 means ready to donate)."""
    if last_donation_date is None:
        return 100
    remaining = days_until_eligible(last_donation_date, today)
    passed = DONATION_COOLDOWN_DAYS - remaining
    return max(0, min(100, round(passed * 100 / DONATION_COOLDOWN_DAYS)))
