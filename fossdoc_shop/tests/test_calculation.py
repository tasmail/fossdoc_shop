import json

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.calculation import MARKER, describe, parse_calculation


def message(**payload):
	body = {
		"lang": "uk",
		"lines": [{"code": "resolution", "name": "Резолюції", "qty": 1, "unit": 100, "total": 100}],
	}
	body.update(payload)
	return f"{MARKER}\n{json.dumps(body, ensure_ascii=False)}"


class TestParseCalculation(FrappeTestCase):
	def test_a_valid_message_is_read(self):
		calc = parse_calculation(message(total=100, perMonth=True))

		self.assertEqual(calc["total"], 100)
		self.assertTrue(calc["per_month"])
		self.assertEqual(calc["lines"][0]["code"], "resolution")

	def test_the_origin_of_a_calculation_is_the_calculator_unless_it_says_it_is_the_cart(self):
		self.assertEqual(parse_calculation(message())["kind"], "calculator")
		self.assertEqual(parse_calculation(message(kind="cart"))["kind"], "cart")
		self.assertEqual(parse_calculation(message(kind="<script>"))["kind"], "calculator")

	def test_a_message_without_the_marker_or_with_broken_json_is_not_a_calculation(self):
		self.assertIsNone(parse_calculation("Hello"))
		self.assertIsNone(parse_calculation(f"{MARKER}\n{{not json"))
		self.assertIsNone(parse_calculation(None))
		self.assertIsNone(parse_calculation(message(lines=[])))

	def test_numbers_and_text_from_a_guest_are_limited(self):
		calc = parse_calculation(
			message(
				lang="xx",
				lines=[
					{"code": "a" * 500, "name": "n" * 500, "qty": -5, "unit": "abc", "total": 1e30},
					{"code": 5},
				],
			)
		)

		self.assertEqual(calc["lang"], "uk")
		self.assertEqual(len(calc["lines"]), 1)
		row = calc["lines"][0]
		self.assertEqual(len(row["code"]), 200)
		self.assertEqual(row["qty"], 1)
		self.assertEqual(row["unit"], 0)
		self.assertEqual(row["total"], 1e9)

	def test_the_lines_in_words_after_the_json_line_are_ignored(self):
		calc = parse_calculation(message(total=100) + "\n\nРезолюції: 100.00\n\nРазом: 100.00")

		self.assertEqual(calc["total"], 100)

	def test_the_message_as_the_contact_form_stores_it_is_read(self):
		calc = parse_calculation(frappe.utils.escape_html(message(total=100)))

		self.assertEqual(calc["total"], 100)


class TestDescribe(FrappeTestCase):
	def test_only_existing_items_are_described(self):
		self.assertEqual(describe([]), {})
		self.assertEqual(describe(["no-such-item-xyz"]), {})


class TestMoney(FrappeTestCase):
	def test_an_amount_is_in_hryvnia_whole_without_kopecks_and_with_a_space_between_thousands(self):
		from fossdoc_shop.calculation import money

		self.assertEqual(money(3700), "3 700 грн")
		self.assertEqual(money(1391.6), "1 391.60 грн")
		self.assertEqual(money(None), "0 грн")
