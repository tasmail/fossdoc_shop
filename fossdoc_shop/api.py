"""The endpoint that the calculator of the site calls to mail a calculation to the visitor."""

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
	if not parse_calculation(message):
		frappe.throw(_("The calculation is not valid"), frappe.ValidationError)
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
