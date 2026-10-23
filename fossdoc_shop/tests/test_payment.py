from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop import overrides
from fossdoc_shop.payment import SUBJECT_MARK, payment_order
from fossdoc_shop.setup import (
	PAYMENT_NOTIFICATION,
	PAYMENT_PRINT_FORMAT,
	ensure_payment_mail,
	refresh_templates,
)
from fossdoc_shop.tests.seed import seed_settings

ORDER = {
	"doctype": "Sales Order",
	"name": "SAL-ORD-1",
	"transaction_date": "2026-10-23",
	"currency": "USD",
	"customer_name": "Acme <b>Co</b>",
	"address_display": "1 Main St<br>Kharkiv<br/><script>alert(1)</script>",
	"grand_total": 150,
	"items": [
		{"item_code": "FD-MOD-audit", "item_name": "Audit <i>X</i>", "qty": 1, "rate": 100, "amount": 100},
		{"item_code": "FD-SEAT", "item_name": "Seat", "qty": 5, "rate": 10, "amount": 50},
	],
}


def request(**values):
	return frappe._dict(
		{
			"doctype": "Payment Request",
			"name": "ACC-PRQ-1",
			"reference_doctype": "Sales Order",
			"reference_name": "SAL-ORD-1",
			"email_to": "client@example.org",
			"grand_total": 150,
			"payment_gateway": "Stripe-FossDoc",
			"modified": "2026-10-23 12:00:00",
			**values,
		}
	)


def with_the_order():
	"""frappe.get_doc that knows the sales order and gives everything else back to Frappe."""
	original = frappe.get_doc

	def get_doc(*args, **kwargs):
		if args and args[0] == "Sales Order":
			return frappe._dict(ORDER)
		return original(*args, **kwargs)

	return patch("frappe.get_doc", side_effect=get_doc)


class TestPaymentOrder(FrappeTestCase):
	def test_the_order_of_a_payment_request_is_read_with_its_lines_and_the_address_as_text(self):
		with with_the_order():
			data = payment_order(request())

		self.assertEqual(
			(data["name"], data["total"], data["paid"], data["gateway"]), ("SAL-ORD-1", 150, 150, "Stripe")
		)
		self.assertEqual([row["name"] for row in data["items"]], ["Audit <i>X</i>", "Seat"])
		self.assertEqual(data["address"][:2], ["1 Main St", "Kharkiv"])
		self.assertNotIn("<br", " ".join(data["address"]))

	def test_a_payment_of_anything_else_has_no_order(self):
		self.assertIsNone(payment_order(request(reference_doctype="Sales Invoice")))
		self.assertIsNone(payment_order(request(reference_name=None)))


