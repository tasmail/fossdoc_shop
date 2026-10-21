"""Create or refresh the records that the app needs: the Notification that mails a calculation."""

from pathlib import Path

import frappe

from fossdoc_shop.calculation import MARKER

TEMPLATES = Path(__file__).parent / "templates"
NOTIFICATION = MARKER
PRINT_FORMAT = "Комерційна пропозиція FossDoc"


def ensure_print_format():
	"""The commercial offer: the PDF that goes with the letter."""
	values = {
		"doc_type": "Communication",
		"module": "FossDoc Shop",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"html": (TEMPLATES / "calculation_offer.html").read_text(encoding="utf-8"),
		"disabled": 0,
		"standard": "No",
	}
	if frappe.db.exists("Print Format", PRINT_FORMAT):
		doc = frappe.get_doc("Print Format", PRINT_FORMAT)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc({"doctype": "Print Format", "name": PRINT_FORMAT, **values}).insert(
		ignore_permissions=True
	)


def ensure_calculation_mail():
	"""Create the Notification once and refresh its text from the template on every migration."""
	ensure_print_format()
	message = (TEMPLATES / "calculation_mail.html").read_text(encoding="utf-8")
	values = {
		"subject": MARKER,
		"document_type": "Communication",
		"event": "New",
		"channel": "Email",
		"enabled": 1,
		"condition": f'doc.content and doc.content.startswith("{MARKER}")',
		"message_type": "HTML",
		"message": message,
		"attach_print": 1,
		"print_format": PRINT_FORMAT,
	}
	if frappe.db.exists("Notification", NOTIFICATION):
		doc = frappe.get_doc("Notification", NOTIFICATION)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return
	doc = frappe.get_doc({"doctype": "Notification", "name": NOTIFICATION, **values})
	doc.append("recipients", {"receiver_by_document_field": "sender"})
	doc.insert(ignore_permissions=True)
