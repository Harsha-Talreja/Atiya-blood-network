"""The one place that answers "how long does a request wait for its hospital?".

Both the model property and the queryset read the waits from here, so they can
never disagree about when a request becomes visible. Keeping it in its own module
also keeps blood_requests from importing siteadmin at module level, which would
make the two apps depend on each other in a circle.
"""

from core.constants import (
    AUTO_APPROVE_AFTER_MINUTES,
    AUTO_APPROVE_MINUTES_BY_URGENCY,
    DEFAULT_MAX_UNITS_PER_REQUEST,
)


def wait_minutes():
    """{urgency: minutes} from the settings row, or the code defaults.

    Falls back to the defaults if the settings table is not there yet - which is
    the case while migrations are still running, and in any test database built
    before this app existed.
    """
    try:
        from siteadmin.models import SiteSetting

        return SiteSetting.load().wait_minutes()
    except Exception:
        return dict(AUTO_APPROVE_MINUTES_BY_URGENCY)


def wait_minutes_for(urgency):
    """Minutes this one urgency waits. Unknown urgency falls back to the default."""
    return wait_minutes().get(urgency, AUTO_APPROVE_AFTER_MINUTES)


def max_units_per_request():
    """The standard unit limit: the settings row, or the code default.

    Read on every call rather than cached, so an admin changing it takes effect
    on the very next request. Falls back like wait_minutes() does when the table
    is not there yet.
    """
    try:
        from siteadmin.models import SiteSetting

        return SiteSetting.load().max_units_per_request
    except Exception:
        return DEFAULT_MAX_UNITS_PER_REQUEST
