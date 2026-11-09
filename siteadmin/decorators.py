"""The lock on the admin panel.

Every view in this app is wrapped in staff_only. There is one decorator rather
than a check written out in each view, because a check written out eight times is
a check that gets forgotten the ninth time. siteadmin.test_access walks the URL
map and asserts that every single route refuses a signed-in non-staff user, so
adding a view without the decorator fails the test suite.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def staff_only(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # Not signed in: send them to log in and come back. No hint that the
            # panel exists beyond the login page itself.
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        if not request.user.is_staff:
            # Signed in but not staff: 403, not a redirect. A redirect would tell
            # an ordinary user there is something here worth trying again for.
            raise PermissionDenied("The admin panel is for staff accounts only.")
        return view(request, *args, **kwargs)

    return guarded
