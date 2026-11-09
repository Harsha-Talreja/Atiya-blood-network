"""The admin panel.

Every view here is wrapped in staff_only (siteadmin.decorators) and every view
that changes something is also POST-only, so a change cannot be triggered by a
link, an image tag or a page someone was tricked into opening. The changes
themselves live in siteadmin.services, which writes the audit log.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from blood_requests.models import BloodRequest, Report
from blood_requests.services import escalate_overdue_requests
from blood_requests.visibility import wait_minutes
from core.charts import requests_per_day
from core.constants import URGENCY_CRITICAL, URGENCY_NORMAL, URGENCY_URGENT
from blood_requests.visibility import max_units_per_request
from siteadmin import selectors, services
from siteadmin.decorators import staff_only
from siteadmin.forms import ExtraUnitsReviewForm, WaitTimesForm
from siteadmin.models import AdminAction, SiteSetting

User = get_user_model()

PAGE_SIZE = 25


def _note(request):
    """The optional reason typed next to the button that was pressed."""
    return request.POST.get("note", "").strip()[:500]


def _page(request, template, page_key, **context):
    """Render an admin page with the side-panel counts already in place.

    Done here rather than in a context processor because a context processor
    would run these five queries on every public page too, where nothing uses
    them.
    """
    context["page_key"] = page_key
    # A hospital that has just missed its deadline reaches the admin's queue (and
    # their notifications) as soon as any admin page loads.
    escalate_overdue_requests()
    # The live search only swaps the table, so it skips the side-panel counts.
    if request.headers.get("X-Requested-With") == "fetch":
        context["nav_counts"] = {}
    else:
        context["nav_counts"] = selectors.sidebar_counts()
    return render(request, template, context)


def _back(request, fallback="siteadmin:overview"):
    """Return the admin to the page they acted from, not to a fixed one.

    Only ever an admin path: taking `next` as given would let someone craft a
    link that bounces a signed-in admin to another site after an action.
    """
    target = request.POST.get("next", "")
    if target.startswith("/admin-panel/"):
        return redirect(target)
    return redirect(fallback)


# ----------------------------------------------------------------- pages


@staff_only
def overview(request):
    return _page(
        request,
        "siteadmin/overview.html",
        "overview",
        **{
            "numbers": selectors.overview_numbers(),
            "attention": selectors.needs_a_person(),
            "activity": AdminAction.objects.all()[:8],
            "supply": selectors.supply_rows(),
            "waits": wait_minutes(),
            "to_review": selectors.awaiting_extra_review()[:6],
            "timed_out": selectors.awaiting_timeout_review()[:6],
            "trend": requests_per_day(BloodRequest.objects.all(), days=7),
        },
    )


@staff_only
def requests(request):
    state = request.GET.get("state", "all")
    query = request.GET.get("q", "").strip()
    rows = selectors.requests_page(state, query)
    return _page(
        request,
        "siteadmin/requests.html",
        "requests",
        **{
            "rows": rows[:PAGE_SIZE],
            "total": rows.count(),
            "state": state,
            "query": query,
            "states": [
                ("all", "All"),
                ("timeout", "Timed out"),
                ("review", "Extra units"),
                ("unchecked", "Unchecked"),
                ("live", "Live"),
                ("fulfilled", "Fulfilled"),
                ("expired", "Expired"),
            ],
        },
    )


def _csv_safe(value):
    """Stop a spreadsheet treating text as a formula (=, +, -, @ at the start)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _request_state_label(req):
    if req.extra_review == "pending":
        return "Waiting for extra-units decision"
    if req.status == "Rejected":
        return "Rejected"
    if req.display_status == "Fulfilled":
        return "Fulfilled"
    if req.display_status == "Expired":
        return "Expired"
    if req.is_verified:
        return "Live, verified by an admin" if req.verified_by_admin else "Live, hospital verified"
    if req.release_label:
        return "Live, " + req.release_label.rstrip(".")
    if req.needs_timeout_review:
        return "Hospital missed deadline, waiting for admin"
    return "Waiting for hospital"


