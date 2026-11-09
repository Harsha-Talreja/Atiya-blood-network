from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from accounts.forms import LoginForm, SignupForm
from accounts.models import needs_strict_session
from core.flash import success_dialog
from django.utils.translation import gettext


def _safe_next(request):
    """The ?next= address, but only if it stays on this site (blocks open redirects)."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    ok = url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return target if target and ok else ""


@never_cache
def signup(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()  # UserCreationForm hashes the password here
        login(request, user)
        success_dialog(request, gettext("Account created"), gettext("Welcome, %(name)s. Your account is ready.") % {"name": user.get_username()})
        return redirect(_safe_next(request) or "core:dashboard")
    return render(request, "accounts/signup.html", {"form": form, "next": _safe_next(request)})


@method_decorator(never_cache, name="dispatch")
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        """Staff land in the admin panel; everyone else lands on their dashboard.

        A ?next= address still wins, so someone sent to log in from a particular
        page is returned to that page rather than being pulled into the panel.
        """
        target = _safe_next(self.request)
        if target:
            return target
        if self.request.user.is_staff:
            return reverse("siteadmin:overview")
        return resolve_url(self.get_default_redirect_url())

    def _set_session_length(self, form):
        """Admin and hospital accounts: gone when the browser closes, whatever the
        box says. Everyone else: only a ticked "Remember me" lasts 2 weeks."""
        session = self.request.session
        if needs_strict_session(form.get_user()):
            session["strict"] = True
            session.set_expiry(0)
        elif form.cleaned_data.get("remember"):
            session.set_expiry(settings.REMEMBER_ME_AGE)
        else:
            session.set_expiry(0)

    def form_valid(self, form):
        response = super().form_valid(form)
        self._set_session_length(form)
        messages.success(self.request, gettext("Welcome back, %(name)s.") % {"name": form.get_user().get_username()})
        return response


class LogoutView(auth_views.LogoutView):
    """POST only, so a link or another website can never log someone out by accident."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, gettext("You have been logged out."))
        # Tell the browser to drop what it cached for the signed-in person, so the
        # next visitor starts from empty pages. (Only "cache": the theme choice,
        # which lives in local storage, is not personal and is kept.)
        response["Clear-Site-Data"] = '"cache"'
        return response
