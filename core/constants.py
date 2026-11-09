"""Project-wide constants. Pure Python, no Django imports.

Values are stored as readable words ("Critical", "Pending") so the database
and the admin panel are easy to read without a lookup table.
"""

# --- Blood types -----------------------------------------------------------
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
BLOOD_TYPE_CHOICES = [(bt, bt) for bt in BLOOD_TYPES]  # for model/form fields

# --- Urgency ---------------------------------------------------------------
URGENCY_NORMAL = "Normal"
URGENCY_URGENT = "Urgent"
URGENCY_CRITICAL = "Critical"
URGENCY_LEVELS = [URGENCY_NORMAL, URGENCY_URGENT, URGENCY_CRITICAL]
URGENCY_CHOICES = [(u, u) for u in URGENCY_LEVELS]

# How many hours a request stays open before it counts as Expired.
URGENCY_HOURS = {
    URGENCY_CRITICAL: 24,
    URGENCY_URGENT: 48,
    URGENCY_NORMAL: 72,
}

# --- Request status --------------------------------------------------------
STATUS_PENDING = "Pending"
STATUS_FULFILLED = "Fulfilled"
# "Expired" is DERIVED (Pending + past expires_at), never stored in the DB.
# It exists only so display code has one constant to use.
STATUS_EXPIRED = "Expired"
# Stored: an admin turned down a request that asked for more than the unit limit.
STATUS_REJECTED = "Rejected"

# Only the STORED statuses are valid choices for the database field.
REQUEST_STATUS_CHOICES = [
    (STATUS_PENDING, STATUS_PENDING),
    (STATUS_FULFILLED, STATUS_FULFILLED),
    (STATUS_REJECTED, STATUS_REJECTED),
]

# --- Donation rule ---------------------------------------------------------
DONATION_COOLDOWN_DAYS = 90

# --- Verification -----------------------------------------------------------
# A request is hidden from donors until its hospital verifies it. If the hospital
# misses its deadline (the "wait" below) the request is NOT released on its own:
# it moves to the admin's review queue, and an admin approves or rejects it. For
# a real emergency an admin can also release it before the deadline. Either way
# the request is labelled "not hospital verified", so nobody is misled.
#
# The wait is per urgency, because the trade-off is not the same for all three.
# Waiting costs a Critical patient more than it costs a Normal one, while a long
# wait is what gives hospital verification any real meaning. So a sensible live
# setting is short for Critical and long for Normal.
#
# All three are 1 minute here so the behaviour can be shown during a demo without
# anyone waiting around. These are only the DEFAULTS used to create the settings
# row the first time; after that the live values come from siteadmin.SiteSetting
# and are changed from the admin panel, not from this file.
AUTO_APPROVE_AFTER_MINUTES = 1  # kept as the fallback when no settings row exists
AUTO_APPROVE_MINUTES_BY_URGENCY = {
    URGENCY_CRITICAL: 1,
    URGENCY_URGENT: 1,
    URGENCY_NORMAL: 1,
}
# Guard rails for the value the panel will accept, so a typo cannot hide every
# request for a week or switch verification off altogether.
AUTO_APPROVE_MINUTES_MIN = 1
AUTO_APPROVE_MINUTES_MAX = 1440  # one day

# --- Abuse prevention -------------------------------------------------------
MAX_REQUESTS_PER_USER_PER_DAY = 3

# --- Units per request -------------------------------------------------------
# The standard limit. The live value is a setting an admin changes from the
# panel (siteadmin.SiteSetting.max_units_per_request); this is only the starting
# value and the fallback. Actual need is a medical decision, so asking for more
# is allowed - it just goes to an admin with a reason instead of straight out.
DEFAULT_MAX_UNITS_PER_REQUEST = 4
MAX_UNITS_LIMIT_MIN = 1
MAX_UNITS_LIMIT_MAX = 20
# The most any single request can ask for, whatever the standard limit is.
UNITS_HARD_CAP = 20
# A one-word reason is not an explanation.
EXTRA_REASON_MIN_LENGTH = 15

# --- Review of requests that ask for more than the limit -----------------------
EXTRA_NONE = "none"          # within the limit, nothing to review
EXTRA_PENDING = "pending"    # over the limit, waiting for an admin
EXTRA_APPROVED = "approved"
EXTRA_REJECTED = "rejected"
EXTRA_REVIEW_CHOICES = [
    (EXTRA_NONE, "Not needed"),
    (EXTRA_PENDING, "Waiting for an admin"),
    (EXTRA_APPROVED, "Approved"),
    (EXTRA_REJECTED, "Rejected"),
]

# --- What happens when a hospital misses its deadline -----------------------------
# The request does NOT go to donors on its own. It waits in the admin's review
# queue, and only an admin's decision (or the hospital verifying it late) makes
# it visible. These are the two decisions an admin can make about it.
TIMEOUT_NONE = "none"
TIMEOUT_APPROVED = "approved"
TIMEOUT_REJECTED = "rejected"
TIMEOUT_REVIEW_CHOICES = [
    (TIMEOUT_NONE, "No decision"),
    (TIMEOUT_APPROVED, "Approved by an admin"),
    (TIMEOUT_REJECTED, "Rejected by an admin"),
]
# The exact wording shown wherever an admin, and not a hospital, let a request out.
ADMIN_RELEASED_LABEL = "Admin released \u2014 not hospital verified."
ADMIN_APPROVED_LABEL = "Admin approved \u2014 not hospital verified."

REPORT_REASON_FAKE = "Fake or hoax"
REPORT_REASON_ALREADY_FULFILLED = "Already fulfilled elsewhere"
REPORT_REASON_SPAM = "Spam or advertising"
REPORT_REASON_INAPPROPRIATE = "Inappropriate content"
REPORT_REASON_OTHER = "Other"
REPORT_REASONS = [
    REPORT_REASON_FAKE, REPORT_REASON_ALREADY_FULFILLED, REPORT_REASON_SPAM,
    REPORT_REASON_INAPPROPRIATE, REPORT_REASON_OTHER,
]
REPORT_REASON_CHOICES = [(r, r) for r in REPORT_REASONS]
