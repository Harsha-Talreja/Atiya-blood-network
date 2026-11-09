"""Say, for every request, where it is right now and why.

Meant for the question "why is this request not in the admin's Extra units or Timed out
tab?". It uses the same queries the admin panel uses, so the answer is the panel's answer.

    python manage.py check_requests
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.selectors import awaiting_extra_review, awaiting_timeout_review, open_requests, still_with_hospital
from blood_requests.visibility import max_units_per_request, wait_minutes


class Command(BaseCommand):
    help = "Show which admin tab each request is in, and why."

    def handle(self, *args, **options):
        extra = set(awaiting_extra_review().values_list("pk", flat=True))
        timed = set(awaiting_timeout_review().values_list("pk", flat=True))
        hospital = set(still_with_hospital().values_list("pk", flat=True))
        live = set(open_requests().values_list("pk", flat=True))
        now = timezone.now()
        self.stdout.write(f"Unit limit: {max_units_per_request()}   Hospital wait (minutes): {wait_minutes()}")
        self.stdout.write("")
        for req in BloodRequest.objects.select_related("requester", "hospital").order_by("-created_at"):
            age = int((now - req.created_at).total_seconds() // 60)
            if req.pk in extra:
                where, why = "ADMIN: Extra units", f"asks for {req.units_needed} units, over the limit"
            elif req.pk in timed:
                where, why = "ADMIN: Timed out", "hospital did not verify within its wait"
            elif req.pk in hospital:
                where, why = "Hospital only", f"still inside the hospital's wait ({age} min old)"
            elif req.pk in live:
                where, why = "Live for donors", "verified or released"
            elif req.status != "Pending":
                where, why = "Closed", f"status is {req.status}"
            elif req.expires_at and req.expires_at <= now:
                where, why = "Expired", "past its deadline"
            elif req.timeout_review != "none":
                where, why = "Decided by admin", f"timed-out decision: {req.timeout_review}"
            else:
                where, why = "Other", "blocked requester or rejected extra units"
            self.stdout.write(
                f"#{req.pk} {req.patient_name} | by {req.requester.username} | {req.units_needed} unit(s) "
                f"{req.urgency} | verified={req.is_verified} | {age} min old\n      -> {where} ({why})"
            )
