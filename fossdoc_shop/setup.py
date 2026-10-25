"""Create the records that the app needs: the Letter Head, the print format of the offer and the Notification.

The texts of the templates live in `templates/` as the starting point. A record is created once; after that the
copy in the database belongs to the managers, who edit it in the desk (Notification, Print Format, Letter Head),
so a migration never overwrites it. `refresh_templates()` puts the texts of the app back on purpose.
"""

from pathlib import Path

import frappe

from fossdoc_shop.calculation import MARKER
from fossdoc_shop.payment import SUBJECT_MARK

TEMPLATES = Path(__file__).parent / "templates"
NOTIFICATION = MARKER
PRINT_FORMAT = "Комерційна пропозиція FossDoc"
LETTER_HEAD = "FossDoc"
PAYMENT_PRINT_FORMAT = "Підтвердження оплати FossDoc"
PAYMENT_NOTIFICATION = f"{SUBJECT_MARK} отримано"
MAIL_MARK = "fossdoc_shop"
LICENCE_MARK = "fossdoc-licence"  # in the letter of a payment since it carries the licence
HRYVNIA_MARK = "fossdoc-i18n"  # in the letters since they are translated (they replace the earlier ones once)


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
		"disabled": 0,
		"standard": "No",
	}
	doc = _save("Print Format", PRINT_FORMAT, values, overwrite)
	if doc:
		doc.insert(ignore_permissions=True)


def ensure_downloads_group():
	"""The Item Group of the releases for download (the installers are attached to its Items)."""
	from fossdoc_shop.downloads import GROUP

	if not frappe.db.exists("Item Group", GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


def ensure_calculation_mail(overwrite: bool = False):
	"""The Notification that mails a calculation to the visitor (the PDF offer is attached)."""
	# A letter of the dollar time has no mark of the hryvnia (a letter of the scripts of the site has no mark of
	# the app either): the letter and the offer are replaced once.
	legacy = frappe.db.exists("Notification", NOTIFICATION) and (
		MAIL_MARK not in (frappe.db.get_value("Notification", NOTIFICATION, "message") or "")
		or HRYVNIA_MARK not in (frappe.db.get_value("Notification", NOTIFICATION, "message") or "")
	)
	overwrite = overwrite or bool(legacy)
	ensure_letter_head(overwrite)
	ensure_print_format(overwrite)
	values = {
		"subject": '{{ _("Розрахунок вартості") }} FossDoc',
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
	doc = _save("Notification", NOTIFICATION, values, overwrite)
	if doc:
		doc.append("recipients", {"receiver_by_document_field": "sender", "cc": "{{ brand().cc }}"})
		doc.insert(ignore_permissions=True)


def ensure_payment_mail(overwrite: bool = False):
	"""The letter that a customer gets when an order is paid (with the PDF of the confirmation).

	The event is Custom: the Payment Request of the shop sends it itself when it books the payment.
	"""
	# A letter that was made before the licence went into it, or before the texts were translated, has not the
	# marks of these: the letter, the PDF and the letter head are replaced once.
	message = (
		frappe.db.get_value("Notification", PAYMENT_NOTIFICATION, "message")
		if frappe.db.exists("Notification", PAYMENT_NOTIFICATION)
		else None
	)
	legacy = message is not None and (LICENCE_MARK not in message or HRYVNIA_MARK not in message)
	overwrite = overwrite or legacy
	ensure_letter_head(overwrite)
	pdf = {
		"doc_type": "Payment Request",
		"module": "FossDoc Shop",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"html": read("payment_receipt.html"),
		"disabled": 0,
		"standard": "No",
	}
	doc = _save("Print Format", PAYMENT_PRINT_FORMAT, pdf, overwrite)
	if doc:
		doc.insert(ignore_permissions=True)
	values = {
		"subject": '{{ _("Оплату замовлення") }} {{ doc.reference_name }} {{ _("отримано") }}',
		"document_type": "Payment Request",
		"event": "Custom",
		"channel": "Email",
		"enabled": 1,
		"message_type": "HTML",
		"message": read("payment_mail.html"),
		"attach_print": 1,
		"print_format": PAYMENT_PRINT_FORMAT,
	}
	doc = _save("Notification", PAYMENT_NOTIFICATION, values, overwrite)
	if doc:
		doc.append("recipients", {"receiver_by_document_field": "email_to", "cc": "{{ brand().cc }}"})
		doc.insert(ignore_permissions=True)


def refresh_templates():
	"""Replace the letter, the offer and the letter head with the texts of the app (`bench execute`)."""
	ensure_calculation_mail(overwrite=True)
	ensure_payment_mail(overwrite=True)
