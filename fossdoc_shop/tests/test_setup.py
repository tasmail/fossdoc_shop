import json

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.calculation import MARKER
from fossdoc_shop.setup import (
	LETTER_HEAD,
	NOTIFICATION,
	PRINT_FORMAT,
	ensure_calculation_mail,
	refresh_templates,
)
from fossdoc_shop.tests.seed import seed_settings, use_language


def communication(content):
	return frappe.get_doc({"doctype": "Communication", "content": content, "sender": "client@example.com"})


class TestCalculationMail(FrappeTestCase):
	def setUp(self):
		use_language(self)
		seed_settings()
		ensure_calculation_mail()

	def test_the_notification_is_created_once_and_a_migration_keeps_the_edits_of_a_manager(self):
		edited = "{# fossdoc_shop fossdoc-i18n #}<p>edited by a manager</p>"
		frappe.db.set_value("Notification", NOTIFICATION, "message", edited)

		ensure_calculation_mail()
		ensure_calculation_mail()

		self.assertEqual(frappe.db.count("Notification", {"name": NOTIFICATION}), 1)
		self.assertEqual(frappe.db.get_value("Notification", NOTIFICATION, "message"), edited)

	def test_an_old_letter_without_the_mark_of_the_app_is_replaced_once(self):
		frappe.db.set_value("Notification", NOTIFICATION, "message", "<p>made by the scripts of the site</p>")

		ensure_calculation_mail()

		self.assertIn("fossdoc_shop", frappe.db.get_value("Notification", NOTIFICATION, "message"))

	def test_the_texts_of_the_app_are_put_back_only_on_purpose(self):
		frappe.db.set_value("Notification", NOTIFICATION, "message", "edited by a manager")
		frappe.db.set_value("Print Format", PRINT_FORMAT, "html", "edited")

		refresh_templates()

		self.assertIn("parse_calculation", frappe.db.get_value("Notification", NOTIFICATION, "message"))
		self.assertIn("Комерційна пропозиція", frappe.db.get_value("Print Format", PRINT_FORMAT, "html"))

	def test_the_offer_has_a_letter_head_that_is_default_only_when_the_site_has_none(self):
		self.assertTrue(frappe.db.exists("Letter Head", LETTER_HEAD))
		self.assertEqual(frappe.db.count("Letter Head", {"is_default": 1}), 1)

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
		self.assertIn("9 × 50\u00a0грн", html)
		self.assertIn("450\u00a0грн", html)
		self.assertIn("щомісяця", html)

	def test_a_message_that_is_not_a_calculation_gets_a_plain_answer_and_no_html_from_the_guest(self):
		message = frappe.db.get_value("Notification", NOTIFICATION, "message")
		content = MARKER + "\n" + json.dumps({"lines": [{"code": "x", "name": "<script>alert(1)</script>"}]})

		html = frappe.render_template(message, {"doc": communication(content)})

		self.assertNotIn("<script>", html)


class TestOffer(FrappeTestCase):
	def setUp(self):
		use_language(self)
		seed_settings()
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
		self.assertIn("150\u00a0грн", html)
		self.assertIn("5", html)
		self.assertNotIn("<b>X</b>", html)

	def test_the_offer_is_rendered_as_a_pdf(self):
		doc = communication(self.content)
		doc.name = "TEST-OFFER"

		pdf = frappe.get_print("Communication", doc=doc, print_format=PRINT_FORMAT, as_pdf=True)

		self.assertTrue(pdf.startswith(b"%PDF"))


class TestOneSourceOfLook(FrappeTestCase):
	def test_the_code_and_the_templates_hold_no_business_data_of_the_seller(self):
		import re
		from pathlib import Path

		root = Path(__file__).resolve().parent.parent
		files = [
			p for p in root.rglob("*") if p.suffix in {".py", ".html", ".css"} and "tests" not in p.parts
		]
		patterns = {
			"an e-mail address": r"[\w.+-]+@[\w-]+\.[a-z]{2,}",
			"a phone number": r"\+\d[\d ()-]{7,}",
			"a colour": r"#[0-9a-fA-F]{6}\b",
			# the namespaces of XML are names of a format, and the National Bank is a public service: not the seller
			"a site address": r"https?://(?!www\.w3\.org|www\.foss\.kharkov\.ua/FossDoc/|bank\.gov\.ua/)[\w.-]+\.[a-z]{2,}",
		}
		for path in files:
			if path.name in {"hooks.py"}:  # the publisher and the e-mail of the app itself
				continue
			text = path.read_text(encoding="utf-8")
			for what, pattern in patterns.items():
				self.assertIsNone(re.search(pattern, text), f"{path.name} hardcodes {what}")

	def test_the_button_of_the_letter_leads_to_the_cart_for_a_cart_and_to_the_calculator_for_a_calculation(
		self,
	):
		seed_settings()
		ensure_calculation_mail()
		message = frappe.db.get_value("Notification", NOTIFICATION, "message")
		for kind, url in (
			("cart", "https://shop.test.example/basket"),
			("calculator", "https://shop.test.example/calc"),
		):
			body = {"kind": kind, "lines": [{"code": "a", "name": "A", "qty": 1, "unit": 1, "total": 1}]}
			doc = communication(MARKER + "\n" + json.dumps(body))

			html = frappe.render_template(message, {"doc": doc})

			self.assertIn(f'href="{url}"', html, kind)

	def test_the_offer_and_the_letter_use_the_settings(self):
		seed_settings()
		ensure_calculation_mail()
		body = (
			MARKER
			+ "\n"
			+ json.dumps({"lines": [{"code": "a", "name": "A", "qty": 1, "unit": 1, "total": 1}]})
		)
		doc = communication(body)
		doc.name = "TEST-LOOK"

		html = frappe.get_print("Communication", doc=doc, print_format=PRINT_FORMAT, as_pdf=False)
		letter = frappe.render_template(
			frappe.db.get_value("Notification", NOTIFICATION, "message"), {"doc": doc}
		)

		self.assertIn("Test Seller Co", html)
		self.assertIn("sales@test.example", html)
		self.assertIn("#112233", html)
		self.assertIn("https://shop.test.example/calc", letter)
		self.assertIn("Test Legal LLC", letter)
		self.assertIn("TestDoc", letter)
