"""The look and the requisites that the letter and the offer share.

Nothing about the seller is written in the code: it all comes from the single DocType FossDoc Shop Settings, which
the deploy of the site fills from its repository and a manager can change in the desk. An empty setting gives an
empty string, never an invented value.
"""

import frappe

SETTINGS = "FossDoc Shop Settings"
COLOR_FIELDS = ("primary", "tint", "line", "text", "muted", "footer")


def brand() -> dict:
	"""Colours and requisites for the templates (the Jinja method `brand`)."""
	settings = frappe.get_cached_doc(SETTINGS)
	data = {name: settings.get(f"color_{name}") or "" for name in COLOR_FIELDS}
	site = (settings.site_url or "").rstrip("/")
	data.update(
		{
			"brand": settings.brand_name or "",
			"company": settings.seller_name or "",
			"legal_name": settings.legal_name or "",
			"email": settings.sales_email or "",
			"phone": settings.phone or "",
			"address": settings.address or "",
			"site": site,
			"calculator_url": site + (settings.calculator_path or ""),
			# the Cc of the letter (a Jinja template of the Notification reads it)
			"cc": (settings.sales_email or "") if settings.copy_sales else "",
		}
	)
	return data