@staff_only
def requests_export(request):
    """The Requests page as a CSV file, for the same tab and search.

    Read-only, so a GET is right. Patient phone numbers are left out on purpose:
    a spreadsheet gets emailed around, and the admin panel is where numbers are read.
    """
    import csv

    from django.http import HttpResponse
    from django.utils import timezone

    state = request.GET.get("state", "all")
    query = request.GET.get("q", "").strip()
    rows = selectors.requests_page(state, query).order_by("-created_at").prefetch_related("responses")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="requests-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("\ufeff")  # lets Excel open Urdu/UTF-8 text correctly
    writer = csv.writer(response)
    writer.writerow(["ID", "Patient", "Blood type", "Units", "Urgency", "Hospital", "City", "State",
                     "Posted by", "Posted at", "Offers"])
    for req in rows:
        writer.writerow([_csv_safe(v) for v in (
            req.pk, req.patient_name, req.blood_type, req.units_needed, req.urgency,
            req.hospital.name, req.hospital.location.city, _request_state_label(req),
            req.requester.username, timezone.localtime(req.created_at).strftime("%Y-%m-%d %H:%M"),
            len(req.responses.all()),
        )])
    return response


@staff_only
def notifications_page(request):
    """The admin's own notifications, inside the panel's layout."""
    from notifications.models import Notification

    items = Notification.objects.filter(user=request.user)[:50]
    return _page(
        request,
        "siteadmin/notifications.html",
        "notifications",
        items=items,
        unread=Notification.objects.filter(user=request.user, read_at__isnull=True).count(),
    )


@staff_only
def donors(request):
    state = request.GET.get("state", "all")
    query = request.GET.get("q", "").strip()
    blood_type = request.GET.get("bt", "").strip()
    rows = selectors.donors_page(state, query, blood_type)
    return _page(
        request,
        "siteadmin/donors.html",
        "donors",
        **{
            "rows": rows[:PAGE_SIZE],
            "total": rows.count(),
            "state": state,
            "query": query,
            "blood_type": blood_type,
            "states": [
                ("all", "All"),
                ("ready", "Ready"),
                ("resting", "Resting"),
                ("unavailable", "Unavailable"),
            ],
            "supply": selectors.supply_rows(),
        },
    )


@staff_only
def users(request):
    state = request.GET.get("state", "all")
    query = request.GET.get("q", "").strip()
    rows = selectors.users_page(state, query)
    return _page(
        request,
        "siteadmin/users.html",
        "users",
        **{
            "rows": rows[:PAGE_SIZE],
            "total": rows.count(),
            "state": state,
            "query": query,
            "states": [("all", "All"), ("reported", "Reported"), ("blocked", "Blocked")],
        },
    )


@staff_only
def reports(request):
    state = request.GET.get("state", "unresolved")
    rows = selectors.reports_page(state)
    return _page(
        request,
        "siteadmin/reports.html",
        "reports",
        **{
            "rows": rows[:PAGE_SIZE],
            "total": rows.count(),
            "state": state,
            "states": [("unresolved", "Unread"), ("resolved", "Resolved"), ("all", "All")],
        },
    )


@staff_only
def hospitals(request):
    rows = selectors.hospitals_page()
    return _page(
        request,
        "siteadmin/hospitals.html",
        "hospitals",
        rows=rows[:PAGE_SIZE],
        total=rows.count(),
    )


@staff_only
def audit(request):
    query = request.GET.get("q", "").strip()
    rows = AdminAction.objects.select_related("actor")
    if query:
        rows = rows.filter(action__icontains=query) | rows.filter(target__icontains=query)
    return _page(
        request,
        "siteadmin/audit.html",
        "audit",
        **{
            "rows": rows[:PAGE_SIZE * 2],
            "total": rows.count(),
            "query": query,
        },
    )


@staff_only
def settings_page(request):
    row = SiteSetting.load()
    form = WaitTimesForm(request.POST or None, instance=row)
    if request.method == "POST" and form.is_valid():
        services.save_wait_times(
            request.user,
            form.cleaned_data["critical_wait_minutes"],
            form.cleaned_data["urgent_wait_minutes"],
            form.cleaned_data["normal_wait_minutes"],
            note=_note(request),
            max_units=form.cleaned_data["max_units_per_request"],
        )
        messages.success(request, "Settings saved.")
        return redirect("siteadmin:settings")
    return _page(
        request,
        "siteadmin/settings.html",
        "settings",
        **{
            "form": form,
            "row": row,
            "urgencies": [URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL],
        },
    )


# --------------------------------------------------------------- actions


@staff_only
@require_POST
def request_verify(request, pk):
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    if services.verify_request(request.user, blood_request, _note(request)):
        messages.success(request, f"{blood_request.patient_name}: verified.")
    else:
        messages.error(request, f"{blood_request.patient_name}: can't be verified now (closed, on hold or already verified).")
    return _back(request, "siteadmin:requests")


