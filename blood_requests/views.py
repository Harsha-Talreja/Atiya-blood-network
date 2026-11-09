from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext, gettext_lazy
from django.views.decorators.http import require_POST

from accounts.models import is_blocked
from blood_requests.contact import contact_links
from blood_requests.forms import BloodRequestForm, ReportForm
from blood_requests.matching import find_matching_donors
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.selectors import most_urgent_first, open_requests
from blood_requests.services import (
    COMMITTED,
    DUPLICATE,
    NOT_A_DONOR,
    OWN_REQUEST,
    CannotRespond,
    DailyLimitReached,
    StatusConflict,
    active_offer,
    check_can_respond,
    create_request,
    daily_limit_message,
    fulfil_request,
    has_reached_daily_limit,
    mark_arrived,
    requests_left_today,
    respond_to_request,
    sidelined_reason,
    withdraw_offer,
)
from blood_requests.tracking import tracking_steps
from blood_requests.visibility import max_units_per_request
from core.constants import (
    BLOOD_TYPES,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    MAX_REQUESTS_PER_USER_PER_DAY,
    STATUS_FULFILLED,
    URGENCY_CRITICAL,
    URGENCY_LEVELS,
    URGENCY_NORMAL,
    URGENCY_URGENT,
)
from core.flash import success_dialog
from core.models import Location
from donors.models import DonorProfile
from hospitals.models import HospitalAccount

DETAIL_MATCHING_DONORS = 6

# Said once, so a blocked person gets the same explanation wherever they are
# stopped. It says what happened and what to do, and does not pretend the site
# is broken.
BLOCKED_MESSAGE = gettext_lazy(
    "An admin has blocked this account from posting requests and offering to help, "
    "usually after reports about it. You can still sign in and see your own history. "
    "If you think this is a mistake, contact the site admin."
)


def _donor_of(user):
    if not user.is_authenticated:
        return None
    return DonorProfile.objects.select_related("location").filter(user=user).first()


# The three ways the board can be ordered. Anything else in the URL falls back
# to "urgent", so a hand-edited query string cannot sort by a column we did not
# mean to expose.
SORTS = {
    "urgent": (gettext_lazy("Most urgent"), None),
    "newest": (gettext_lazy("Newest first"), ("-created_at",)),
    "closing": (gettext_lazy("Closing soon"), ("expires_at",)),
}
DEFAULT_SORT = "urgent"


def _board_url(blood_type, city, sort, urgency):
    """A link back to the board with the filters that are set, and only those."""
    params = {}
    if blood_type:
        params["blood_type"] = blood_type
    if city:
        params["city"] = city
    if urgency:
        params["urgency"] = urgency
    params["sort"] = sort
    return "?" + urlencode(params)


def _send_sidelined_donor_home(request):
    """A donor who cannot give right now is sent to their dashboard instead of a request.

    Returns the redirect, or None when the person may carry on. Only a donor can be
    sidelined; signed-out visitors, hospitals, admins and plain requesters never are.
    """
    reason = sidelined_reason(_donor_of(request.user))
    if reason is None:
        return None
    messages.info(request, reason)
    return redirect("donors:profile")


