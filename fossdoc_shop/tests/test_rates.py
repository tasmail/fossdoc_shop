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
PAYMENT_ITEM = "TEST-RATE-PAYMENT"


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

	def test_a_payment_for_services_keeps_the_kopecks_of_the_rate_the_other_prices_are_rounded(self):
		if not frappe.db.exists("Item Group", rates.PAYMENTS_GROUP):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": rates.PAYMENTS_GROUP,
					"parent_item_group": "All Item Groups",
				}
			).insert()
		if not frappe.db.exists("Item", PAYMENT_ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": PAYMENT_ITEM,
					"item_group": rates.PAYMENTS_GROUP,
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert()
		frappe.db.delete("Item Price", {"item_code": PAYMENT_ITEM})
		# the other tests count the prices that a sync changes: this item must not stay in the list
		self.addCleanup(frappe.db.delete, "Item Price", {"item_code": PAYMENT_ITEM})
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": PAYMENT_ITEM,
				"price_list": MASTER,
				"price_list_rate": 1,
				"currency": "USD",
				"selling": 1,
			}
		).insert()

		rates.sync_prices(45.3526)

		paid = frappe.db.get_value(
			"Item Price", {"item_code": PAYMENT_ITEM, "price_list": TARGET}, "price_list_rate"
		)
		self.assertEqual(paid, 45.35)  # not 45: the amount in dollars times it follows the rate
		self.assertEqual(self.price(), 4535)  # an ordinary price is still rounded to the step (1)

	def test_the_migrate_makes_the_prices_again_from_the_stored_rate_and_survives_a_failure(self):
		from fossdoc_shop import hooks

		self.assertIn("fossdoc_shop.rates.refresh", hooks.after_migrate)
		rates.sync_prices(41.5)
		frappe.db.set_value("Item Price", {"item_code": ITEM, "price_list": TARGET}, "price_list_rate", 1)
		with mock.patch.object(rates, "current_rate", return_value=(41.5, datetime.date(2026, 10, 25))):
			rates.refresh()
		self.assertEqual(self.price(), 4150)  # the price that left the rate is made again

		with (
			mock.patch.object(rates, "sync_prices", side_effect=ValueError("broken")),
			mock.patch.object(rates.frappe, "log_error") as logged,
		):
			rates.refresh()  # no exception
		logged.assert_called_once()

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

	def test_the_calculator_reads_the_prices_and_the_quantity_rules_of_the_hryvnia_list(self):
		# the rules are put after the list is made: making it drops the rules that the dollar list has not
		rates.sync_prices(41.5)
		frappe.db.delete("Pricing Rule", {"for_price_list": TARGET})
		for min_qty, max_qty, rate in ((6, 0, 3900), (1, 5, 4000)):
			frappe.get_doc(
				{
					"doctype": "Pricing Rule",
					"title": f"Test rate rule {min_qty}",
					"apply_on": "Item Code",
					"items": [{"item_code": ITEM}],
					"selling": 1,
					"currency": "UAH",
					"for_price_list": TARGET,
					"price_or_product_discount": "Price",
					"rate_or_discount": "Rate",
					"rate": rate,
					"min_qty": min_qty,
					"max_qty": max_qty,
				}
			).insert()
		frappe.cache().delete_value(rates.SHEET_KEY)

		sheet = rates.price_sheet()

		self.assertEqual(sheet["items"][ITEM], 4150)
		self.assertEqual(sheet["slabs"][ITEM], [[1, 5, 4000], [6, 0, 3900]])

	def test_a_new_rate_reaches_the_calculator_at_once(self):
		rates.sync_prices(41.5)
		self.assertEqual(rates.price_sheet()["items"][ITEM], 4150)

		rates.sync_prices(42)

		self.assertEqual(rates.price_sheet()["items"][ITEM], 4200)

	def test_a_guest_may_read_the_prices(self):
		from fossdoc_shop import api

		rates.sync_prices(41.5)
		frappe.set_user("Guest")
		try:
			frappe.is_whitelisted(api.prices)  # raises for a method that a guest may not call
			self.assertEqual(api.prices()["items"][ITEM], 4150)
		finally:
			frappe.set_user("Administrator")

	def make_rule(self, min_qty, rate, **extra):
		return frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"Test rate rule {min_qty} {rate}",
				"apply_on": "Item Code",
				"items": [{"item_code": ITEM}],
				"selling": 1,
				"currency": "UAH",
				"for_price_list": TARGET,
				"price_or_product_discount": "Price",
				"rate_or_discount": "Rate",
				"rate": rate,
				"min_qty": min_qty,
				"max_qty": 0,
				**extra,
			}
		).insert()

	def test_a_rule_that_the_cart_does_not_apply_today_is_not_shown_by_the_calculator(self):
		rates.sync_prices(41.5)
		frappe.db.delete("Pricing Rule", {"for_price_list": TARGET})
		yesterday = frappe.utils.add_days(frappe.utils.nowdate(), -1)
		tomorrow = frappe.utils.add_days(frappe.utils.nowdate(), 1)
		ended = self.make_rule(1, 3000, valid_upto=tomorrow)
		frappe.db.set_value("Pricing Rule", ended.name, "valid_upto", yesterday)  # Frappe refuses a past date
		self.make_rule(1, 3100, valid_from=tomorrow)
		self.make_rule(1, 3900)
		frappe.cache().delete_value(rates.SHEET_KEY)

		self.assertEqual(rates.price_sheet()["slabs"][ITEM], [[1, 0, 3900]])

	def test_an_empty_sheet_is_not_kept_for_ten_minutes(self):
		frappe.cache().delete_value(rates.SHEET_KEY)
		config = frappe.get_doc("FossDoc Shop Settings")
		previous = config.uah_price_list
		frappe.db.set_single_value("FossDoc Shop Settings", "uah_price_list", "")
		frappe.clear_cache(doctype="FossDoc Shop Settings")
		self.addCleanup(frappe.db.set_single_value, "FossDoc Shop Settings", "uah_price_list", previous)
		self.addCleanup(frappe.clear_cache, doctype="FossDoc Shop Settings")

		self.assertEqual(rates.price_sheet(), {"items": {}, "slabs": {}})
		self.assertIsNone(frappe.cache().get_value(rates.SHEET_KEY))

	def test_the_sheet_is_dropped_again_after_the_commit_of_a_new_rate(self):
		before = len(frappe.db.after_commit._functions)
		rates.sync_prices(41.5)
		ours = [
			callback
			for callback in list(frappe.db.after_commit._functions)[before:]
			if getattr(callback, "__module__", "") == "fossdoc_shop.rates"
		]
		frappe.cache().set_value(rates.SHEET_KEY, {"items": {"x": 1}, "slabs": {}})

		self.assertEqual(len(ours), 1)
		ours[0]()  # what the commit runs

		self.assertIsNone(frappe.cache().get_value(rates.SHEET_KEY))
