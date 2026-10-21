import json

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.calculation import MARKER
from fossdoc_shop.setup import NOTIFICATION, PRINT_FORMAT, ensure_calculation_mail


def communication(content):
	return frappe.get_doc({"doctype": "Communication", "content": content, "sender": "client@example.com"})


class TestCalculationMail(FrappeTestCase):
	def setUp(self):
		ensure_calculation_mail()

	def test_the_notification_is_created_once_and_refreshed_in_place(self):
		frappe.db.set_value("Notification", NOTIFICATION, "message", "old text")

		ensure_calculation_mail()
		ensure_calculation_mail()

		self.assertEqual(frappe.db.count("Notification", {"name": NOTIFICATION}), 1)
		self.assertIn("FossDoc", frappe.db.get_value("Notification", NOTIFICATION, "message"))

	def test_the_notification_mails_the_sender_of_a_calculation_only(self):
		doc = frappe.get_doc("Notification", NOTIFICATION)

		self.assertEqual(doc.document_type, "Communication")
		self.assertEqual(doc.event, "New")
		self.assertEqual(doc.recipients[0].receiver_by_document_field, "sender")
		self.assertTrue(frappe.safe_eval(doc.condition, None, {"doc": communication(MARKER + "\n{}")}))
		self.assertFalse(frappe.safe_eval(doc.condition, None, {"doc": communication("Hello")}))

	def test_the_letter_shows_the_lines_and_the_total(self):
		body = json.dumps(
			{
				"lang": "uk",
				"perMonth": True,
				"total": 450,
				"lines": [{"code": "seat", "name": "Клієнтських місць", "qty": 9, "unit": 50, "total": 450}],
			},
			ensure_ascii=False,
		)
		message = frappe.db.get_value("Notification", NOTIFICATION, "message")

		html = frappe.render_template(message, {"doc": communication(f"{MARKER}\n{body}")})

		self.assertIn("Клієнтських місць", html)
		self.assertIn("9 × 50.00", html)
		self.assertIn("$ 450.00", html)
		self.assertIn("щомісяця", html)

	def test_a_message_that_is_not_a_calculation_gets_a_plain_answer_and_no_html_from_the_guest(self):
		message = frappe.db.get_value("Notification", NOTIFICATION, "message")
		content = MARKER + "\n" + json.dumps({"lines": [{"code": "x", "name": "<script>alert(1)</script>"}]})

		html = frappe.render_template(message, {"doc": communication(content)})

		self.assertNotIn("<script>", html)


class TestOffer(FrappeTestCase):
	def setUp(self):
		ensure_calculation_mail()
		self.content = (
			MARKER
			+ "\n"
			+ json.dumps(
				{
					"lang": "uk",
					"total": 150,
					"lines": [
						{
							"code": "no-such-item",
							"name": "Модуль <b>X</b>",
							"qty": 1,
							"unit": 100,
							"total": 100,
						},
						{"code": "seat", "name": "Місця", "qty": 5, "unit": 10, "total": 50},
					],
				},
				ensure_ascii=False,
			)
		)

	def test_the_notification_attaches_the_offer(self):
		doc = frappe.get_doc("Notification", NOTIFICATION)

		self.assertEqual((doc.attach_print, doc.print_format), (1, PRINT_FORMAT))

	def test_the_offer_lists_the_lines_the_total_and_the_requisites_and_escapes_the_text_of_a_guest(self):
		html = frappe.render_template(
			frappe.db.get_value("Print Format", PRINT_FORMAT, "html"),
			{"doc": communication(self.content)},
		)

		self.assertIn("Комерційна пропозиція", html)
		self.assertIn("$ 150.00", html)
		self.assertIn("5", html)
		self.assertNotIn("<b>X</b>", html)
		self.assertIn("sales@foss.ua", html)

	def test_the_offer_is_rendered_as_a_pdf(self):
		doc = communication(self.content)
		doc.name = "TEST-OFFER"

		pdf = frappe.get_print("Communication", doc=doc, print_format=PRINT_FORMAT, as_pdf=True)

		self.assertTrue(pdf.startswith(b"%PDF"))
