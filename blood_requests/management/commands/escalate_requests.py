"""Tell the admins about requests whose hospital has missed its deadline.

The requests are already in the admin's queue without this; the command only makes
the notification arrive on time even when nobody has the site open.

    python manage.py escalate_requests              # once
    python manage.py escalate_requests --every 60   # keep running, once a minute
"""
import time

from django.core.management.base import BaseCommand

from blood_requests.services import escalate_overdue_requests


class Command(BaseCommand):
    help = "Notify admins about requests whose hospital missed its deadline."

    def add_arguments(self, parser):
        parser.add_argument("--every", type=int, default=0, metavar="SECONDS",
                            help="Repeat forever, waiting this many seconds between runs (Ctrl+C to stop).")

    def handle(self, *args, **options):
        every = options["every"]
        while True:
            count = escalate_overdue_requests()
            self.stdout.write(f"Escalated {count} request(s).")
            if every <= 0:
                return
            try:
                time.sleep(every)
            except KeyboardInterrupt:
                self.stdout.write("Stopped.")
                return
