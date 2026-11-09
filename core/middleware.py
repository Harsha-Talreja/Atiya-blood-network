import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.utils.cache import add_never_cache_headers, patch_vary_headers

from accounts.models import is_blocked

BLOCKED_MESSAGE = _("This account has been blocked by an admin, so it cannot be used.")


class PrivatePagesNotCachedMiddleware:
    """Never let the browser keep a page that was made for a signed-in person.

    Without this, pressing Back after logging out can show the previous user's
    dashboard from the browser's own cache, even though the session is gone.
    Pages seen while signed out (the home page, the board) are untouched.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            add_never_cache_headers(response)
        return response


SUPPORTED_LANGUAGES = ("en", "ur", "sd")
ENGLISH_ONLY_PREFIXES = ("/admin-panel/", "/admin/")


class LanguageMiddleware:
    """Show each page in the language the visitor chose (cookie), English if they never chose.

    Only the cookie is read: no Accept-Language parsing, so it costs almost nothing. The admin
    panel is staff-only and stays in English whatever the cookie says. Must sit after
    SessionMiddleware and before anything that makes a message.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME, "en")
        if lang not in SUPPORTED_LANGUAGES or request.path.startswith(ENGLISH_ONLY_PREFIXES):
            lang = "en"
        with translation.override(lang):
            request.LANGUAGE_CODE = lang
            response = self.get_response(request)
        response.headers.setdefault("Content-Language", lang)
        patch_vary_headers(response, ("Cookie",))
        return response


class BlockedUsersSignedOutMiddleware:
    """Sign a blocked person out the moment they are blocked.

    The login form already refuses them, but someone who was signed in when the
    admin pressed Block would otherwise keep their session until it expired.
    Staff are never blocked (the panel refuses to), so they are not checked.
    Must sit after MessageMiddleware so the explanation can be shown.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_staff and is_blocked(user):
            logout(request)
            messages.error(request, BLOCKED_MESSAGE)
            return redirect(reverse("accounts:login"))
        return self.get_response(request)


IDLE_MESSAGE = _("You were logged out after a while without use. Please log in again.")


class StrictAccountsIdleLogoutMiddleware:
    """Log admin and hospital accounts out after a short time without use.

    These accounts can see and change other people's data, so a window left open
    on a shared computer must not stay open for long. The login view marks such a
    session with "strict"; staff are also covered here directly. The time of the
    last request is kept in the session and refreshed at most once a minute, so
    this adds almost no database work. Must sit after MessageMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and (user.is_staff or request.session.get("strict")):
            now = int(time.time())
            last = request.session.get("last_seen")
            if last is not None and now - last > settings.STRICT_IDLE_SECONDS:
                logout(request)
                messages.info(request, IDLE_MESSAGE)
                return redirect(reverse("accounts:login"))
            if last is None or now - last >= 60:
                request.session["last_seen"] = now
        return self.get_response(request)


# The pages and actions that belong to ordinary accounts: giving blood and asking for it.
# An admin account has none of these. It can still open a request to review it
# (blood_requests:detail), close one from there, and use everything in the admin panel.
DONOR_AND_REQUESTER_PAGES = {
    "donors:profile", "donors:edit", "donors:toggle", "donors:donated", "donors:search",
    "blood_requests:new", "blood_requests:mine", "blood_requests:respond", "blood_requests:withdraw", "blood_requests:arrived",
    "blood_requests:report",
}
ADMIN_ONLY_MESSAGE = _("Admin accounts only use the admin panel. Use a separate account to donate or ask for blood.")


class AdminsKeepToAdminPanelMiddleware:
    """Keep an admin account out of the donor and requester pages.

    The links are hidden for admins, but a typed address must not work either,
    so the check is on the server.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        match = request.resolver_match
        if not (user.is_authenticated and user.is_staff and match):
            return None
        if match.view_name in DONOR_AND_REQUESTER_PAGES:
            if request.method == "GET":
                messages.info(request, ADMIN_ONLY_MESSAGE)
            return redirect("siteadmin:overview")
        return None


# The pages and actions of giving blood. A hospital login is for verifying requests
# at its own desk, so it is kept out of these. (It can still post and follow a
# request: staff sometimes ask for blood for a patient.)
DONOR_PAGES = {
    "donors:profile", "donors:edit", "donors:toggle", "donors:donated", "donors:search",
    "blood_requests:respond", "blood_requests:withdraw", "blood_requests:arrived",
}
HOSPITAL_ONLY_MESSAGE = _("Hospital accounts only use the verification desk. Use a separate account to donate blood.")


class HospitalsKeepToTheirDeskMiddleware:
    """Keep a hospital login out of the donor pages, on the server.

    The links are already hidden, but a typed address must not work either: a
    hospital must not be able to register as a donor or offer to help.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        user = request.user
        # The name check comes first, so ordinary pages never pay for the lookup.
        if not (match and match.view_name in DONOR_PAGES and user.is_authenticated and not user.is_staff):
            return None
        from hospitals.models import HospitalAccount

        if not HospitalAccount.objects.filter(user_id=user.pk).exists():
            return None
        if request.method == "GET":
            messages.info(request, HOSPITAL_ONLY_MESSAGE)
        return redirect("hospitals:dashboard")
