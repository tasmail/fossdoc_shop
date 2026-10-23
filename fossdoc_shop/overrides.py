"""Hooks of the app: the e-mail of a calculation and the download of a PDF."""

import email
from email import policy
from email.utils import formataddr

import frappe
from frappe import _

from fossdoc_shop.branding import brand
from fossdoc_shop.calculation import MARKER
from fossdoc_shop.payment import SUBJECT_MARK

# The documents of the letters whose replies go to sales: a calculation (Communication) and a payment.
LETTERS = ("Communication", "Payment Request")


def set_reply_to(doc, method=None):
	"""A reply to the letter with a calculation goes to sales and not to the no-reply address that sends it.

	The Notification of Frappe has no Reply-To, so the header of the queued message is set here. The letter is
	found by its subject, which is the marker of the calculation.
	"""
	if doc.reference_doctype not in LETTERS or not doc.message:
		return
	message = email.message_from_string(doc.message, policy=policy.SMTP)
	subject = str(message.get("Subject") or "")
	if MARKER not in subject and SUBJECT_MARK not in subject:
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


@frappe.whitelist()
def make_payment_request(**args):
	"""Let the customer of a sales order pay it: the Pay button of the order page of the portal.

	ERPNext checks that the user may create a Payment Request and read the sales order, and no role of a portal
	user has those rights (the portal pages are opened by the link of the user to the customer, not by a role),
	so the button ends with Not permitted. For a sales order the call is allowed to the user whose customer owns
	the order (the rule of the portal pages) and runs as the administrator for the time of the call; for any
	other document the endpoint of ERPNext is called as it is.
	"""
	from erpnext.accounts.doctype.payment_request import payment_request
	from erpnext.controllers.website_list_for_contact import has_website_permission

	if args.get("dt") != "Sales Order" or not isinstance(args.get("dn"), str):
		return payment_request.make_payment_request(**args)

	order = frappe.get_doc("Sales Order", args["dn"])
	if not has_website_permission(order, "read", frappe.session.user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	user = frappe.session.user
	# the card is charged for this customer: without it ERPNext takes the owner of the order, who is the
	# administrator for a cart, and Stripe refuses "Administrator" as the e-mail of the payer
	args.setdefault("recipient_id", user)
	frappe.set_user("Administrator")
	try:
		return payment_request.make_payment_request(**args)
	finally:
		frappe.set_user(user)


def _payment_request_class():
	"""The class that the shop uses for a Payment Request (Webshop already replaces the one of ERPNext)."""
	from webshop.webshop.doctype.override_doctype.payment_request import PaymentRequest

	return PaymentRequest


class PaymentRequest(_payment_request_class()):
	"""A Payment Request whose payment is booked by the administrator.

	After a charge on Stripe the customer is the user of the session, and booking the payment (the Payment Entry)
	needs rights that a portal user does not have: the page ended with a message that the user may not select or
	read an account. ERPNext handles the guest in the same way (it books the payment as the administrator).
	"""

	def set_as_paid(self):
		user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			result = super().set_as_paid()
			send_payment_letter(self)
			return result
		finally:
			frappe.set_user(user)


def send_payment_letter(request):
	"""Mail the confirmation of a paid order; a failure of the letter never undoes the payment."""
	if request.get("reference_doctype") != "Sales Order" or not request.get("email_to"):
		return
	from fossdoc_shop.setup import PAYMENT_NOTIFICATION

	try:
		frappe.get_doc("Notification", PAYMENT_NOTIFICATION).send(request)
	except Exception:  # noqa: BLE001 - whatever goes wrong with a letter, the payment stays booked
		frappe.log_error(title="The letter of the payment was not sent")
