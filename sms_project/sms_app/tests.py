"""Automated tests for the SMS application.

The SMS gateway is never contacted: ``requests.post`` / ``requests.get`` are
replaced with mocks, so the tests are free, fast, and safe to run without
credentials, a phone, or internet access. They cover every test case listed
in Step 6 of the assignment plus the additional features.

Run with:  python manage.py test sms_app -v 2
"""

import logging
from unittest import mock

import requests
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import normalize_phone_number
from .models import Contact, SmsMessage

GATEWAY_URL = "https://api.sms-gate.app/3rdparty/v1"
FAKE_USER = "TESTUSER123"
FAKE_PASSWORD = "test-password-not-real"
VALID_NUMBER = "+639171234567"
MESSAGE_ID = "zXDYfTmTVf3iMd16zzdBj"

GATEWAY_TEST_SETTINGS = dict(
    SMSGATE_URL=GATEWAY_URL,
    SMSGATE_USERNAME=FAKE_USER,
    SMSGATE_PASSWORD=FAKE_PASSWORD,
    SMSGATE_SIM_NUMBER=None,
    SMSGATE_TIMEOUT=15,
    SMS_DEFAULT_REGION="PH",
)


def setUpModule():
    # Error paths log warnings by design; keep the test output readable.
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


def gateway_response(status_code=202, data=None, state="Pending", error=None):
    """Build a fake ``requests.Response`` like the gateway returns."""
    if data is None:
        recipient = {"phoneNumber": VALID_NUMBER, "state": state}
        if error:
            recipient["error"] = error
        data = {"id": MESSAGE_ID, "state": state, "recipients": [recipient]}
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = data
    return response


@override_settings(**GATEWAY_TEST_SETTINGS)
class SmsTestCase(TestCase):
    def setUp(self):
        post = mock.patch("sms_app.services.requests.post", return_value=gateway_response())
        get = mock.patch("sms_app.services.requests.get")
        self.post = post.start()
        self.get = get.start()
        self.addCleanup(post.stop)
        self.addCleanup(get.stop)

    def post_sms(self, recipient=VALID_NUMBER, message="Hello from IT 120!", **extra):
        data = {"recipient": recipient, "message": message, **extra}
        return self.client.post(reverse("sms_app:compose"), data, follow=True)

    def assertNoSecrets(self, response):
        content = response.content.decode()
        self.assertNotIn(FAKE_PASSWORD, content)
        self.assertNotIn(FAKE_USER, content)


