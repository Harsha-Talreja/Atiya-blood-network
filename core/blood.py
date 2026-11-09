"""Blood-type compatibility. Pure Python: NO Django imports, so it is trivial to test.

HOW COMPATIBILITY WORKS (for Q&A)
---------------------------------
Red blood cells can carry two ABO antigens (A and B) and one Rh antigen (D, the "+").
  A   -> has antigen A          B   -> has antigen B
  AB  -> has A and B            O   -> has neither
  "+" -> has Rh antigen         "-" -> has no Rh antigen
A recipient's immune system attacks any antigen its own cells do NOT carry.
So the rule is:

    A donor is compatible  <=>  every antigen on the donor's cells
                                is also present on the recipient's cells.

Consequences:
  * O-  has no antigens at all -> a subset of everyone's -> universal DONOR.
  * AB+ has every antigen      -> can receive from everyone -> universal RECIPIENT.
  * O-  has none, so it can only receive from O- (any other type adds an antigen).
This table is for red blood cells (what a whole-blood donation is mostly used
for in an emergency). Plasma and platelets follow different rules.
"""

# recipient -> list of donor types that recipient can safely receive from
COMPATIBLE_DONORS = {
    "A+": ["A+", "A-", "O+", "O-"],
    "A-": ["A-", "O-"],
    "B+": ["B+", "B-", "O+", "O-"],
    "B-": ["B-", "O-"],
    "AB+": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "AB-": ["A-", "B-", "AB-", "O-"],
    "O+": ["O+", "O-"],
    "O-": ["O-"],
}


def compatible_donor_types(recipient_type):
    """Return the donor blood types that can give to `recipient_type`."""
    try:
        return list(COMPATIBLE_DONORS[recipient_type])  # copy: callers can't alter the table
    except KeyError:
        raise ValueError(f"Unknown blood type: {recipient_type!r}") from None


def can_donate(donor_type, recipient_type):
    """True if a donor of `donor_type` can give to a recipient of `recipient_type`."""
    if donor_type not in COMPATIBLE_DONORS:
        raise ValueError(f"Unknown blood type: {donor_type!r}")
    return donor_type in compatible_donor_types(recipient_type)


def compatible_recipient_types(donor_type):
    """The recipient blood types a donor of `donor_type` can give to.

    This is the same table read in the other direction. The donor dashboard uses it
    to find open requests the donor could help with.
    """
    if donor_type not in COMPATIBLE_DONORS:
        raise ValueError(f"Unknown blood type: {donor_type!r}")
    return [recipient for recipient, donors in COMPATIBLE_DONORS.items() if donor_type in donors]