def request_list(request):
    """Public board of open requests, filterable by blood type, city and urgency."""
    away = _send_sidelined_donor_home(request)
    if away is not None:
        return away
    blood_type = request.GET.get("blood_type", "")
    city = request.GET.get("city", "")
    urgency = request.GET.get("urgency", "")
    if urgency not in URGENCY_LEVELS:
        urgency = ""
    sort = request.GET.get("sort", DEFAULT_SORT)
    if sort not in SORTS:
        sort = DEFAULT_SORT

    requests = open_requests().select_related("location", "hospital")
    if blood_type in BLOOD_TYPES:
        requests = requests.filter(blood_type=blood_type)
    if city:
        requests = requests.filter(location__city=city)

    order = SORTS[sort][1]
    ordered = requests.order_by(*order) if order else most_urgent_first(requests)
    ordered = list(ordered)

    # The urgency tiles count what the blood type and city filters leave, before
    # urgency itself narrows the list, so each tile says what clicking it would show.
    urgency_counts = {level: 0 for level in (URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL)}
    for r in ordered:
        if r.urgency in urgency_counts:
            urgency_counts[r.urgency] += 1
    total_open = len(ordered)
    if urgency:
        ordered = [r for r in ordered if r.urgency == urgency]

    return render(request, "blood_requests/list.html", {
        "requests": ordered,
        "result_count": len(ordered),
        "critical_count": urgency_counts[URGENCY_CRITICAL],
        "blood_types": BLOOD_TYPES,
        "cities": Location.objects.values_list("city", flat=True).distinct().order_by("city"),
        "selected_blood_type": blood_type,
        "selected_city": city,
        "sort": sort,
        "sorts": [(key, label) for key, (label, _) in SORTS.items()],
        "sort_links": [
            (key, label, _board_url(blood_type if blood_type in BLOOD_TYPES else "", city, key, urgency))
            for key, (label, _) in SORTS.items()
        ],
        "selected_urgency": urgency,
        # Clicking the tile that is already on clears it, so each tile is a toggle.
        "urgency_tiles": [
            (
                level,
                urgency_counts[level],
                _board_url(blood_type if blood_type in BLOOD_TYPES else "", city, sort,
                           "" if urgency == level else level),
            )
            for level in (URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL)
        ],
        "total_open": total_open,
        "has_filters": bool(blood_type or city or urgency),
    })


def _track_fill(steps):
    """How far along the timeline line to fill, as a percentage of its length.

    It reaches the dot where the request is now: the active stage, or the last
    finished one when the request has stopped moving.
    """
    reached = 0
    for index, step in enumerate(steps):
        if step["state"] in ("done", "active"):
            reached = index
    return round(reached / max(len(steps) - 1, 1) * 100)


def request_detail(request, pk):
    """Anyone can view; contact details and matching donors are gated further below."""
    blood_request = get_object_or_404(
        BloodRequest.objects.select_related("location", "requester", "hospital", "hospital__location"), pk=pk
    )
    is_owner = request.user.is_authenticated and request.user.pk == blood_request.requester_id
    viewer_donor = _donor_of(request.user)
    # Resting or unavailable donors are not shown other people's requests.
    if not is_owner:
        away = _send_sidelined_donor_home(request)
        if away is not None:
            return away

    # Who may read the reason given for extra units: the person who asked, the
    # admins deciding on it, and the staff of the hospital it names.
    is_hospital_staff = (
        request.user.is_authenticated
        and HospitalAccount.objects.filter(user=request.user, hospital_id=blood_request.hospital_id).exists()
    )
    can_see_reason = is_owner or request.user.is_staff or is_hospital_staff
    # A request over the unit limit that is still waiting for, or was refused by,
    # an admin is not public: only the people above can open it.
    if blood_request.extra_review in (EXTRA_PENDING, EXTRA_REJECTED) and not can_see_reason:
        raise Http404("No such request.")
    # Likewise a request nobody has released yet (neither its hospital nor an
    # admin): it may be fake, so only the people handling it can open it.
    if not (blood_request.is_verified or blood_request.released_early) and not can_see_reason:
        raise Http404("No such request.")

    has_responded = (
        viewer_donor is not None
        and DonorResponse.objects.filter(request=blood_request, donor=viewer_donor).exists()
    )
    # The same rules the POST enforces, asked here so the button only appears for
    # a donor who would actually be accepted, and everyone else is told why not.
    can_offer_help, offer_problem, committed_to = False, "", None
    if (
        request.user.is_authenticated and not request.user.is_staff
        and viewer_donor is not None and not is_owner and not has_responded
    ):
        try:
            check_can_respond(request.user, blood_request)
            can_offer_help = True
        except CannotRespond as refused:
            offer_problem = str(refused)
            if refused.code == COMMITTED:
                committed_to = active_offer(viewer_donor, excluding=blood_request)
    # Who may read the patient's phone number: the person who posted the request,
    # the hospital it names, admins, and donors who offered to help (they need it
    # to arrange the donation). Nobody else, however signed in.
    can_see_contact = can_see_reason or has_responded

    # A count, not a list: everyone may see that two people offered, but only
    # the requester and staff see who they are.
    response_count = blood_request.responses.count()

    my_response = (
        DonorResponse.objects.filter(request=blood_request, donor=viewer_donor).first() if viewer_donor else None
    )
    arrived_count = blood_request.responses.filter(arrived_at__isnull=False).count()
    tracking = tracking_steps(blood_request, response_count, arrived_count)
    context = {
        "req": blood_request,
        "is_owner": is_owner,
        "can_offer_help": can_offer_help,
        "offer_problem": offer_problem,
        "committed_to": committed_to,
        "can_see_contact": can_see_contact,
        "has_responded": has_responded,
        "my_response": my_response,
        "viewer_donor": viewer_donor,
        "response_count": response_count,
        "tracking": tracking,
        "track_fill": _track_fill(tracking),
        "report_form": ReportForm() if request.user.is_authenticated and not request.user.is_staff else None,
        "can_see_reason": can_see_reason,
        "unit_limit": max_units_per_request(),
    }
    if (
        (is_owner or request.user.is_staff)
        and blood_request.is_open
        and blood_request.extra_review not in (EXTRA_PENDING, EXTRA_REJECTED)
    ):
        # A donor who already offered is listed under "Donors who offered", so
        # they are left out of "Donors ready nearby" instead of showing twice.
        offered_ids = blood_request.responses.values_list("donor_id", flat=True)
        context["matching_donors"] = (
            find_matching_donors(blood_request).exclude(pk__in=offered_ids)[:DETAIL_MATCHING_DONORS]
        )
    if is_owner or request.user.is_staff:
        responses = blood_request.responses.select_related("donor__user", "donor__location")
        context["responses"] = responses
        # One entry per donor who offered, with the Call and WhatsApp links. The
        # links exist only for donors who agreed to share their number.
        context["offers"] = [
            {"donor": response.donor, "arrived_at": response.arrived_at,
             **contact_links(blood_request, response.donor)} for response in responses
        ]
    return render(request, "blood_requests/detail.html", context)


