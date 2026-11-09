"""Business logic for blood_requests that isn't tied to HTTP, so it's testable
on its own (same pattern as donors/eligibility.py)."""
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from django.urls import reverse

from accounts.models import is_blocked
from blood_requests.matching import find_matching_donors
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.selectors import awaiting_extra_review, awaiting_timeout_review
from core.blood import can_donate
from core.constants import (
    EXTRA_APPROVED,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    MAX_REQUESTS_PER_USER_PER_DAY,
    STATUS_FULFILLED,
    STATUS_PENDING,
)
from donors.models import DonorProfile
from notifications import services as notes
from notifications.models import Notification


class DailyLimitReached(Exception):
    """The requester has already submitted today's allowance."""


def daily_limit_message():
    return gettext(
        "You have reached your daily limit of %(limit)s blood requests. Please try again tomorrow."
    ) % {"limit": MAX_REQUESTS_PER_USER_PER_DAY}


def requests_posted_today(user):
    """How many requests this user has submitted since midnight (their local date).

    Every saved request counts, whatever became of it: pending, approved,
    fulfilled, expired or rejected. A form that was opened but never submitted,
    or submitted with errors, saved nothing and so counts for nothing. The day
    rolls over at local midnight (settings.TIME_ZONE).
    """
    return BloodRequest.objects.filter(requester=user, created_at__date=timezone.localdate()).count()


def requests_left_today(user):
    return max(0, MAX_REQUESTS_PER_USER_PER_DAY - requests_posted_today(user))


def has_reached_daily_limit(user):
    return requests_posted_today(user) >= MAX_REQUESTS_PER_USER_PER_DAY


@transaction.atomic
def create_request(user, blood_request):
    """Save a new request, unless the requester is out of requests for today.

    The check and the save happen in one transaction, and the requester's row is
    locked while they do, so two submissions sent at the same moment cannot both
    slip under the limit (on a database that supports row locks; SQLite already
    serialises writers).

    Raises DailyLimitReached; the caller shows daily_limit_message().
    """
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if has_reached_daily_limit(user):
        raise DailyLimitReached(daily_limit_message())
    blood_request.requester = user  # always the signed-in person
    blood_request.location = blood_request.hospital.location  # always matches the hospital
    blood_request.save()
    _announce_new_request(blood_request)
    return blood_request


def _announce_new_request(blood_request):
    """Tell the people who have to act on a brand-new request."""
    who = f"{blood_request.patient_name} ({blood_request.blood_type})"
    notes.notify_many(
        notes.hospital_staff(blood_request.hospital),
        Notification.REQUEST_FOR_HOSPITAL,
        f"New {blood_request.urgency.lower()} request for {who}. Please verify it.",
        blood_request,
        url=reverse("hospitals:dashboard"),
    )


# ---------------------------------------------------------------- escalation


@transaction.atomic
def escalate_overdue_requests_soon(every=60):
    """Run the deadline check at most once every `every` seconds.

    The bell asks "anything new?" every half minute from every open tab, and each
    ask used to run the full check, which opens a database write. Deadlines are
    hours long, so once a minute is plenty. cache.add only succeeds for the first
    caller in the window, so everyone else skips the work and returns 0.
    """
    if caches["snap"].add("bn:escalation-check", 1, every):
        return escalate_overdue_requests()
    return 0