class ComposeFormTests(SmsTestCase):
    def test_form_page_shows_fields_and_csrf_token(self):
        response = self.client.get(reverse("sms_app:compose"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="recipient"')
        self.assertContains(response, 'name="message"')
        self.assertContains(response, "Send SMS")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_post_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("sms_app:compose"), {"recipient": VALID_NUMBER, "message": "hi"})
        self.assertEqual(response.status_code, 403)
        self.post.assert_not_called()


class ValidationTests(SmsTestCase):
    """Step 6: empty phone, empty message, invalid phone number."""

    def test_empty_phone_number_is_rejected(self):
        response = self.post_sms(recipient="")
        self.assertContains(response, "Please enter the recipient&#x27;s phone number.")
        self.assertEqual(SmsMessage.objects.count(), 0)
        self.post.assert_not_called()

    def test_empty_message_is_rejected(self):
        response = self.post_sms(message="")
        self.assertContains(response, "Please type a message before sending.")
        self.assertEqual(SmsMessage.objects.count(), 0)
        self.post.assert_not_called()

    def test_whitespace_only_message_is_rejected(self):
        response = self.post_sms(message="    \n  ")
        self.assertContains(response, "Please type a message before sending.")
        self.post.assert_not_called()

    def test_invalid_phone_numbers_are_rejected(self):
        for bad in ["abc", "12345", "+63 917", "+999123456789", "0917-ABC-4567", "+1 555"]:
            with self.subTest(number=bad):
                response = self.post_sms(recipient=bad)
                self.assertContains(response, "has-error")
        self.assertEqual(SmsMessage.objects.count(), 0)
        self.post.assert_not_called()

    def test_landline_is_rejected(self):
        response = self.post_sms(recipient="+63 2 8123 4567")
        self.assertContains(response, "landline")
        self.post.assert_not_called()

    def test_message_too_long_is_rejected(self):
        response = self.post_sms(message="x" * 1601)
        self.assertContains(response, "at most 1600 characters")
        self.post.assert_not_called()

    def test_local_format_is_normalized_to_e164(self):
        self.assertEqual(normalize_phone_number("0917 123 4567"), VALID_NUMBER)
        self.assertEqual(normalize_phone_number("+63 (917) 123-4567"), VALID_NUMBER)
        self.assertEqual(normalize_phone_number("+1 415 555 2671"), "+14155552671")


class SendingTests(SmsTestCase):
    """Step 6: valid input and successful provider response."""

    def test_valid_input_submits_to_gateway(self):
        response = self.post_sms(recipient="0917 123 4567", message="Hello!")
        self.post.assert_called_once_with(
            GATEWAY_URL + "/messages",
            json={
                "textMessage": {"text": "Hello!"},
                "phoneNumbers": [VALID_NUMBER],
                "withDeliveryReport": True,
            },
            auth=(FAKE_USER, FAKE_PASSWORD),
            timeout=15,
        )
        sms = SmsMessage.objects.get()
        self.assertEqual(sms.status, "queued")
        self.assertEqual(sms.recipient, VALID_NUMBER)
        self.assertEqual(sms.provider_sid, MESSAGE_ID)
        self.assertRedirects(response, reverse("sms_app:message_detail", args=[sms.pk]))

    def test_success_does_not_claim_delivery(self):
        response = self.post_sms()
        self.assertContains(response, "Message submitted to the SMS gateway")
        self.assertContains(response, "Delivery is not confirmed yet")
        self.assertNotContains(response, "badge-delivered")

    def test_sim_number_is_sent_when_configured(self):
        with self.settings(SMSGATE_SIM_NUMBER=2):
            self.post_sms()
        self.assertEqual(self.post.call_args.kwargs["json"]["simNumber"], 2)

    def test_local_mode_url(self):
        with self.settings(SMSGATE_URL="http://192.168.1.50:8080"):
            self.post_sms()
        self.assertEqual(self.post.call_args.args[0], "http://192.168.1.50:8080/messages")

    def test_send_using_saved_contact_only(self):
        contact = Contact.objects.create(name="Ana", phone_number=VALID_NUMBER)
        self.client.post(reverse("sms_app:compose"), {"contact": contact.pk, "recipient": "", "message": "Hi Ana"})
        self.post.assert_called_once()
        self.assertEqual(SmsMessage.objects.get().contact, contact)

    def test_refreshing_result_page_does_not_resend(self):
        response = self.post_sms()
        self.client.get(response.request["PATH_INFO"])
        self.assertEqual(self.post.call_count, 1)


class ErrorHandlingTests(SmsTestCase):
    """Step 6: credentials, network and provider errors."""

    def test_missing_credentials(self):
        with self.settings(SMSGATE_USERNAME="", SMSGATE_PASSWORD=""):
            response = self.post_sms()
        self.assertContains(response, "The SMS gateway is not configured")
        self.assertEqual(SmsMessage.objects.get().status, "error")
        self.post.assert_not_called()

    def test_incorrect_credentials_do_not_leak_secrets(self):
        self.post.return_value = gateway_response(401, {"message": "Unauthorized"})
        response = self.post_sms()
        self.assertContains(response, "rejected the username or password")
        self.assertNoSecrets(response)
        sms = SmsMessage.objects.get()
        self.assertEqual(sms.status, "error")
        self.assertEqual(sms.error_code, "HTTP 401")
        self.assertNotIn(FAKE_PASSWORD, sms.error_message)

    def test_gateway_error_text_containing_secret_is_hidden(self):
        self.post.return_value = gateway_response(400, {"message": f"bad user {FAKE_USER}"})
        response = self.post_sms()
        self.assertNoSecrets(response)
        self.assertContains(response, "The SMS gateway rejected the request.")

    def test_network_error(self):
        self.post.side_effect = requests.exceptions.ConnectionError("DNS failure")
        response = self.post_sms()
        self.assertContains(response, "Could not connect to the SMS gateway")
        self.assertEqual(SmsMessage.objects.get().error_code, "NETWORK")

    def test_timeout(self):
        self.post.side_effect = requests.exceptions.ReadTimeout()
        response = self.post_sms()
        self.assertContains(response, "did not respond in time")
        self.assertEqual(SmsMessage.objects.get().error_code, "TIMEOUT")

    def test_phone_offline_or_queue_full(self):
        self.post.return_value = gateway_response(503, {"message": "queue limit"})
        response = self.post_sms()
        self.assertContains(response, "no phone is online")
        self.assertEqual(SmsMessage.objects.get().status, "error")

    def test_gateway_server_error(self):
        self.post.return_value = gateway_response(500, {"message": "oops"})
        response = self.post_sms()
        self.assertContains(response, "having problems right now")
        self.assertEqual(SmsMessage.objects.get().status, "error")

    def test_gateway_rejects_request(self):
        self.post.return_value = gateway_response(400, {"message": "invalid phone number"})
        response = self.post_sms()
        self.assertContains(response, "The SMS gateway rejected the request: invalid phone number")
        self.assertEqual(SmsMessage.objects.get().status, "rejected")

    def test_immediately_failed_message(self):
        self.post.return_value = gateway_response(state="Failed", error="Invalid number")
        response = self.post_sms()
        self.assertContains(response, "could not send the message: Invalid number")
        sms = SmsMessage.objects.get()
        self.assertEqual(sms.status, "failed")
        self.assertEqual(sms.category, "failed")

    def test_non_json_success_response_is_handled(self):
        response_mock = gateway_response()
        response_mock.json.side_effect = ValueError("not json")
        self.post.return_value = response_mock
        self.post_sms()
        self.assertEqual(SmsMessage.objects.get().status, "queued")

    def test_unexpected_exception_is_handled(self):
        self.post.side_effect = RuntimeError("boom")
        response = self.post_sms()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unexpected error")


class StatusTrackingTests(SmsTestCase):
    def setUp(self):
        super().setUp()
        self.sms = SmsMessage.objects.create(
            recipient=VALID_NUMBER, body="hi", status="queued", provider_sid=MESSAGE_ID
        )
        self.refresh_url = reverse("sms_app:refresh_status", args=[self.sms.pk])

    def test_refresh_updates_to_delivered(self):
        self.get.return_value = gateway_response(200, state="Delivered")
        response = self.client.post(self.refresh_url, follow=True)
        self.get.assert_called_once_with(
            f"{GATEWAY_URL}/messages/{MESSAGE_ID}", auth=(FAKE_USER, FAKE_PASSWORD), timeout=15
        )
        self.sms.refresh_from_db()
        self.assertEqual(self.sms.status, "delivered")
        self.assertContains(response, "Status updated: Delivered.")

    def test_all_gateway_states_are_mapped(self):
        expected = {
            "Pending": "queued", "Processed": "processed", "Sent": "sent",
            "Delivered": "delivered", "Failed": "failed", "Cancelled": "canceled",
        }
        for gateway_state, our_status in expected.items():
            with self.subTest(state=gateway_state):
                self.sms.status = "queued"
                self.sms.save()
                self.get.return_value = gateway_response(200, state=gateway_state)
                self.client.post(self.refresh_url)
                self.sms.refresh_from_db()
                self.assertEqual(self.sms.status, our_status)

    def test_refresh_records_failure_reason(self):
        self.get.return_value = gateway_response(200, state="Failed", error="RESULT_ERROR_NO_SERVICE")
        self.client.post(self.refresh_url)
        self.sms.refresh_from_db()
        self.assertEqual(self.sms.status, "failed")
        self.assertIn("RESULT_ERROR_NO_SERVICE", self.sms.error_message)

    def test_failed_refresh_keeps_previous_status(self):
        self.get.side_effect = requests.exceptions.ConnectionError()
        response = self.client.post(self.refresh_url, follow=True)
        self.sms.refresh_from_db()
        self.assertEqual(self.sms.status, "queued")
        self.assertContains(response, "Could not refresh the status")

    def test_refresh_http_error_keeps_previous_status(self):
        self.get.return_value = gateway_response(401, {"message": "Unauthorized"})
        self.client.post(self.refresh_url)
        self.sms.refresh_from_db()
        self.assertEqual(self.sms.status, "queued")

    def test_refresh_requires_post(self):
        response = self.client.get(self.refresh_url)
        self.assertEqual(response.status_code, 405)

    def test_auto_refresh_json_endpoint(self):
        self.get.return_value = gateway_response(200, state="Sent")
        response = self.client.post(self.refresh_url + "?format=json")
        self.assertEqual(
            response.json(),
            {"ok": True, "status": "sent", "changed": True, "final": False, "message": ""},
        )

    def test_auto_refresh_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(self.refresh_url + "?format=json")
        self.assertEqual(response.status_code, 403)
        self.get.assert_not_called()

    def test_detail_page_polls_only_while_not_final(self):
        response = self.client.get(reverse("sms_app:message_detail", args=[self.sms.pk]))
        self.assertContains(response, "status_poll.js")
        self.sms.status = "delivered"
        self.sms.save()
        response = self.client.get(reverse("sms_app:message_detail", args=[self.sms.pk]))
        self.assertNotContains(response, "status_poll.js")


class HistoryAndContactsTests(SmsTestCase):
    def test_history_dashboard_counts_and_filters(self):
        SmsMessage.objects.create(recipient=VALID_NUMBER, body="a", status="delivered")
        SmsMessage.objects.create(recipient=VALID_NUMBER, body="b", status="queued")
        SmsMessage.objects.create(recipient=VALID_NUMBER, body="c", status="rejected")
        response = self.client.get(reverse("sms_app:history"))
        self.assertEqual(response.context["stats"], {"total": 3, "delivered": 1, "submitted": 1, "failed": 1})
        response = self.client.get(reverse("sms_app:history"), {"category": "failed"})
        self.assertEqual([m.body for m in response.context["page"].object_list], ["c"])

    def test_history_search(self):
        SmsMessage.objects.create(recipient=VALID_NUMBER, body="meeting at 5pm", status="queued")
        SmsMessage.objects.create(recipient=VALID_NUMBER, body="lunch", status="queued")
        response = self.client.get(reverse("sms_app:history"), {"q": "meeting"})
        self.assertEqual(len(response.context["page"].object_list), 1)

    def test_add_contact_normalizes_number(self):
        self.client.post(reverse("sms_app:contacts"), {"name": "Ben", "phone_number": "0917 123 4567"})
        self.assertEqual(Contact.objects.get().phone_number, VALID_NUMBER)

    def test_duplicate_contact_is_rejected(self):
        Contact.objects.create(name="Ana", phone_number=VALID_NUMBER)
        response = self.client.post(reverse("sms_app:contacts"), {"name": "Ana 2", "phone_number": "09171234567"})
        self.assertContains(response, "already exists")
        self.assertEqual(Contact.objects.count(), 1)

    def test_invalid_contact_is_rejected(self):
        response = self.client.post(reverse("sms_app:contacts"), {"name": " ", "phone_number": "123"})
        self.assertContains(response, "Please enter a name.")
        self.assertEqual(Contact.objects.count(), 0)

    def test_delete_contact_keeps_history(self):
        contact = Contact.objects.create(name="Ana", phone_number=VALID_NUMBER)
        sms = SmsMessage.objects.create(recipient=VALID_NUMBER, body="x", contact=contact)
        self.client.post(reverse("sms_app:delete_contact", args=[contact.pk]))
        sms.refresh_from_db()
        self.assertIsNone(sms.contact)
        self.assertEqual(Contact.objects.count(), 0)

    def test_compose_prefills_contact(self):
        contact = Contact.objects.create(name="Ana", phone_number=VALID_NUMBER)
        response = self.client.get(reverse("sms_app:compose"), {"contact": contact.pk})
        self.assertContains(response, f'value="{VALID_NUMBER}"')