@login_required
def request_new(request):
    if is_blocked(request.user):
        messages.error(request, BLOCKED_MESSAGE)
        return redirect("blood_requests:mine")

    # Checked on every visit, GET or POST, and again inside create_request()
    # where the request is saved, so the limit holds however the form is reached.
    if has_reached_daily_limit(request.user):
        messages.error(request, daily_limit_message())
        return redirect("blood_requests:mine")

    form = BloodRequestForm(request.POST or None, user=request.user)
    blood_request = None
    if request.method == "POST" and form.is_valid():
        try:
            # The CNIC (asked once) and the request are saved together or not at all.
            with transaction.atomic():
                form.save_identity()
                blood_request = create_request(request.user, form.save(commit=False))
        except DailyLimitReached as limit:
            messages.error(request, str(limit))
            return redirect("blood_requests:mine")
        except ValidationError as problem:
            form.add_error("cnic", problem)
            blood_request = None
    if blood_request is not None:
        if blood_request.is_awaiting_extra_review:
            success_dialog(
                request, gettext("Request posted"),
                gettext("%(hospital)s needs to verify this request before donors can see it. You asked for "
                        "%(units)s units, more than the standard %(limit)s; if the hospital verifies it, the "
                        "extra units are accepted. If it does not verify in time, an admin decides. You can "
                        "follow it from \"My requests.\"")
                % {"hospital": blood_request.hospital.name, "units": blood_request.units_needed, "limit": form.unit_limit},
            )
        else:
            success_dialog(
                request, gettext("Request posted"),
                gettext("%(hospital)s needs to verify this request before donors can see it. "
                        "You'll be able to track its status from \"My requests.\"")
                % {"hospital": blood_request.hospital.name},
            )
        return redirect("blood_requests:detail", pk=blood_request.pk)
    return render(request, "blood_requests/form.html", {
        "dash_active": "request-new",
        "form": form,
        "requests_left": requests_left_today(request.user),
        "daily_limit": MAX_REQUESTS_PER_USER_PER_DAY,
    })