def escalate_overdue_requests():
    """Notice requests whose hospital missed its deadline and tell the admins.

    Nothing is released here. A late request simply sits in the admin's review
    queue (selectors.awaiting_timeout_review is derived from the clock, so it is
    right even if this never runs); this only makes sure people are TOLD, once.
    Called from the notification poll, the admin panel and the hospital desk, so
    no scheduler is needed. Returns how many requests were escalated.
    """
    now = timezone.now()
    count = 0
    for blood_request in awaiting_timeout_review().filter(escalated_at__isnull=True)[:100]:
        # The UPDATE is the lock: if two polls arrive together only one changes a
        # row, so only one sends the notifications.
        claimed = BloodRequest.objects.filter(pk=blood_request.pk, escalated_at__isnull=True).update(escalated_at=now)
        if not claimed:
            continue
        count += 1
        who = f"{blood_request.patient_name} ({blood_request.blood_type})"
        notes.notify_admins(
            Notification.TIMED_OUT,
            f"{blood_request.hospital.name} did not verify {who} in time. Approve or reject it.",
            blood_request,
            url=reverse("siteadmin:requests") + "?state=timeout",
        )
        notes.notify(
            blood_request.requester,
            Notification.TIMED_OUT,
            f"{blood_request.hospital.name} has not verified your request yet. "
            "An admin will decide whether donors can see it.",
            blood_request,
        )
    for blood_request in awaiting_extra_review().filter(escalated_at__isnull=True)[:100]:
        claimed = BloodRequest.objects.filter(pk=blood_request.pk, escalated_at__isnull=True).update(escalated_at=now)
        if not claimed:
            continue
        count += 1
        who = f"{blood_request.patient_name} ({blood_request.blood_type})"
        notes.notify_admins(
            Notification.NEEDS_REVIEW,
            f"{blood_request.hospital.name} did not verify {who}, which asks for "
            f"{blood_request.units_needed} units, more than the standard limit. It needs an admin's decision.",
            blood_request,
            url=reverse("siteadmin:request_review", args=[blood_request.pk]),
        )
        notes.notify(
            blood_request.requester,
            Notification.TIMED_OUT,
            f"{blood_request.hospital.name} has not verified your request yet. "
            "An admin will decide whether donors can see it.",
            blood_request,
        )
    return count


# ------------------------------------------------------------------ responding


def sidelined_reason(donor):
    """Why this donor is not shown other people's requests right now, or None.

    A donor who is resting after a donation, or who switched availability off,
    cannot give blood, so the site does not dangle requests in front of them:
    the lists are replaced by this sentence and other people's requests are not
    opened for them. Their own requests are not affected.
    """
    if donor is None:
        return None
    if not donor.is_available:
        return gettext(
            "You are marked as unavailable, so requests are hidden. Turn your availability on to see them."
        )
    if not donor.is_eligible:
        return gettext(
            "You are in your resting period until %(date)s, so requests are hidden. "
            "They will appear again when you can donate."
        ) % {"date": date_format(donor.next_eligible_date, "j M Y")}
    return None


