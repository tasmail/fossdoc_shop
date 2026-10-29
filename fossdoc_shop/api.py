"""The endpoints that the calculator of the site calls: its prices and the mail of a calculation to the visitor."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import escape_html, validate_email_address

from fossdoc_shop.calculation import MARKER, parse_calculation


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30, seconds=60 * 60)
def send_calculation(sender: str, message: str):
	"""Store the calculation as a Communication; the Notification of the app mails it (with a copy to sales).

	Unlike the contact form of Frappe this sends nothing by itself, so sales get the finished letter with the
	PDF offer and not the raw text of the message.
	"""
	sender = validate_email_address(sender, throw=True)
	calculation = parse_calculation(message)
	if not calculation:
		frappe.throw(_("The calculation is not valid"), frappe.ValidationError)
	# the letter and the offer are made in the language of the page that the visitor calculated on
	frappe.local.lang = calculation["lang"]
	frappe.get_doc(
		{
			"doctype": "Communication",
			"sender": sender,
			"subject": MARKER,
			"sent_or_received": "Received",
			# escaped like the contact form does: the desk shows the content of a Communication as HTML
			"content": escape_html(message),
			"status": "Open",
		}
	).insert(ignore_permissions=True)


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def prices():
	"""The prices in hryvnia that the calculator of the site shows (see rates.price_sheet)."""
	from fossdoc_shop import rates

	return rates.price_sheet()


@frappe.whitelist()
def update_prices():
	"""Fetch the rate of the National Bank and make the prices in hryvnia (the deploy of the site calls it)."""
	frappe.only_for("System Manager")
	from fossdoc_shop import rates

	result = rates.update()
	if not result.get("new") and "error" not in result:
		result["sync"] = rates.sync_prices()
	return result
