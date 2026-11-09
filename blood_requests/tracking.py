"""The four stages a request passes through, for the timeline on its page.

Every stage is derived from fields that already exist; nothing new is stored.
Each stage reports one of three states:

    done      it happened, and `when` says when
    active    this is where the request is right now
    upcoming  it has not happened yet

Exactly one stage is "active" while a request is open, so the timeline always
has one lit dot. A request that is fulfilled or expired has no active stage:
it has stopped moving, and saying otherwise would be a lie on the page.

Why this lives here and not in the template: the wording of stage 2 depends on
*why* the request became visible, and those three reasons must stay mutually
exclusive. A template with four nested ifs gets that wrong quietly; a function
can be tested.
"""

from django.utils.translation import gettext, ngettext

from core.constants import EXTRA_PENDING, EXTRA_REJECTED, TIMEOUT_APPROVED, TIMEOUT_REJECTED

from .models import STATUS_PENDING

DONE, ACTIVE, UPCOMING = "done", "active", "upcoming"


def _stage(key, title, state, when=None, detail=""):
    return {"key": key, "title": title, "state": state, "when": when, "detail": detail}


def tracking_steps(blood_request, response_count=0, arrived_count=0):
    """Return the four stages, in order, for one request.

    `response_count` is passed in rather than read off the object so the caller
    can reuse a count it already has instead of running a second query.
    """
    req = blood_request
    is_fulfilled = req.fulfilled_at is not None
    is_expired = req.is_expired
    has_stopped = is_fulfilled or is_expired
    visible = req.is_visible_to_donors

    steps = [_stage("posted", gettext("Request posted"), DONE, req.created_at,
                    gettext("The hospital and blood type were recorded."))]

    # --- stage 2: why donors can see it, or why they cannot yet -------------
    if req.extra_review == EXTRA_PENDING and not req.hospital_wait_over and not req.is_verified:
        steps.append(_stage(
            "visible", gettext("Waiting for the hospital"), ACTIVE if not has_stopped else UPCOMING, None,
            gettext("This asks for %(units)s units, more than the standard limit. Donors can see it once the "
                    "hospital verifies it; if it does not in time, an admin decides.") % {"units": req.units_needed}))
    elif req.extra_review == EXTRA_PENDING:
        steps.append(_stage(
            "visible", gettext("Waiting for an admin"), ACTIVE if not has_stopped else UPCOMING, None,
            gettext("This asks for %(units)s units, more than the standard limit, so an admin has to "
                    "approve it before donors can see it.") % {"units": req.units_needed}))
    elif req.extra_review == EXTRA_REJECTED:
        steps.append(_stage(
            "visible", gettext("Not approved"), UPCOMING, req.reviewed_at,
            gettext("An admin did not approve the extra units, so donors never saw this request.")))
    elif req.is_verified:
        steps.append(_stage(
            "visible", gettext("Verified by an admin") if req.verified_by_admin else gettext("Verified by the hospital"), DONE,
            req.verified_at or req.created_at,
            (gettext("An admin confirmed this request with the hospital, so donors can see it.") if req.verified_by_admin
             else gettext("%(hospital)s confirmed this request, so donors can see it.") % {"hospital": req.hospital.name})))
    elif req.released_early:
        approved = req.timeout_review == TIMEOUT_APPROVED
        steps.append(_stage(
            "visible", gettext("Approved by an admin") if approved else gettext("Released by an admin"), DONE,
            req.timeout_decided_at if approved else req.released_at or req.created_at,
            req.release_label))
    elif req.timeout_review == TIMEOUT_REJECTED:
        steps.append(_stage(
            "visible", gettext("Not approved"), UPCOMING, req.timeout_decided_at,
            gettext("%(hospital)s did not verify it in time and an admin did not approve it, so donors never saw it.")
            % {"hospital": req.hospital.name}))
    elif req.needs_timeout_review:
        steps.append(_stage(
            "visible", gettext("Waiting for an admin"), ACTIVE, None,
            gettext("%(hospital)s did not verify it in time, so an admin will approve or reject it. "
                    "Donors cannot see it until then.") % {"hospital": req.hospital.name}))
    elif has_stopped:
        # The request died before anyone released it, so nobody ever saw it.
        steps.append(_stage(
            "visible", gettext("Never reached donors"), UPCOMING, None,
            gettext("The request closed before it was verified or approved.")))
    else:
        steps.append(_stage(
            "visible", gettext("Waiting for the hospital"), ACTIVE, None,
            gettext("If %(hospital)s does not verify it in time, an admin decides whether donors see it.")
            % {"hospital": req.hospital.name}))

    # --- stage 3: has anyone offered ---------------------------------------
    if response_count:
        steps.append(_stage(
            "offered", gettext("A donor offered to help"), DONE, None,
            ngettext("%(n)s donor said they can donate.", "%(n)s donors said they can donate.", response_count)
            % {"n": response_count}))
    elif visible and not has_stopped:
        steps.append(_stage(
            "offered", gettext("Waiting for a donor"), ACTIVE, None,
            gettext("Compatible donors nearby can see this request now.")))
    else:
        steps.append(_stage("offered", gettext("A donor offers to help"), UPCOMING, None, ""))

    # --- stage 3b: has a donor reached the hospital ------------------------
    if response_count and arrived_count:
        steps.append(_stage(
            "arrived", gettext("A donor reached the hospital"), DONE, None,
            ngettext("%(n)s donor is at the hospital.", "%(n)s donors are at the hospital.", arrived_count)
            % {"n": arrived_count}))
    elif response_count and not has_stopped:
        steps.append(_stage(
            "arrived", gettext("A donor reaches the hospital"), UPCOMING, None,
            gettext("The donor taps \"I've reached the hospital\" when they get there.")))

    # --- stage 4: how it ended ---------------------------------------------
    if is_fulfilled:
        steps.append(_stage("closed", gettext("Marked fulfilled"), DONE, req.fulfilled_at,
                            gettext("The requester confirmed the blood was arranged.")))
    elif is_expired:
        steps.append(_stage("closed", gettext("Expired"), DONE, req.expires_at,
                            gettext("The request ran out of time and is no longer shown.")))
    elif req.extra_review == EXTRA_REJECTED:
        steps.append(_stage("closed", gettext("Closed"), DONE, req.reviewed_at,
                            gettext("The request was closed when the extra units were not approved.")))
    elif req.timeout_review == TIMEOUT_REJECTED:
        steps.append(_stage("closed", gettext("Closed"), DONE, req.timeout_decided_at,
                            gettext("The request was closed because an admin did not approve it.")))
    elif req.status != STATUS_PENDING:
        steps.append(_stage("closed", gettext("Closed"), DONE, None, ""))
    else:
        steps.append(_stage("closed", gettext("Marked fulfilled"), UPCOMING, None,
                            gettext("The requester closes the request once blood is arranged.")))

    return steps
