import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.api import shop_status
from fossdoc_shop.branding import brand, shop_open
from fossdoc_shop.orders import require_open_shop
from fossdoc_shop.tests.seed import seed_settings


class TestShopSwitch(FrappeTestCase):
	def test_a_site_that_never_saved_the_setting_keeps_the_shop_open(self):
		seed_settings()
		frappe.db.delete("Singles", {"doctype": "FossDoc Shop Settings", "field": "shop_enabled"})
		frappe.clear_cache(doctype="FossDoc Shop Settings")

		self.assertTrue(shop_open())
		self.assertEqual(shop_status(), {"enabled": True})

	def test_the_status_and_the_brand_follow_the_setting(self):
		seed_settings(shop_enabled=0)

		self.assertFalse(shop_open())
		self.assertEqual(shop_status(), {"enabled": False})
		self.assertFalse(brand()["shop_enabled"])

		seed_settings(shop_enabled=1)

		self.assertTrue(brand()["shop_enabled"])

	def test_a_closed_shop_refuses_a_cart_of_a_visitor_but_not_of_the_staff(self):
		seed_settings(shop_enabled=0)
		doc = frappe._dict(doctype="Quotation")

		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.ValidationError):
			require_open_shop(doc)

		frappe.set_user("Administrator")
		require_open_shop(doc)  # the staff can still make a quotation in the desk

		seed_settings(shop_enabled=1)
		frappe.set_user("Guest")
		require_open_shop(doc)  # an open shop lets everyone through
