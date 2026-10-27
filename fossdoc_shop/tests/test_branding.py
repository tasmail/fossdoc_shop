import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.branding import brand
from fossdoc_shop.tests.seed import SETTINGS, seed_settings, use_language


class TestBranding(FrappeTestCase):
	def test_the_brand_comes_from_the_settings_and_not_from_the_code(self):
		seed_settings()

		data = brand()

		self.assertEqual(data["primary"], SETTINGS["color_primary"])
		self.assertEqual(data["email"], SETTINGS["sales_email"])
		self.assertEqual(data["company"], SETTINGS["seller_name"])
		self.assertEqual(data["calculator_url"], "https://shop.test.example/calc")
		self.assertEqual(data["cart_url"], "https://shop.test.example/basket")
		self.assertEqual(data["cc"], SETTINGS["sales_email"])

	def test_the_seller_is_named_in_the_language_of_the_letter_when_the_site_has_the_translation(self):
		seed_settings()
		doc = frappe.get_doc(
			{
				"doctype": "Translation",
				"language": "en",
				"source_text": SETTINGS["seller_name"],
				"translated_text": "Test Seller Enterprise",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Translation", doc.name, force=True)
		frappe.clear_cache()
		use_language(self, "en")

		self.assertEqual(brand()["company"], "Test Seller Enterprise")
		use_language(self, "uk")
		self.assertEqual(brand()["company"], SETTINGS["seller_name"])

	def test_a_change_of_a_setting_is_seen_at_once(self):
		seed_settings()
		seed_settings(sales_email="other@test.example", site_url="https://x.test.example/")

		data = brand()

		self.assertEqual((data["email"], data["site"]), ("other@test.example", "https://x.test.example"))

	def test_no_copy_to_sales_gives_an_empty_cc(self):
		seed_settings(copy_sales=0)

		self.assertEqual(brand()["cc"], "")

	def test_an_empty_setting_gives_an_empty_string_and_never_an_invented_value(self):
		doc = frappe.get_doc("FossDoc Shop Settings")
		for field in ("sales_email", "phone", "address", "site_url", "color_primary"):
			doc.set(field, "")
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
		frappe.clear_cache(doctype="FossDoc Shop Settings")

		data = brand()

		self.assertEqual((data["email"], data["phone"], data["address"], data["primary"]), ("", "", "", ""))
