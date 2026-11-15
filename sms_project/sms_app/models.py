from django.db import models


class Contact(models.Model):
    """A saved recipient, so users don't have to retype numbers."""

    name = models.CharField(max_length=80)
    phone_number = models.CharField(max_length=20, unique=True, help_text="E.164 format")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class SmsMessage(models.Model):
    """One sending attempt and its latest known status.

    Status values come from two sources:
    * Local states, set before the gateway accepts the request:
      ``pending`` (about to send), ``error`` (never reached the gateway: missing
      credentials, wrong password, network problem, phone offline) and
      ``rejected`` (the gateway refused the request).
    * The gateway's processing states: Pending -> Processed -> Sent -> Delivered,
      or Failed / Cancelled.

    Only ``delivered`` means the recipient's phone confirmed receipt.
    ``queued``/``processed``/``sent`` mean the message was *submitted*, not that it arrived.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ERROR = "error", "Not sent (error)"
        REJECTED = "rejected", "Rejected by gateway"
        QUEUED = "queued", "Queued on gateway"
        PROCESSED = "processed", "Sending from phone"
        SENT = "sent", "Sent to carrier"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    # Grouping used by the UI and dashboard.
    SUBMITTED_STATES = {"queued", "processed", "sent"}
    DELIVERED_STATES = {"delivered"}
    FAILED_STATES = {"error", "rejected", "failed", "canceled"}
    FINAL_STATES = DELIVERED_STATES | FAILED_STATES

    recipient = models.CharField(max_length=20)
    contact = models.ForeignKey(
        Contact, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_sid = models.CharField("gateway message ID", max_length=64, blank=True, db_index=True)
    num_segments = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=20, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.recipient} [{self.status}]"

    @property
    def category(self):
        """'delivered', 'submitted', 'failed' or 'pending' - drives badge colours."""
        if self.status in self.DELIVERED_STATES:
            return "delivered"
        if self.status in self.SUBMITTED_STATES:
            return "submitted"
        if self.status in self.FAILED_STATES:
            return "failed"
        return "pending"

    @property
    def is_final(self):
        return self.status in self.FINAL_STATES

    @property
    def can_refresh(self):
        return bool(self.provider_sid) and not self.is_final

    @property
    def status_explanation(self):
        explanations = {
            "pending": "The request has not been sent to the SMS gateway yet.",
            "error": "The message never reached the SMS gateway.",
            "rejected": "The SMS gateway refused the request, so nothing was sent.",
            "queued": "Submitted to the SMS gateway and waiting for the gateway phone. Delivery is not confirmed yet.",
            "processed": "The gateway phone is sending the message. Delivery is not confirmed yet.",
            "sent": "The mobile carrier accepted the message. Delivery has not been confirmed by the recipient's phone yet.",
            "delivered": "The recipient's phone confirmed it received the message.",
            "failed": "The gateway phone or the carrier could not send the message.",
            "canceled": "The message was canceled before it was sent.",
        }
        return explanations.get(self.status, "")

    @property
    def progress_steps(self):
        """(label, state) pairs for the progress tracker; state is 'done', 'fail' or ''."""
        s = self.status

        def step(done, failed=False):
            return "fail" if failed else ("done" if done else "")

        return [
            ("Sent to SMS gateway", step(s not in ("pending", "error"), s == "error")),
            ("Accepted by gateway", step(s not in ("pending", "error", "rejected"), s == "rejected")),
            ("Sent by phone to carrier", step(s in ("sent", "delivered"), s in ("failed", "canceled"))),
            ("Delivery confirmed", step(s == "delivered")),
        ]
