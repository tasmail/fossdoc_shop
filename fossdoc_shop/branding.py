"""The look and the requisites that the letter and the offer share.

The colours are the palette of the site (`PRIMARY` is the red of the logo tile). The requisites come from the
Company of the site and its Address when they exist, so a manager changes them in ERPNext; the defaults below
are used until then.
"""

import frappe

COLORS = {
	"primary": "#d9381e",
	"primary_dark": "#b32b14",
	"tint": "#fdeeea",
	"line": "#f6c8bf",
	"text": "#222222",
	"muted": "#666666",
	"footer": "#555555",
}

DEFAULTS = {
	"company": "ФОСС-Он-Лайн",
	"address": "61002, м. Харків, вул. Дарвіна, 20, корп. 3",
	"phone": "+38 057 714-12-28",
	"email": "sales@foss.ua",
	"site": "https://fossdoc.com",
}


def requisites() -> dict:
	"""The requisites of the seller: the default Company of the site over the defaults of the app."""
	data = dict(DEFAULTS)
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	if not company:
		return data
	row = frappe.db.get_value(
		"Company", company, ["company_name", "phone_no", "email", "website"], as_dict=True
	)
	for key, field in (
		("company", "company_name"),
		("phone", "phone_no"),
		("email", "email"),
		("site", "website"),
	):
		if row and row.get(field):
			data[key] = row[field]
	address = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
		"parent",
	)
	if address:
		line = frappe.db.get_value("Address", address, ["address_line1", "city", "pincode"], as_dict=True)
		parts = [line.pincode, line.city, line.address_line1] if line else []
		if any(parts):
			data["address"] = ", ".join(str(part) for part in parts if part)
	return data


def brand() -> dict:
	"""Colours and requisites for the templates (the Jinja method `fossdoc_brand`)."""
	return {**COLORS, **requisites()}