class CannotRespond(Exception):
    """A donor's "I can help" was refused. `code` is stable for tests and the UI;
    str(error) is the sentence to show the person."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


NOT_A_DONOR = "no_profile"
OWN_REQUEST = "own_request"
CLOSED = "closed"
NOT_VISIBLE = "not_visible"
INCOMPATIBLE = "incompatible"
UNAVAILABLE = "unavailable"
RESTING = "resting"
DUPLICATE = "duplicate"
COMMITTED = "committed"
OTHER_CITY = "other_city"
NOT_OFFERED = "not_offered"
BLOCKED = "blocked"
FILLED = "filled"


def active_offer(donor, excluding=None):
    """The one open request this donor has already offered to help with, or None.

    "Open" means still pending and not expired, so the commitment ends by itself when the
    request is fulfilled, closed, rejected or runs out of time: a donor is never stuck
    because a requester forgot to press "Mark fulfilled".
    """
    offers = (
        DonorResponse.objects.filter(donor=donor, request__status=STATUS_PENDING)
        .exclude(request__extra_review=EXTRA_REJECTED)
        .select_related("request")
        .order_by("-created_at")
    )
    for offer in offers:
        if offer.request_id != getattr(excluding, "pk", None) and not offer.request.is_expired:
            return offer.request
    return None


def can_record_donation(donor):
    """May this donor press "I donated today"?

    Only a donor who is not already resting and who has offered to help a request that
    is still open. Without that the button would let anyone start their 90-day rest,
    and drop out of matching, by accident or by testing it. (When the family marks the
    request fulfilled, the donors who helped are put to rest automatically.)
    """
    return donor is not None and donor.is_eligible and active_offer(donor) is not None


def check_can_respond(user, blood_request):
    """Every rule for "I can help", in one place. Returns the donor's profile, or
    raises CannotRespond naming the first rule that fails.

    This is the backend's check; the page hiding the button is only a courtesy.
    It is a first screen, not a medical clearance: the hospital still does the
    final screening before any blood is taken.
    """
    if is_blocked(user):
        raise CannotRespond(BLOCKED, gettext("Your account is blocked, so you can't offer to help."))
    donor = DonorProfile.objects.select_related("location").filter(user=user).first()
    if donor is None:
        raise CannotRespond(NOT_A_DONOR, gettext("Register as a donor first so requesters can see your details."))
    if user.pk == blood_request.requester_id:
        raise CannotRespond(OWN_REQUEST, gettext("You can't respond to your own request."))
    if blood_request.status == STATUS_FULFILLED:
        raise CannotRespond(CLOSED, gettext("This request has already been fulfilled."))
    if blood_request.status != STATUS_PENDING or blood_request.extra_review == EXTRA_REJECTED:
        raise CannotRespond(CLOSED, gettext("This request is closed."))
    if blood_request.is_expired:
        raise CannotRespond(CLOSED, gettext("This request has expired."))
    if not blood_request.is_visible_to_donors:
        raise CannotRespond(NOT_VISIBLE, gettext("This request hasn't been verified or released yet."))
    if not can_donate(donor.blood_type, blood_request.blood_type):
        raise CannotRespond(
            INCOMPATIBLE,
            gettext("Your blood type (%(donor)s) can't be given to a %(patient)s patient.")
            % {"donor": donor.blood_type, "patient": blood_request.blood_type},
        )
    if donor.location.city != blood_request.location.city:
        raise CannotRespond(
            OTHER_CITY,
            gettext("This request is in %(request_city)s, but your donor profile says %(donor_city)s. "
                    "You can offer to help requests in your own city. "
                    "If you have moved, update your area on your donor profile.")
            % {"request_city": blood_request.location.city, "donor_city": donor.location.city},
        )
    if not donor.is_available:
        raise CannotRespond(UNAVAILABLE, gettext("You're marked as unavailable. Turn availability on first."))
    if not donor.is_eligible:
        raise CannotRespond(
            RESTING,
            gettext("You're resting after your last donation until %(date)s.")
            % {"date": date_format(donor.next_eligible_date, "j M Y")},
        )
    if DonorResponse.objects.filter(request=blood_request, donor=donor).exists():
        raise CannotRespond(DUPLICATE, gettext("You've already offered to help with this request."))
    # One donor has already offered. Their offer is not a reason to keep the request open to
    # everyone else; if they withdraw, it opens again.
    if blood_request.responses.exists():
        raise CannotRespond(
            FILLED,
            gettext("Another donor has already offered to help with this request. "
                    "If they withdraw, it will open again."),
        )
    # One commitment at a time: one donation means a long rest, so an offer here would be a
    # promise the donor cannot keep to a second requester.
    committed = active_offer(donor, excluding=blood_request)
    if committed is not None:
        raise CannotRespond(
            COMMITTED,
            gettext("You've already offered to help %(patient)s. You can offer here once that "
                    "request is fulfilled or closed, or if you withdraw your offer.")
            % {"patient": committed.patient_name},
        )
    return donor


@transaction.atomic
def respond_to_request(user, request_id):
    """Record "I can help" if, and only if, every rule in check_can_respond holds.

    The request row is locked and re-read, so a requester marking it fulfilled at
    the same moment cannot be followed by a response to a request that just
    closed. Raises CannotRespond; otherwise returns the new DonorResponse.
    """
    blood_request = BloodRequest.objects.select_for_update().select_related("hospital").get(pk=request_id)
    donor = check_can_respond(user, blood_request)
    response = DonorResponse.objects.create(request=blood_request, donor=donor)
    notes.notify(
        blood_request.requester,
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor offered to help with {blood_request.patient_name}'s request.",
        blood_request,
    )
    # The hospital does the final screening, so its staff hear about offers too
    # (except the requester, who has just been told above).
    notes.notify_many(
        [u for u in notes.hospital_staff(blood_request.hospital) if u.pk != blood_request.requester_id],
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor offered to help {blood_request.patient_name} ({blood_request.blood_type}) "
        "at your hospital. Final screening is up to you.",
        blood_request,
    )
    return response


@transaction.atomic
def withdraw_offer(user, request_id):
    """Take back "I can help" while the request is still open.

    Frees the donor to offer elsewhere and tells the requester (and the hospital's staff, who
    were told about the offer) so nobody expects them. Raises CannotRespond if there is no
    offer to take back or the request has already closed.
    """
    blood_request = BloodRequest.objects.select_for_update().select_related("hospital").get(pk=request_id)
    donor = DonorProfile.objects.filter(user=user).first()
    response = DonorResponse.objects.filter(request=blood_request, donor=donor).first() if donor else None
    if response is None:
        raise CannotRespond(NOT_OFFERED, gettext("You haven't offered to help with this request."))
    if not blood_request.is_open:
        raise CannotRespond(CLOSED, gettext("This request is already closed, so the offer can't be withdrawn."))
    response.delete()
    notes.notify(
        blood_request.requester,
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor withdrew their offer on {blood_request.patient_name}'s request.",
        blood_request,
    )
    notes.notify_many(
        [u for u in notes.hospital_staff(blood_request.hospital) if u.pk != blood_request.requester_id],
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor withdrew their offer for {blood_request.patient_name} "
        f"({blood_request.blood_type}).",
        blood_request,
    )


@transaction.atomic
def mark_arrived(user, request_id):
    """The donor taps "I've reached the hospital" on a request they offered to help with.

    Tells the requester and the hospital's staff, so nobody has to ask "where are you?".
    Only the donor's own offer on a still-open request can be marked, and only once.
    Returns True if it changed, False if the donor had already said so. Raises
    CannotRespond when there is no offer to mark or the request has closed.
    """
    blood_request = BloodRequest.objects.select_for_update().select_related("hospital").get(pk=request_id)
    donor = DonorProfile.objects.filter(user=user).first()
    response = DonorResponse.objects.filter(request=blood_request, donor=donor).first() if donor else None
    if response is None:
        raise CannotRespond(NOT_OFFERED, gettext("You haven't offered to help with this request."))
    if not blood_request.is_open:
        raise CannotRespond(CLOSED, gettext("This request is already closed."))
    if response.arrived_at is not None:
        return False
    response.arrived_at = timezone.now()
    response.save(update_fields=["arrived_at"])
    notes.notify(
        blood_request.requester,
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor has reached {blood_request.hospital.name} for {blood_request.patient_name}'s request.",
        blood_request,
        url=reverse("blood_requests:detail", args=[blood_request.pk]),
    )
    notes.notify_many(
        [u for u in notes.hospital_staff(blood_request.hospital) if u.pk != blood_request.requester_id],
        Notification.DONOR_RESPONSE,
        f"A {donor.blood_type} donor has reached your hospital for {blood_request.patient_name} "
        f"({blood_request.blood_type}). Final screening is up to you.",
        blood_request,
    )
    return True


# ----------------------------------------------------------------- status changes


class StatusConflict(Exception):
    """The change would contradict the request's current state."""


