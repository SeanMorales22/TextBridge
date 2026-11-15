import phonenumbers
from django import forms
from django.conf import settings

from .models import Contact


def normalize_phone_number(raw: str) -> str:
    """Validate a phone number and return it in E.164 format (e.g. +639171234567).

    Accepts international format (+63 917 123 4567) or local format for the
    configured default region (0917 123 4567 when SMS_DEFAULT_REGION=PH).
    Raises ``forms.ValidationError`` with a readable message when invalid.
    """
    value = (raw or "").strip()
    if not value:
        raise forms.ValidationError("Please enter the recipient's phone number.")

    allowed = set("0123456789+-() .")
    if any(ch not in allowed for ch in value):
        raise forms.ValidationError(
            "Phone numbers may only contain digits, spaces, dashes, brackets and a leading +."
        )

    try:
        parsed = phonenumbers.parse(value, settings.SMS_DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        raise forms.ValidationError(
            "That doesn't look like a phone number. Use international format, e.g. +639171234567."
        )

    if not phonenumbers.is_valid_number(parsed):
        raise forms.ValidationError(
            "This phone number is not valid. Check the country code and number of digits "
            "(example: +639171234567)."
        )

    number_type = phonenumbers.number_type(parsed)
    if number_type == phonenumbers.PhoneNumberType.FIXED_LINE:
        raise forms.ValidationError("This looks like a landline number, which cannot receive SMS.")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class SmsForm(forms.Form):
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        empty_label="- Type a number below or pick a saved contact -",
        label="Saved contact",
    )
    recipient = forms.CharField(
        label="Recipient phone number",
        max_length=30,
        required=False,  # emptiness is checked in clean() so the contact can fill it
        widget=forms.TextInput(
            attrs={
                "placeholder": "+639171234567",
                "autocomplete": "tel",
                "inputmode": "tel",
            }
        ),
        help_text="International format with country code, e.g. +639171234567.",
    )
    message = forms.CharField(
        label="Message",
        max_length=settings.SMS_MAX_LENGTH,
        strip=True,
        error_messages={
            "required": "Please type a message before sending.",
            "max_length": "Messages can be at most %(limit_value)d characters (you typed %(show_value)d).",
        },
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": "Type your message here...",
                "maxlength": settings.SMS_MAX_LENGTH,
            }
        ),
    )

    def clean(self):
        cleaned = super().clean()
        contact = cleaned.get("contact")
        recipient = cleaned.get("recipient", "")

        # An explicitly typed number wins; otherwise fall back to the saved contact.
        if not recipient and contact:
            recipient = contact.phone_number

        if "recipient" not in self.errors:
            try:
                cleaned["recipient"] = normalize_phone_number(recipient)
            except forms.ValidationError as exc:
                self.add_error("recipient", exc)
        return cleaned


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["name", "phone_number"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Juan Dela Cruz"}),
            "phone_number": forms.TextInput(
                attrs={"placeholder": "+639171234567", "inputmode": "tel"}
            ),
        }
        error_messages = {
            "name": {"required": "Please enter a name."},
            "phone_number": {"required": "Please enter a phone number."},
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Please enter a name.")
        return name

    def clean_phone_number(self):
        number = normalize_phone_number(self.cleaned_data.get("phone_number"))
        if Contact.objects.filter(phone_number=number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("A contact with this phone number already exists.")
        return number