class TestPaymentMail(FrappeTestCase):
	def setUp(self):
		seed_settings()
		frappe.delete_doc("Notification", PAYMENT_NOTIFICATION, force=True)
		ensure_payment_mail()

	def test_the_letter_is_created_once_for_a_payment_request_with_the_pdf_and_a_copy_to_sales(self):
		notification = frappe.get_doc("Notification", PAYMENT_NOTIFICATION)

		self.assertEqual(
			(notification.document_type, notification.event, notification.attach_print),
			("Payment Request", "Custom", 1),
		)
		self.assertEqual(notification.print_format, PAYMENT_PRINT_FORMAT)
		row = notification.recipients[0]
		self.assertEqual((row.receiver_by_document_field, row.cc), ("email_to", "{{ brand().cc }}"))
		self.assertEqual(
			frappe.db.get_value("Print Format", PAYMENT_PRINT_FORMAT, "doc_type"), "Payment Request"
		)

	def test_a_migration_keeps_the_edits_of_a_manager_and_refresh_puts_the_texts_back(self):
		edited = "{# fossdoc_shop #}<p>edited</p>"
		frappe.db.set_value("Notification", PAYMENT_NOTIFICATION, "message", edited)

		ensure_payment_mail()
		self.assertEqual(frappe.db.get_value("Notification", PAYMENT_NOTIFICATION, "message"), edited)

		refresh_templates()
		self.assertIn(
			"payment_order(doc)", frappe.db.get_value("Notification", PAYMENT_NOTIFICATION, "message")
		)

	def test_the_letter_shows_the_order_the_lines_the_total_and_a_link_to_the_order_and_escapes_the_text_of_a_customer(
		self,
	):
		message = frappe.db.get_value("Notification", PAYMENT_NOTIFICATION, "message")

		with with_the_order():
			html = frappe.render_template(message, {"doc": request()})

		self.assertIn("SAL-ORD-1", html)
		self.assertIn("USD 150.00", html)
		self.assertIn("5 × 10.00", html)
		self.assertIn('href="https://shop.test.example/orders/SAL-ORD-1"', html)
		self.assertIn("Acme &lt;b&gt;Co&lt;/b&gt;", html)
		self.assertNotIn("<script>", html)
		self.assertNotIn("Audit <i>X</i>", html)

	def test_the_pdf_is_a_confirmation_with_the_payer_the_lines_and_the_stamp(self):
		doc = frappe.get_doc(
			{
				"doctype": "Payment Request",
				"name": "ACC-PRQ-1",
				**{k: v for k, v in request().items() if k not in ("doctype", "name")},
			}
		)
		doc.name = "ACC-PRQ-1"

		with with_the_order():
			html = frappe.get_print(
				"Payment Request", doc=doc, print_format=PAYMENT_PRINT_FORMAT, as_pdf=False
			)
			pdf = frappe.get_print("Payment Request", doc=doc, print_format=PAYMENT_PRINT_FORMAT, as_pdf=True)

		for part in (
			"Підтвердження оплати",
			"СПЛАЧЕНО",
			"SAL-ORD-1",
			"Kharkiv",
			"Test Seller Co",
			"sales@test.example",
		):
			self.assertIn(part, html)
		self.assertNotIn("<script>alert", html)
		self.assertTrue(pdf.startswith(b"%PDF"))


class TestSendPaymentLetter(FrappeTestCase):
	def test_the_letter_is_sent_for_an_order_with_an_address_of_the_payer(self):
		with patch("frappe.get_doc") as get_doc:
			overrides.send_payment_letter(request())

		get_doc.assert_called_once_with("Notification", PAYMENT_NOTIFICATION)
		get_doc.return_value.send.assert_called_once()

	def test_nothing_is_sent_for_another_document_or_without_an_address(self):
		with patch("frappe.get_doc") as get_doc:
			overrides.send_payment_letter(request(reference_doctype="Sales Invoice"))
			overrides.send_payment_letter(request(email_to=None))

		get_doc.assert_not_called()

	def test_a_failure_of_the_letter_is_logged_and_never_undoes_the_payment(self):
		with patch("frappe.get_doc") as get_doc, patch("frappe.log_error") as log:
			get_doc.return_value.send.side_effect = RuntimeError("smtp down")
			overrides.send_payment_letter(request())

		log.assert_called_once()

	def test_the_payment_request_of_the_shop_sends_the_letter_after_it_books_the_payment(self):
		order = []
		paid = overrides.PaymentRequest.__new__(overrides.PaymentRequest)
		with (
			patch.object(
				overrides.PaymentRequest.__mro__[1],
				"set_as_paid",
				lambda self: order.append("booked") or "pe",
			),
			patch("fossdoc_shop.overrides.send_payment_letter", lambda req: order.append("letter")),
		):
			result = paid.set_as_paid()

		self.assertEqual((result, order), ("pe", ["booked", "letter"]))

	def test_the_reply_to_of_the_letter_is_sales(self):
		seed_settings()
		doc = frappe._dict(
			reference_doctype="Communication",
			message=f"From: a@example.org\nTo: b@example.org\nSubject: {SUBJECT_MARK} SAL-1 отримано\nReply-To: noreply@example.org\n\nbody\n",
		)

		overrides.set_reply_to(doc)

		self.assertIn("sales@test.example", doc.message)

	def test_the_subject_names_the_order(self):
		subject = frappe.db.get_value("Notification", PAYMENT_NOTIFICATION, "subject")

		self.assertEqual(
			frappe.render_template(subject, {"doc": request()}), f"{SUBJECT_MARK} SAL-ORD-1 отримано"
		)