@transaction.atomic
def fulfil_request(blood_request_id, require_offer=False):
    """Mark a request fulfilled. Returns True if it changed, False if it already was.

    A rejected request can't be fulfilled: it was refused, so "fulfilled" would
    contradict the admin's decision. Donors who offered are told it is done so
    nobody travels to a hospital for blood that is no longer needed.

    require_offer=True is what the requester's button uses: a request nobody has offered
    to help with cannot be closed as fulfilled, because nothing was fulfilled.
    """
    blood_request = BloodRequest.objects.select_for_update().get(pk=blood_request_id)
    if blood_request.status == STATUS_FULFILLED:
        return False
    if blood_request.status != STATUS_PENDING:
        raise StatusConflict(gettext("A rejected request can't be marked fulfilled."))
    if require_offer and not blood_request.responses.exists():
        raise StatusConflict(gettext("A donor needs to offer to help before you can mark this fulfilled."))
    blood_request.status = STATUS_FULFILLED
    blood_request.fulfilled_at = timezone.now()
    blood_request.save(update_fields=["status", "fulfilled_at"])
    responses = list(blood_request.responses.select_related("donor__user").order_by("created_at", "pk"))
    # The donors who gave blood start their rest now, without pressing anything. The site
    # cannot tell who gave, so it takes the earliest offers, as many as units were needed.
    gave = responses[: max(blood_request.units_needed, 1)]
    today = timezone.localdate()
    for response in gave:
        donor = response.donor
        if donor.last_donation_date is None or donor.last_donation_date < today:
            donor.last_donation_date = today
            donor.save(update_fields=["last_donation_date"])
        notes.notify(
            donor.user,
            Notification.FULFILLED,
            f"{blood_request.patient_name}'s request was marked fulfilled. Thank you for donating. "
            f"You are resting until {date_format(donor.next_eligible_date, 'j M Y')}.",
            blood_request,
        )
    notes.notify_many(
        [r.donor.user for r in responses[len(gave):]],
        Notification.FULFILLED,
        f"{blood_request.patient_name}'s request was marked fulfilled. Thank you for offering to help.",
        blood_request,
    )
    return True


