"""The look and the requisites that the letter and the offer share.

Nothing about the seller is written in the code: it all comes from the single DocType FossDoc Shop Settings, which
the deploy of the site fills from its repository and a manager can change in the desk. An empty setting gives an
empty string, never an invented value.
"""

import frappe

SETTINGS = "FossDoc Shop Settings"
COLOR_FIELDS = ("primary", "tint", "line", "text", "muted", "footer")


def shop_open() -> bool:
	"""Whether the cart and the payments are open. A site that never saved the setting keeps its shop open."""
	if not frappe.get_meta(SETTINGS).has_field("shop_enabled"):
		return True  # the code is deployed and the site is not migrated yet
	# not get_single_value: it turns a value that was never saved into 0, and that would close the shop
	rows = frappe.db.sql(
		"select `value` from `tabSingles` where `doctype` = %s and `field` = 'shop_enabled'", SETTINGS
	)
	return not rows or rows[0][0] is None or bool(int(rows[0][0]))


def brand() -> dict:
	"""Colours and requisites for the templates (the Jinja method `brand`).

	The name and the address of the seller go through the translation, so a letter in another language prints them
	in that language (the deploy of the site adds the Translation records).
	"""
	settings = frappe.get_cached_doc(SETTINGS)
	data = {name: settings.get(f"color_{name}") or "" for name in COLOR_FIELDS}
	site = (settings.site_url or "").rstrip("/")
	data.update(
		{
			"brand": settings.brand_name or "",
			"company": frappe._(settings.seller_name) if settings.seller_name else "",
			"legal_name": frappe._(settings.legal_name) if settings.legal_name else "",
			"email": settings.sales_email or "",
			"phone": settings.phone or "",
			"address": frappe._(settings.address) if settings.address else "",
			"site": site,
			"calculator_url": site + (settings.calculator_path or ""),
			"cart_url": site + (settings.cart_path or ""),
			"orders_url": site + "/orders",
			# a letter must not send the buyer to a cart that is closed
			"shop_enabled": shop_open(),
			# the Cc of the letter (a Jinja template of the Notification reads it)
			"cc": (settings.sales_email or "") if settings.copy_sales else "",
		}
	)
	return data
