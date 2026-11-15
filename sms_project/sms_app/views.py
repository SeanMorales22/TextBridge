from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .forms import ContactForm, SmsForm
from .models import Contact, SmsMessage


@require_http_methods(["GET", "POST"])
def compose(request):
    """Show the SMS form (GET) or validate and send it (POST)."""
    if request.method == "POST":
        form = SmsForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data["recipient"]
            body = form.cleaned_data["message"]
            contact = form.cleaned_data.get("contact")
            if not contact or contact.phone_number != recipient:
                contact = Contact.objects.filter(phone_number=recipient).first()

            # Record the attempt first so it appears in history even if sending fails.
            sms = SmsMessage.objects.create(recipient=recipient, body=body, contact=contact)
            result = services.send_sms(recipient, body)

            sms.status = result.status
            sms.provider_sid = result.sid
            sms.num_segments = result.num_segments
            sms.error_code = result.error_code
            sms.error_message = "" if result.ok else result.user_message[:300]
            sms.save()

            if result.ok:
                messages.success(request, result.user_message)
            else:
                messages.error(request, result.user_message)
            # Post/Redirect/Get: refreshing the result page never re-sends the SMS.
            return redirect("sms_app:message_detail", pk=sms.pk)

        messages.error(request, "Please fix the highlighted fields and try again.")
    else:
        initial = {}
        contact_id = request.GET.get("contact")
        if contact_id and contact_id.isdigit():
            contact = Contact.objects.filter(pk=contact_id).first()
            if contact:
                initial = {"contact": contact, "recipient": contact.phone_number}
        form = SmsForm(initial=initial)

    recent = SmsMessage.objects.all()[:5]
    return render(
        request,
        "sms_app/compose.html",
        {"form": form, "recent": recent, "max_length": settings.SMS_MAX_LENGTH},
    )


def history(request):
    """Dashboard of previous sending attempts with stats, filter and search."""
    qs = SmsMessage.objects.select_related("contact")

    stats = qs.aggregate(
        total=Count("id"),
        delivered=Count("id", filter=Q(status__in=SmsMessage.DELIVERED_STATES)),
        submitted=Count("id", filter=Q(status__in=SmsMessage.SUBMITTED_STATES)),
        failed=Count("id", filter=Q(status__in=SmsMessage.FAILED_STATES)),
    )

    category = request.GET.get("category", "")
    groups = {
        "delivered": SmsMessage.DELIVERED_STATES,
        "submitted": SmsMessage.SUBMITTED_STATES,
        "failed": SmsMessage.FAILED_STATES,
    }
    if category in groups:
        qs = qs.filter(status__in=groups[category])
    else:
        category = ""

    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(recipient__icontains=query) | Q(body__icontains=query) | Q(contact__name__icontains=query)
        )

    page = Paginator(qs, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "sms_app/history.html",
        {"page": page, "stats": stats, "category": category, "query": query},
    )


def message_detail(request, pk):
    sms = get_object_or_404(SmsMessage.objects.select_related("contact"), pk=pk)
    return render(request, "sms_app/message_detail.html", {"sms": sms})


@require_POST
def refresh_status(request, pk):
    """Ask the gateway for the latest delivery status of one message.

    Called by the "Refresh delivery status" button (normal form POST) and by the
    detail page's automatic polling (fetch POST with ?format=json).
    """
    sms = get_object_or_404(SmsMessage, pk=pk)
    wants_json = request.GET.get("format") == "json"
    old_status = sms.status

    if not sms.provider_sid:
        text = "This message was never accepted by the gateway, so it has no status to check."
        if wants_json:
            return JsonResponse({"ok": False, "status": sms.status, "changed": False, "message": text})
        messages.warning(request, text)
        return redirect("sms_app:message_detail", pk=pk)

    result = services.fetch_status(sms.provider_sid)
    if result.ok:
        if result.status in SmsMessage.Status.values:
            sms.status = result.status
        if result.error_code:
            sms.error_code = result.error_code
            sms.error_message = result.user_message[:300]
        sms.save()

    if wants_json:
        return JsonResponse(
            {
                "ok": result.ok,
                "status": sms.status,
                "changed": sms.status != old_status,
                "final": sms.is_final,
                "message": "" if result.ok else result.user_message,
            }
        )

    if result.ok:
        messages.info(request, f"Status updated: {sms.get_status_display()}.")
    else:
        messages.error(request, "Could not refresh the status: " + result.user_message)
    return redirect("sms_app:message_detail", pk=pk)


@require_http_methods(["GET", "POST"])
def contacts(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save()
            messages.success(request, f"Saved contact {contact.name}.")
            return redirect("sms_app:contacts")
        messages.error(request, "Please fix the highlighted fields and try again.")
    else:
        form = ContactForm()
    contact_list = Contact.objects.annotate(message_count=Count("messages"))
    return render(request, "sms_app/contacts.html", {"form": form, "contacts": contact_list})


@require_POST
def delete_contact(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    name = contact.name
    contact.delete()  # message history is kept (contact is set to NULL)
    messages.success(request, f"Deleted contact {name}.")
    return redirect("sms_app:contacts")
