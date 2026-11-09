"""Developer-only pages. They return 404 unless DEBUG is on, so they are never public."""
from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import defaults

from core.forms import StyleGuideDemoForm


def _debug_only():
    if not settings.DEBUG:
        raise Http404("Developer pages are only available when DEBUG is on.")


def _sample_request(pk, urgency, blood_type, hospital, area, hours_left, verified=False):
    now = timezone.now()
    return SimpleNamespace(
        pk=pk, blood_type=blood_type, urgency=urgency, display_status="Pending", is_verified=verified,
        hospital=SimpleNamespace(name=hospital), units_needed=2, created_at=now - timedelta(minutes=18),
        expires_at=now + hours_left,
        location=SimpleNamespace(area=area, city="Sukkur"),
    )


def style_guide(request):
    _debug_only()
    now = timezone.now()
    clean_form = StyleGuideDemoForm()
    error_form = StyleGuideDemoForm({"full_name": "", "phone": "12345", "blood_type": "", "password": "abc"})
    error_form.is_valid()  # populate errors so the page can show them
    samples = [
        _sample_request(1, "Critical", "O-", "Example Civil Hospital", "Barrage Road", timedelta(hours=3, minutes=12), True),
        _sample_request(2, "Urgent", "A+", "Example Medical Center", "Military Road", timedelta(hours=40)),
        _sample_request(3, "Normal", "B+", "Example Blood Bank", "Minara Road", timedelta(hours=70)),
        _sample_request(4, "Critical", "AB-", "Example Trauma Unit", "Old Sukkur", timedelta(minutes=42)),
    ]
    return render(request, "core/style_guide.html", {
        "clean_form": clean_form, "error_form": error_form, "samples": samples,
        "swatches": [
            ("Brand", "var(--brand)"), ("Brand text", "var(--brand-text)"), ("Blood", "var(--blood)"),
            ("Tint", "var(--tint)"), ("Surface", "var(--surface)"), ("Background", "var(--bg)"),
            ("Text", "var(--text)"), ("Muted", "var(--muted)"),
        ],
        "now": now,
    })


def preview_403(request):
    _debug_only()
    return defaults.permission_denied(request, Exception("This is a preview of the 403 page."))


def preview_404(request):
    _debug_only()
    return defaults.page_not_found(request, Exception("preview"))


def preview_500(request):
    _debug_only()
    return defaults.server_error(request)
