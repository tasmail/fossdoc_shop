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

	def test_the_html_that_frappe_adds_around_the_message_is_removed(self):
		calc = parse_calculation("<div>" + message().replace("\n", "<br>\n") + "</div>")

		self.assertIsNotNone(calc)


class TestDescribe(FrappeTestCase):
	def test_only_existing_items_are_described(self):
		self.assertEqual(describe([]), {})
		self.assertEqual(describe(["no-such-item-xyz"]), {})
