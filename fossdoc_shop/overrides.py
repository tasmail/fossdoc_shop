"""Hooks of the app: the e-mail of a calculation and the download of a PDF."""

import email
from email import policy
from email.utils import formataddr

import frappe

from fossdoc_shop.branding import brand
from fossdoc_shop.calculation import MARKER


def set_reply_to(doc, method=None):
	"""A reply to the letter with a calculation goes to sales and not to the no-reply address that sends it.

	The Notification of Frappe has no Reply-To, so the header of the queued message is set here. The letter is
	found by its subject, which is the marker of the calculation.
	"""
	if doc.reference_doctype != "Communication" or not doc.message:
		return
	message = email.message_from_string(doc.message, policy=policy.SMTP)
	subject = str(message.get("Subject") or "")
	if MARKER not in subject:
		return
	data = brand()
	if not data["email"]:
		return
	del message["Reply-To"]
	message["Reply-To"] = formataddr((data["company"], data["email"]))
	doc.message = message.as_string()


NOTHING = ("", "none", "null", "undefined")


def _clean(value):
	"""A template of Frappe writes a missing value into an address as the word None: it is no value."""
	return None if isinstance(value, str) and value.strip().lower() in NOTHING else value


@frappe.whitelist()
def download_pdf(
	doctype, name, format=None, doc=None, no_letterhead=0, language=None, letterhead=None, pdf_generator=None
):
	"""The download of a PDF of Frappe that accepts what its own print page sends.

	The page /printview (the Print and Download buttons of a quotation or an order of the portal) builds the address
	with letterhead=None&no_letterhead=None; the typed endpoint of Frappe refuses the word None and the customer sees a
	traceback. The values are cleaned and the endpoint of Frappe does the rest.
	"""
	from frappe.utils import print_format

	no_letterhead = _clean(no_letterhead)
	if isinstance(no_letterhead, str):
		no_letterhead = 1 if no_letterhead.strip().lower() in ("1", "true", "yes") else 0
	return print_format.download_pdf(
		doctype,
		name,
		format=_clean(format),
		doc=doc,
		no_letterhead=no_letterhead or 0,
		language=_clean(language),
		letterhead=_clean(letterhead),
		pdf_generator=_clean(pdf_generator),
	)