@staff_only
@require_POST
def request_timeout(request, pk):
    """Approve or reject a request whose hospital missed its deadline."""
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    decision = request.POST.get("decision", "")
    if decision not in ("approve", "reject"):
        messages.error(request, "Choose approve or reject.")
        return _back(request, "siteadmin:requests")
    approve = decision == "approve"
    if services.review_timeout(request.user, blood_request, approve, _note(request)):
        messages.success(request, f"{blood_request.patient_name}: {'approved' if approve else 'rejected'}.")
    else:
        messages.error(request, f"{blood_request.patient_name}: nothing to decide, it was already handled.")
    return _back(request, "siteadmin:requests")


@staff_only
@require_POST
def request_check(request, pk):
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    services.mark_request_checked(request.user, blood_request, _note(request))
    messages.success(request, f"{blood_request.patient_name}: marked checked.")
    return _back(request, "siteadmin:overview")


@staff_only
@require_POST
def request_remove(request, pk):
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    target = services.remove_request(request.user, blood_request, _note(request))
    messages.success(request, f"Removed {target}.")
    return _back(request, "siteadmin:requests")


@staff_only
@require_POST
def report_resolve(request, pk):
    report = get_object_or_404(Report, pk=pk)
    services.resolve_report(request.user, report, _note(request))
    messages.success(request, "Report resolved.")
    return _back(request, "siteadmin:reports")


@staff_only
@require_POST
def user_block(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "You cannot block your own account.")
        return _back(request, "siteadmin:users")
    if user.is_staff:
        # Staff accounts are managed in Django's admin, where removing a login is
        # deliberate. A block button here would be an easy way for one admin to
        # lock out another by accident.
        messages.error(request, "Staff accounts can't be blocked here.")
        return _back(request, "siteadmin:users")
    if hasattr(user, "hospital_account"):
        # A hospital login is how its requests get verified. Taking it away is a
        # decision about the hospital, not about one person, so it is not one click.
        messages.error(request, "Hospital accounts can't be blocked here.")
        return _back(request, "siteadmin:users")
    services.block_user(request.user, user, _note(request))
    messages.success(request, f"{user.username} is blocked and signed out.")
    return _back(request, "siteadmin:users")


@staff_only
@require_POST
def user_delete(request, pk):
    """Delete a donor or patient account for good. The admin must type the username to confirm."""
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return _back(request, "siteadmin:users")
    if user.is_staff or user.is_superuser:
        messages.error(request, "Staff accounts can't be deleted here.")
        return _back(request, "siteadmin:users")
    if hasattr(user, "hospital_account"):
        messages.error(request, "Hospital accounts can't be deleted here.")
        return _back(request, "siteadmin:users")
    if request.POST.get("confirm_username", "").strip() != user.username:
        messages.error(request, "The username you typed did not match, so nothing was deleted.")
        return _back(request, "siteadmin:users")
    username = user.username
    services.delete_user(request.user, user, _note(request))
    messages.success(request, f"Deleted the account {username} and its information.")
    return _back(request, "siteadmin:users")


@staff_only
@require_POST
def user_unblock(request, pk):
    user = get_object_or_404(User, pk=pk)
    services.unblock_user(request.user, user, _note(request))
    messages.success(request, f"Unblocked {user.username}.")
    return _back(request, "siteadmin:users")


@staff_only
def request_review(request, pk):
    """Read an over-limit request's reason and approve or reject it.

    A page of its own, not a button in a table row, because the decision rests on
    a paragraph the requester wrote and a note the admin has to write back.
    """
    blood_request = get_object_or_404(
        BloodRequest.objects.select_related("hospital", "hospital__location", "requester", "reviewed_by"),
        pk=pk,
    )
    form = ExtraUnitsReviewForm(request.POST or None)
    if request.method == "POST":
        if blood_request.extra_review != "pending":
            messages.error(request, "This request is not waiting for a decision.")
            return redirect("siteadmin:request_review", pk=pk)
        if form.is_valid():
            approve = form.cleaned_data["decision"] == "approve"
            services.review_extra_units(request.user, blood_request, approve, form.cleaned_data["note"])
            messages.success(
                request,
                f"{blood_request.patient_name}: extra units {'approved' if approve else 'rejected'}.",
            )
            return redirect(f"{reverse('siteadmin:requests')}?state=review")
    return _page(
        request,
        "siteadmin/review.html",
        "requests",
        **{
            "req": blood_request,
            "form": form,
            "unit_limit": max_units_per_request(),
            "poster_total": BloodRequest.objects.filter(requester_id=blood_request.requester_id).count(),
        },
    )
