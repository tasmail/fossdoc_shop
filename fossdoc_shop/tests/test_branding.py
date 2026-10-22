from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.branding import COLORS, DEFAULTS, brand, requisites


class TestBranding(FrappeTestCase):
	def test_without_a_company_the_requisites_are_the_defaults(self):
		with (
			patch.object(frappe.db, "get_single_value", return_value=None),
			patch.object(frappe.db, "get_value", return_value=None),
		):
			self.assertEqual(requisites(), DEFAULTS)

	def test_the_company_and_the_address_of_the_site_override_the_defaults(self):
		company = frappe._dict(
			company_name="Test Co", phone_no="+380 1", email="x@test.example", website=None
		)
		address = frappe._dict(address_line1="Main 1", city="Kyiv", pincode="01001")

		def get_value(doctype, *args, **kwargs):
			return {"Company": company, "Dynamic Link": "ADDR", "Address": address}[doctype]

		with (
			patch.object(frappe.db, "get_single_value", return_value="Test Co"),
			patch.object(frappe.db, "get_value", side_effect=get_value),
		):
			data = requisites()

		self.assertEqual(
			(data["company"], data["phone"], data["email"]), ("Test Co", "+380 1", "x@test.example")
		)
		self.assertEqual(data["site"], DEFAULTS["site"])
		self.assertEqual(data["address"], "01001, Kyiv, Main 1")

	def test_the_brand_has_the_palette_and_the_requisites(self):
		data = brand()

		self.assertEqual(data["primary"], COLORS["primary"])
		self.assertIn("phone", data)