@transaction.atomic
def verify_by_hospital(user, blood_request_id):
    """A hospital's staff member verifying a request routed to them.

    Allowed even after the deadline (a late genuine verification is still
    useful and removes the request from the admin's queue), but never on a
    request that is already closed. Returns True if it changed.
    """
    blood_request = BloodRequest.objects.select_for_update().select_related("hospital").get(pk=blood_request_id)
    if blood_request.is_verified:
        return False
    if blood_request.status != STATUS_PENDING:
        raise StatusConflict(gettext("This request is already closed, so it can't be verified."))
    blood_request.is_verified = True
    blood_request.verified_by = user
    blood_request.verified_at = timezone.now()
    fields = ["is_verified", "verified_by", "verified_at"]
    if blood_request.extra_review == EXTRA_PENDING:
        # The hospital checked the patient, so the extra units are accepted with it. An admin
        # is only asked when the hospital does not act in time.
        blood_request.extra_review = EXTRA_APPROVED
        blood_request.reviewed_by = user
        blood_request.reviewed_at = blood_request.verified_at
        fields += ["extra_review", "reviewed_by", "reviewed_at"]
    blood_request.save(update_fields=fields)
    notes.notify(
        blood_request.requester,
        Notification.HOSPITAL_VERIFIED,
        f"{blood_request.hospital.name} verified {blood_request.patient_name}'s request. Donors can see it now.",
        blood_request,
    )
    announce_if_visible(blood_request.pk)
    return True


# ------------------------------------------------------------ telling donors

MAX_DONORS_NOTIFIED = 200


def announce_if_visible(blood_request_id):
    """Tell matching donors about a request, if donors can see it now.

    Call this after anything that can make a request visible (hospital or admin
    verification, early release, an admin approving after a timeout or the extra
    units). It re-reads the request, so it is safe to call when nothing changed:
    a request that is still hidden tells nobody, and a donor who was already told
    about this request is never told twice. Returns how many were notified.
    """
    blood_request = BloodRequest.objects.select_related("hospital", "location").get(pk=blood_request_id)
    if not (blood_request.is_open and blood_request.is_visible_to_donors):
        return 0
    already = set(
        Notification.objects.filter(request=blood_request, kind=Notification.NEW_MATCH).values_list("user_id", flat=True)
    )
    # Same people the requester sees under "Matching donors nearby": compatible
    # type, same city, available, rested. Blocked accounts can't respond, so skip them.
    donors = (
        find_matching_donors(blood_request)
        .filter(user__block__isnull=True)
        .exclude(user_id__in=already)[:MAX_DONORS_NOTIFIED]
    )
    message = (
        f"{blood_request.urgency}: {blood_request.blood_type} needed at {blood_request.hospital.name}, "
        f"{blood_request.location.area}. Your blood type can help."
    )
    created = notes.notify_many([d.user for d in donors], Notification.NEW_MATCH, message, blood_request)
    return len(created)
