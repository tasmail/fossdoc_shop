"""The Pay button of the order page: the unpaid remainder and the template.

These tests need no Frappe site (the helper and the template are read as plain Python and text).
"""

import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from fossdoc_shop.templates.pages.order import unpaid_amount

TEMPLATE = Path(__file__).parents[1] / "templates" / "pages" / "order.html"


def order(**values):
	data = {
		"doctype": "Sales Order",
		"docstatus": 1,
		"currency": "UAH",
		"party_account_currency": "UAH",
		"conversion_rate": 1,
		"grand_total": 45.67,
		"rounded_total": 0,
		"advance_paid": 0,
		"outstanding_amount": 0,
	}
	data.update(values)
	return SimpleNamespace(**data)


class TestUnpaidAmount(unittest.TestCase):
	def test_an_unpaid_order_owes_its_grand_total_to_the_kopiyka(self):
		self.assertEqual(unpaid_amount(order()), 45.67)

	def test_a_paid_order_owes_nothing_and_has_no_button(self):
		self.assertEqual(unpaid_amount(order(advance_paid=45.67)), 0)

	def test_the_rounded_total_of_an_old_order_is_what_the_payment_request_charges(self):
		# ERPNext charges (rounded_total or grand_total) less the advance, so the page must print the same
		self.assertEqual(unpaid_amount(order(rounded_total=46)), 46)
		self.assertEqual(unpaid_amount(order(rounded_total=46, advance_paid=46)), 0)

	def test_a_part_payment_leaves_the_remainder(self):
		self.assertEqual(unpaid_amount(order(grand_total=100, advance_paid=40.1)), 59.9)

	def test_an_overpaid_order_owes_nothing(self):
		self.assertEqual(unpaid_amount(order(advance_paid=50)), 0)

	def test_a_draft_and_a_cancelled_order_have_no_button(self):
		self.assertEqual(unpaid_amount(order(docstatus=0)), 0)
		self.assertEqual(unpaid_amount(order(docstatus=2)), 0)

	def test_an_advance_in_the_currency_of_the_account_is_converted(self):
		# the advance is kept in the currency of the party account, the order is in another one
		done = order(
			currency="USD", party_account_currency="UAH", conversion_rate=40, grand_total=50, advance_paid=800
		)
		self.assertEqual(unpaid_amount(done), 30)

	def test_an_invoice_owes_its_outstanding_amount(self):
		self.assertEqual(unpaid_amount(order(doctype="Sales Invoice", outstanding_amount=12.34)), 12.34)
		self.assertEqual(unpaid_amount(order(doctype="Sales Invoice", outstanding_amount=0)), 0)

	def test_a_quotation_cannot_be_paid(self):
		self.assertEqual(unpaid_amount(order(doctype="Quotation")), 0)

	def test_the_rounding_is_half_up_like_flt_of_frappe(self):
		# round() would give 10.12 and 2.67 (binary floats, banker's rounding); the Payment Request charges 10.13 and 2.68
		self.assertEqual(unpaid_amount(order(grand_total=10.125)), 10.13)
		self.assertEqual(unpaid_amount(order(grand_total=10.135)), 10.14)
		self.assertEqual(unpaid_amount(order(grand_total=2.675)), 2.68)

	def test_a_negative_remainder_is_nothing(self):
		self.assertEqual(unpaid_amount(order(grand_total=10, advance_paid=10.125)), 0)

	def test_the_precision_of_the_currency_is_kept(self):
		self.assertEqual(unpaid_amount(order(grand_total=10.126), precision=2), 10.13)
		self.assertEqual(unpaid_amount(order(grand_total=5), precision=0), 5)


class TestTemplate(unittest.TestCase):
	def setUp(self):
		self.text = TEMPLATE.read_text()

	def test_the_button_is_shown_for_a_remainder_and_prints_it(self):
		self.assertIn("{% if enabled_checkout and pay_amount and not pay_state %}", self.text)
		self.assertIn("{{ pay_amount_formatted }}", self.text)

	def test_a_payment_in_progress_replaces_the_button_with_the_notice(self):
		self.assertIn("{% elif enabled_checkout and pay_state %}", self.text)
		self.assertIn("fossdoc_shop/templates/payment_notice.html", self.text)
		notice = (TEMPLATE.parents[1] / "payment_notice.html").read_text()
		self.assertIn("Оплата цього замовлення вже розпочата", notice)
		self.assertIn("Продовжити оплату", notice)
		# in the second state ("processing") there is no way to start or continue a payment
		self.assertEqual(notice.count("make_payment_request"), 1)
		self.assertLess(notice.index('pay_state == "processing"'), notice.index("{% else %}"))
		self.assertGreater(notice.index("make_payment_request"), notice.index("{% else %}"))

	def test_the_links_disable_themselves_on_a_click_and_the_popup_is_shown_once(self):
		notice = (TEMPLATE.parents[1] / "payment_notice.html").read_text()
		links = (TEMPLATE.parents[1] / "payment_links.html").read_text()
		for text in (self.text, notice):
			self.assertIn("data-wait=", text)
			self.assertIn("payment_links.html", text)
		self.assertIn("pageshow", links)
		self.assertIn("event.persisted", links)
		self.assertIn("aria-disabled", links)
		self.assertIn("preventDefault", links)
		# a click that opens a new tab, and a cancelled navigation, must not leave the link disabled
		self.assertIn("event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0", links)
		self.assertIn("setTimeout(restore, 10000)", links)
		self.assertIn("visibilitychange", links)
		self.assertIn('document.visibilityState === "visible"', links)
		self.assertIn("history.replaceState", notice)
		self.assertIn('notice.dataset.state !== "processing"', notice)

	def test_the_stock_condition_and_the_grand_total_are_gone_from_the_button(self):
		self.assertNotIn('doc.doctype != "Sales Invoice"', self.text)
		self.assertNotIn('doc.get_formatted("grand_total")', self.text)

	def test_the_copy_names_its_stock_file(self):
		self.assertIn("webshop/webshop/templates/pages/order.html", self.text.split("{% extends", 1)[0])


class TestStockTemplate(unittest.TestCase):
	def test_the_copy_differs_from_the_stock_page_only_in_the_header_and_the_pay_block(self):
		import importlib.util

		spec = importlib.util.find_spec("webshop")
		if not spec or not spec.origin:
			self.skipTest("Webshop is not installed")
		stock_file = Path(spec.origin).parent / "templates" / "pages" / "order.html"
		if not stock_file.exists():
			self.skipTest("Webshop has no such page")
		pay = re.compile(
			r"\{% if enabled_checkout and (?:pay_amount|\(doc\.doctype).*?\{% endif %\}", re.DOTALL
		)
		copy = TEMPLATE.read_text().split("-#}\n", 1)[1]
		self.assertEqual(pay.sub("PAY", copy, count=1), pay.sub("PAY", stock_file.read_text(), count=1))


if __name__ == "__main__":
	unittest.main()
