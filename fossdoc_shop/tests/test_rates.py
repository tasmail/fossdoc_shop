import datetime
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop import rates
from fossdoc_shop.tests.seed import seed_settings

NBU = [{"r030": 840, "txt": "Долар США", "rate": 41.5321, "cc": "USD", "exchangedate": "25.10.2026"}]
MASTER = "Test USD List"
TARGET = "Test UAH List"
ITEM = "TEST-RATE-ITEM"


class TestRateOfTheNationalBank(FrappeTestCase):
	def test_the_rate_and_its_date_are_read_from_the_answer(self):
		self.assertEqual(rates.parse_nbu(NBU), (41.5321, datetime.date(2026, 10, 25)))

	def test_an_answer_without_the_rate_or_with_an_absurd_one_is_refused(self):
		for rows in (
			[],
			[{"cc": "EUR", "rate": 45, "exchangedate": "25.10.2026"}],
			[{**NBU[0], "rate": 0}],
			[{**NBU[0], "rate": 5000}],
		):
			with self.assertRaises(ValueError):
				rates.parse_nbu(rows)

	def test_a_price_is_rounded_to_the_step_and_a_half_goes_up(self):
		self.assertEqual(rates.round_to_step(3700.5, 1), 3701)
		self.assertEqual(rates.round_to_step(3704, 10), 3700)
		self.assertEqual(rates.round_to_step(3705, 10), 3710)
		self.assertEqual(rates.round_to_step(3.14159, 0), 3.14)


class TestUahPrices(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for name, currency in ((MASTER, "USD"), (TARGET, "UAH")):
			if not frappe.db.exists("Price List", name):
				frappe.get_doc(
					{"doctype": "Price List", "price_list_name": name, "currency": currency, "selling": 1}
				).insert()
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert()
		frappe.db.delete("Item Price", {"item_code": ITEM})
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": ITEM,
				"price_list": MASTER,
				"price_list_rate": 100,
				"currency": "USD",
				"selling": 1,
			}
		).insert()
		seed_settings(master_price_list=MASTER, uah_price_list=TARGET, rounding_step=1)

	def price(self):
		return frappe.db.get_value("Item Price", {"item_code": ITEM, "price_list": TARGET}, "price_list_rate")

	def test_the_price_in_hryvnia_is_the_price_in_dollars_at_the_rate_rounded(self):
		result = rates.sync_prices(41.5321)

		self.assertEqual(self.price(), 4153)
		self.assertGreaterEqual(result["items"]["created"], 1)

	def test_a_new_rate_changes_the_price_and_the_same_rate_changes_nothing(self):
		rates.sync_prices(41.5)
		again = rates.sync_prices(41.5)
		self.assertEqual(again["items"], {"created": 0, "changed": 0, "removed": 0})

		changed = rates.sync_prices(42)

		self.assertEqual(self.price(), 4200)
		self.assertEqual(changed["items"]["changed"], 1)

	def test_a_price_that_left_the_dollar_list_leaves_the_hryvnia_list(self):
		rates.sync_prices(41.5)
		frappe.db.delete("Item Price", {"item_code": ITEM, "price_list": MASTER})

		result = rates.sync_prices(41.5)

		self.assertIsNone(self.price())
		self.assertEqual(result["items"]["removed"], 1)

	def test_the_update_stores_a_new_rate_once_and_makes_the_prices_from_it(self):
		frappe.db.delete(
			"Currency Exchange", {"from_currency": "USD", "to_currency": "UAH", "date": "2026-10-25"}
		)
		with mock.patch.object(rates, "fetch_nbu_rate", return_value=(41.5, datetime.date(2026, 10, 25))):
			first = rates.update()
			second = rates.update()

		self.assertTrue(first["new"] and not second["new"])
		self.assertEqual(self.price(), 4150)

	def test_a_failure_of_the_bank_is_logged_and_keeps_the_prices(self):
		rates.sync_prices(41.5)
		with mock.patch.object(rates, "fetch_nbu_rate", side_effect=rates.requests.ConnectionError("down")):
			result = rates.update()

		self.assertIn("error", result)
		self.assertEqual(self.price(), 4150)
