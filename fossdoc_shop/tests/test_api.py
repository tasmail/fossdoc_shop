import json

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.api import send_calculation
from fossdoc_shop.calculation import MARKER


def calculation():
	body = {
		"lang": "uk",
		"total": 100,
		"lines": [{"code": "a", "name": "A", "qty": 1, "unit": 100, "total": 100}],
	}
	return f"{MARKER}\n{json.dumps(body, ensure_ascii=False)}\n\nA: 100.00"


class TestSendCalculation(FrappeTestCase):
	def test_a_valid_calculation_becomes_an_escaped_communication_and_sends_nothing_by_itself(self):
		before = frappe.db.count("Email Queue")

		send_calculation("client@example.org", calculation())

		row = frappe.get_all(
			"Communication",
			filters={"sender": "client@example.org", "subject": MARKER},
			fields=["content", "sent_or_received"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(row.sent_or_received, "Received")
		self.assertIn("&quot;", row.content)  # the JSON is escaped, as the contact form stores it
		# only the Notification queues mail; the endpoint itself queues none
		queued = frappe.db.count("Email Queue") - before
		self.assertLessEqual(queued, 1)

	def test_a_bad_address_or_a_message_that_is_not_a_calculation_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			send_calculation("not-an-address", calculation())
		with self.assertRaises(frappe.ValidationError):
			send_calculation("client@example.org", "Hello")

	def test_the_notification_copies_the_address_of_the_settings(self):
		from fossdoc_shop.setup import NOTIFICATION, ensure_calculation_mail

		frappe.delete_doc("Notification", NOTIFICATION, force=True)
		ensure_calculation_mail()
		row = frappe.get_doc("Notification", NOTIFICATION).recipients[0]

		self.assertEqual(row.receiver_by_document_field, "sender")
		self.assertEqual(row.cc, "{{ brand().cc }}")  # read from the settings when the letter is sent