@login_required
def request_mine(request):
    requests = (
        BloodRequest.objects.filter(requester=request.user)
        .select_related("location", "hospital")
        .annotate(offer_count=Count("responses"))
    )
    # One row per request, with the same four-stage timeline the detail page
    # shows. The count comes from the annotation, so this is still one query.
    rows = []
    for blood_request in requests:
        steps = tracking_steps(blood_request, blood_request.offer_count)
        rows.append({
            "req": blood_request,
            "tracking": steps,
            "track_fill": _track_fill(steps),
            "offers": blood_request.offer_count,
        })
    open_rows = [row for row in rows if row["req"].is_open]
    context = {
        "dash_active": "mine",
        "requests": requests,
        "rows": rows,
        # Open requests stay in the main list; everything else (fulfilled,
        # expired, refused) waits under "Past requests".
        "open_rows": open_rows,
        "past_rows": [row for row in rows if not row["req"].is_open],
        "open_count": len(open_rows),
        "open_offers": sum(row["offers"] for row in open_rows),
        "fulfilled_count": sum(1 for row in rows if row["req"].fulfilled_at is not None),
        "total_count": len(rows),
        "daily_limit": MAX_REQUESTS_PER_USER_PER_DAY,
        "requests_left": requests_left_today(request.user),
        "awaiting_review": sum(1 for row in rows if row["req"].is_awaiting_extra_review),
    }
    return render(request, "blood_requests/mine.html", context)


@login_required
@require_POST
def request_fulfil(request, pk):
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    if not (request.user.pk == blood_request.requester_id or request.user.is_staff):
        raise PermissionDenied(gettext("Only the person who posted this request can mark it fulfilled."))
    try:
        # The requester can only close a request once a donor has offered to help. An admin can always close one.
        changed = fulfil_request(blood_request.pk, require_offer=not request.user.is_staff)
    except StatusConflict as conflict:
        messages.error(request, str(conflict))
    else:
        if changed:
            messages.success(request, gettext("Marked as fulfilled. Thank you for updating the request."))
    return redirect("blood_requests:detail", pk=pk)


@login_required
@require_POST
def request_respond(request, pk):
    """A donor taps 'I can help'."""
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    try:
        respond_to_request(request.user, blood_request.pk)
    except CannotRespond as refused:
        if refused.code == OWN_REQUEST:
            raise PermissionDenied(str(refused)) from refused
        if refused.code == NOT_A_DONOR:
            messages.info(request, str(refused))
            return redirect("donors:edit")
        if refused.code == DUPLICATE:
            messages.info(request, str(refused))
        else:
            messages.error(request, str(refused))
    else:
        messages.success(request, gettext("Thanks! The requester can now see that you're willing to help. "
                                          "The hospital will do the final medical screening."))
    return redirect("blood_requests:detail", pk=pk)


@login_required
@require_POST
def request_withdraw(request, pk):
    """A donor takes back their "I can help"."""
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    try:
        withdraw_offer(request.user, blood_request.pk)
    except CannotRespond as refused:
        messages.error(request, str(refused))
    else:
        messages.success(request, gettext("Your offer was withdrawn. The requester has been told, and you can offer to help elsewhere."))
    return redirect("blood_requests:detail", pk=pk)


@login_required
@require_POST
def request_arrived(request, pk):
    """A donor tells the requester they have reached the hospital."""
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    try:
        changed = mark_arrived(request.user, blood_request.pk)
    except CannotRespond as refused:
        messages.error(request, str(refused))
    else:
        if changed:
            messages.success(request, gettext("Thank you! The requester and the hospital have been told you are there. "
                                              "Show your name at the hospital desk."))
    return redirect("blood_requests:detail", pk=pk)


@login_required
@require_POST
def request_report(request, pk):
    """Flag a request as suspicious. Anyone signed in can report; an admin reviews it."""
    blood_request = get_object_or_404(BloodRequest, pk=pk)
    form = ReportForm(request.POST)

    if not form.is_valid():
        messages.error(request, gettext("Please choose a reason for the report."))
        return redirect("blood_requests:detail", pk=pk)

    report = form.save(commit=False)
    report.request = blood_request
    report.reporter = request.user

    try:
        with transaction.atomic():
            report.save()
    except IntegrityError:
        messages.info(request, gettext("You've already reported this request. An admin will review it."))
    else:
        messages.success(request, gettext("Thanks for the report. An admin will review this request."))
    return redirect("blood_requests:detail", pk=pk)
