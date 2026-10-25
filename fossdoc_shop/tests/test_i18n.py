import json

import frappe
from frappe import _
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop import orders
from fossdoc_shop.api import send_calculation
from fossdoc_shop.calculation import MARKER
from fossdoc_shop.tests.seed import seed_settings, use_language


class TestTranslations(FrappeTestCase):
	def test_the_texts_of_the_letters_have_a_russian_and_an_english_translation(self):
		use_language(self, "ru")
		self.assertEqual(_("Разом"), "Итого")
		use_language(self, "en")
		self.assertEqual(_("Разом"), "Total")
		use_language(self, "uk")
		self.assertEqual(_("Разом"), "Разом")

	def test_the_names_of_the_items_are_translated_the_same_way(self):
		use_language(self, "en")
		self.assertEqual(_("Робоче місце користувача"), "User seat")


class TestLetterOfACalculation(FrappeTestCase):
	def setUp(self):
		seed_settings()

	def render(self, lang):
		body = {
			"lang": lang,
			"total": 150,
			"lines": [{"code": "a", "name": "A", "qty": 1, "unit": 150, "total": 150}],
		}
		doc = frappe.get_doc(
			{
				"doctype": "Communication",
				"sender": "client@example.org",
				"content": f"{MARKER}\n{json.dumps(body)}",
			}
		)
		return frappe.render_template(frappe.db.get_value("Notification", MARKER, "message"), {"doc": doc})

	def test_the_letter_is_in_the_language_of_the_page_of_the_calculation(self):
		frappe.local.lang = "ru"
		self.addCleanup(setattr, frappe.local, "lang", "en")
		self.assertIn("Итого", self.render("ru"))
		frappe.local.lang = "en"
		self.assertIn("Total", self.render("en"))

	def test_the_endpoint_makes_the_letter_in_the_language_that_the_page_sent(self):
		body = {
			"lang": "en",
			"total": 1,
			"lines": [{"code": "a", "name": "A", "qty": 1, "unit": 1, "total": 1}],
		}
		previous = frappe.local.lang
		self.addCleanup(setattr, frappe.local, "lang", previous)
		frappe.local.lang = "uk"

		send_calculation("client@example.org", f"{MARKER}\n{json.dumps(body)}\n\nA: 1")

		self.assertEqual(frappe.local.lang, "en")


class TestOrders(FrappeTestCase):
	def setUp(self):
		orders.ensure_item_fields()
		frappe.db.delete("Item", {"item_code": "TEST-ONCE"})
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "TEST-ONCE",
				"item_name": "Test once",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"max_order_qty": 1,
			}
		).insert()

	def test_a_row_does_not_hold_more_than_the_item_allows_and_a_free_item_is_not_cut(self):
		doc = frappe._dict(items=[frappe._dict(item_code="TEST-ONCE", item_name="Test once", qty=3)])

		orders.limit_quantities(doc)

		self.assertEqual(doc["items"][0].qty, 1)
		other = frappe._dict(items=[frappe._dict(item_code="FD-SEAT-NOT-LIMITED", item_name="Seat", qty=40)])
		orders.limit_quantities(other)
		self.assertEqual(other["items"][0].qty, 40)

	def test_an_order_takes_the_language_of_the_visit_once(self):
		previous = frappe.local.lang
		self.addCleanup(setattr, frappe.local, "lang", previous)
		frappe.local.lang = "ru"

		order = frappe._dict(language=None)
		orders.set_language(order)
		self.assertEqual(order.language, "ru")

		frappe.local.lang = "en"
		orders.set_language(order)  # the language of an order does not change
		self.assertEqual(order.language, "ru")

		frappe.local.lang = "de"  # a language that the shop does not serve is not recorded
		other = frappe._dict(language=None)
		orders.set_language(other)
		self.assertIsNone(other.language)

	def test_a_buyer_who_signs_up_keeps_the_language_of_the_site_and_a_user_of_the_desk_is_left_alone(self):
		previous = frappe.local.lang
		self.addCleanup(setattr, frappe.local, "lang", previous)
		frappe.local.lang = "ru"

		buyer = frappe._dict(doctype="User", user_type="Website User", language=None)
		orders.set_language(buyer)
		manager = frappe._dict(doctype="User", user_type="System User", language=None)
		orders.set_language(manager)

		self.assertEqual(buyer.language, "ru")
		self.assertIsNone(manager.language)
