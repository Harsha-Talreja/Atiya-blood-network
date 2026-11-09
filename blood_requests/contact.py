"""Call and WhatsApp links for the requester.

When a donor offers to help, the person who posted the request needs to reach
them quickly. Two small buttons do that without any paid service:

* a ``tel:`` link, which opens the phone's dialler, and
* a ``wa.me`` link, which opens a WhatsApp chat with the message already
  typed. The requester still presses Send; WhatsApp does not let a website send
  a message for someone, and this keeps it that way.

Only the numbers donors agreed to share (``phone_consent``) ever get here; the
view decides that. This module just turns a number and a request into links.
"""
import re
from urllib.parse import quote

# Pakistani mobiles are stored as 03XXXXXXXXX or +923XXXXXXXXX (see
# core.validators.phone_validator). wa.me wants the number with the country
# code and nothing else: 923XXXXXXXXX.
_PK_LOCAL = re.compile(r"^03\d{9}$")
_PK_INTERNATIONAL = re.compile(r"^\+?92(3\d{9})$")


def international_digits(phone):
    """'03001234567' or '+923001234567' -> '923001234567'; anything else -> ''."""
    cleaned = re.sub(r"[\s\-()]", "", phone or "")
    if _PK_LOCAL.match(cleaned):
        return "92" + cleaned[1:]
    match = _PK_INTERNATIONAL.match(cleaned)
    if match:
        return "92" + match.group(1)
    return ""


def tel_url(phone):
    digits = international_digits(phone)
    return f"tel:+{digits}" if digits else ""


def _requester_name(blood_request):
    user = blood_request.requester
    return (user.get_full_name() or user.get_username()).strip()


def message_text(blood_request, donor_name):
    """What the WhatsApp chat opens with, in plain words the donor can act on."""
    place = ", ".join(part for part in (blood_request.location.area, blood_request.location.city) if part)
    hospital = blood_request.hospital.name
    units = f"{blood_request.units_needed} unit{'s' if blood_request.units_needed != 1 else ''}"
    me = _requester_name(blood_request)
    first = (donor_name or "").split(" ")[0]

    if blood_request.fulfilled_at is not None:
        return (
            f"Assalam o Alaikum {first}, thank you for offering to help. "
            f"The blood for {blood_request.patient_name} at {hospital} has been arranged. "
            f"JazakAllah! - {me}, ATIYA"
        )
    return (
        f"Assalam o Alaikum {first}, I'm {me} from ATIYA. "
        f"{blood_request.blood_type} blood ({units}) is needed for {blood_request.patient_name} "
        f"at {hospital}, {place}. Please call me on {blood_request.contact_phone}. "
        f"Thank you for offering to help!"
    )


def whatsapp_url(phone, text):
    digits = international_digits(phone)
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(text, safe='')}"


def contact_links(blood_request, donor):
    """The two links for one donor, or empty strings when there is nothing to open."""
    if not donor.phone_consent:
        return {"tel": "", "wa": ""}
    return {
        "tel": tel_url(donor.phone),
        "wa": whatsapp_url(donor.phone, message_text(blood_request, donor.full_name)),
    }
