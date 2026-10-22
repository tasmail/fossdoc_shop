"""Create the records that the app needs: the Letter Head, the print format of the offer and the Notification.

The texts of the templates live in `templates/` as the starting point. A record is created once; after that the
copy in the database belongs to the managers, who edit it in the desk (Notification, Print Format, Letter Head),
so a migration never overwrites it. `refresh_templates()` puts the texts of the app back on purpose.
"""

from pathlib import Path

import frappe

from fossdoc_shop.branding import COLORS
from fossdoc_shop.calculation import MARKER

TEMPLATES = Path(__file__).parent / "templates"
NOTIFICATION = MARKER
PRINT_FORMAT = "Комерційна пропозиція FossDoc"
LETTER_HEAD = "FossDoc"
MAIL_MARK = "fossdoc_shop"


def read(name: str) -> str:
	return (TEMPLATES / name).read_text(encoding="utf-8")


def _save(doctype: str, name: str, values: dict, overwrite: bool):
	"""Create the record, or (only when told) replace its templates with the ones of the app."""
	if frappe.db.exists(doctype, name):
		if overwrite:
			doc = frappe.get_doc(doctype, name)
			doc.update(values)
			doc.save(ignore_permissions=True)
		return None
	doc = frappe.get_doc({"doctype": doctype, "name": name, **values})
	return doc


def ensure_letter_head(overwrite: bool = False):
	"""The header and the footer of the offer (Frappe makes it the default letter head when the site has none)."""
	values = {
		"letter_head_name": LETTER_HEAD,
		"source": "HTML",
		"content": read("letter_head_header.html"),
		"footer_source": "HTML",
		"footer": read("letter_head_footer.html"),
	}
	doc = _save("Letter Head", LETTER_HEAD, values, overwrite)
	if doc:
		doc.insert(ignore_permissions=True)


def ensure_print_format(overwrite: bool = False):
	"""The commercial offer: the PDF that goes with the letter."""
	values = {
		"doc_type": "Communication",
		"module": "FossDoc Shop",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"html": read("calculation_offer.html"),
		"css": read("calculation_offer.css").format(**COLORS),
		"disabled": 0,
		"standard": "No",
	}
	doc = _save("Print Format", PRINT_FORMAT, values, overwrite)
	if doc:
		doc.insert(ignore_permissions=True)


def ensure_calculation_mail(overwrite: bool = False):
	"""The Notification that mails a calculation to the visitor (the PDF offer is attached)."""
	ensure_letter_head(overwrite)
	ensure_print_format(overwrite)
	values = {
		"subject": MARKER,
		"document_type": "Communication",
		"event": "New",
		"channel": "Email",
		"enabled": 1,
		"condition": f'doc.content and doc.content.startswith("{MARKER}")',
		"message_type": "HTML",
		"message": read("calculation_mail.html"),
		"attach_print": 1,
		"print_format": PRINT_FORMAT,
	}
	# The Notification that the scripts of the site made before the app has no mark of the app: replace it once.
	legacy = frappe.db.exists("Notification", NOTIFICATION) and MAIL_MARK not in (
		frappe.db.get_value("Notification", NOTIFICATION, "message") or ""
	)
	doc = _save("Notification", NOTIFICATION, values, overwrite or bool(legacy))
	if doc:
		doc.append("recipients", {"receiver_by_document_field": "sender"})
		doc.insert(ignore_permissions=True)


def refresh_templates():
	"""Replace the letter, the offer and the letter head with the texts of the app (`bench execute`)."""
	ensure_calculation_mail(overwrite=True)
