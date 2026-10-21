import frappe
from frappe.tests.utils import FrappeTestCase

import fossdoc_shop
from fossdoc_shop import hooks


class TestInstall(FrappeTestCase):
	def test_the_app_is_installed_on_the_site(self):
		self.assertIn("fossdoc_shop", frappe.get_installed_apps())

	def test_the_app_is_named_for_the_hooks_of_frappe(self):
		self.assertEqual(hooks.app_name, "fossdoc_shop")

	def test_the_version_is_set(self):
		self.assertRegex(fossdoc_shop.__version__, r"^\d+\.\d+\.\d+$")
