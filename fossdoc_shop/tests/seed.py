"""Values for FossDoc Shop Settings in the tests (the real ones come from the deploy of the site)."""

import frappe

SETTINGS = {
	"brand_name": "TestDoc",
	"seller_name": "Test Seller Co",
	"legal_name": "Test Legal LLC",
	"sales_email": "sales@test.example",
	"copy_sales": 1,
	"phone": "+00 111 222",
	"address": "1 Test Street, Testville",
	"site_url": "https://shop.test.example",
	"calculator_path": "/calc",
	"cart_path": "/basket",
	"color_primary": "#112233",
	"color_tint": "#aabbcc",
	"color_line": "#ccbbaa",
	"color_text": "#010203",
	"color_muted": "#040506",
	"color_footer": "#070809",
}


def seed_settings(**override):
	doc = frappe.get_doc("FossDoc Shop Settings")
	doc.update({**SETTINGS, **override})
	doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype="FossDoc Shop Settings")
	return doc


def use_language(test, lang="uk"):
	"""The language of the request for the length of a test (the letters are made in the language of the buyer)."""
	previous = frappe.local.lang
	frappe.local.lang = lang
	test.addCleanup(setattr, frappe.local, "lang", previous)
