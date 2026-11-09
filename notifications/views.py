from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from blood_requests.services import escalate_overdue_requests_soon
from notifications import services
from notifications.models import Notification

PAGE_SIZE = 50


@login_required
@never_cache
def inbox(request):
    if request.user.is_staff:
        return redirect("siteadmin:notifications")  # admins read theirs inside the panel
    escalate_overdue_requests_soon()
    items = Notification.objects.filter(user=request.user)[:PAGE_SIZE]
    return render(request, "notifications/inbox.html", {
        "items": items,
        "unread": services.unread_count(request.user),
    })


@login_required
@require_GET
@never_cache
def count(request):
    """Polled by the bell every few seconds. Also where a missed hospital deadline
    is noticed, so the admin hears about it without anyone running a scheduler."""
    escalate_overdue_requests_soon()
    latest = Notification.objects.filter(user=request.user).values_list("id", flat=True).first()
    return JsonResponse({"unread": services.unread_count(request.user), "latest": latest or 0})


@login_required
@require_POST
def read(request, pk):
    """Mark one read, then go where it points."""
    note = services.mark_read(request.user, pk)
    target = note.url if note is not None else ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        return redirect(target)
    return redirect("notifications:inbox")


@login_required
@require_POST
def read_all(request):
    services.mark_all_read(request.user)
    return redirect("notifications:inbox")
