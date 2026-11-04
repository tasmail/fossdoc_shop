"""Hooks of the app: the e-mail of a calculation and the download of a PDF."""

import email
import traceback
from email import policy
from email.utils import formataddr

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from fossdoc_shop import captcha, payment_state
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

	ERPNext checks that the user may create a Payment Request and read the document, and no role of a portal
	user has those rights (the portal pages are opened by the link of the user to the customer, not by a role),
	so the button ends with Not permitted. For a sales order or a sales invoice the call is allowed to the user
	whose customer owns the document (the rule of the portal pages) and runs as the administrator for the time of
	the call; for any other document the endpoint of ERPNext is called as it is.

	A payment that is already in progress is never replaced. When the customer presses Pay again, ERPNext cancels
	the open Payment Request and makes a new one, and a customer who pays on the first page of the gateway has paid
	for a cancelled request. So, before ERPNext is called, the open requests of the document are looked at
	(payment_state.py): a payment that the bank is checking sends the customer back to the page of the document
	with a notice and starts nothing, and an open request of the same gateway account and of the amount still owed
	is not replaced: the customer goes to its payment page again (the same reference). Two presses at once are
	serialised by a lock of the database connection on the document (payment_state.document_lock): after getting it
	the transaction is ended, so that the reads that follow see the request that the first press committed, and
	the lock is released after the commit that follows the new request. A press that waits too long is told that
	the payment is in process. The stock code
	cancels open requests only for the order type Shopping Cart, so only that call is redirected; a call with
	loyalty points changes the amount, so while a payment is open it is refused with a message and not passed on.
	"""
	from erpnext.accounts.doctype.payment_request import payment_request
	from erpnext.controllers.website_list_for_contact import has_website_permission

	if args.get("dt") not in payment_state.DOCTYPES or not isinstance(args.get("dn"), str):
		return payment_request.make_payment_request(**args)

	order = frappe.get_doc(args["dt"], args["dn"])
	if not has_website_permission(order, "read", frappe.session.user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	user = frappe.session.user
	# the card is charged for this customer: without it ERPNext takes the owner of the order, who is the
	# administrator for a cart, and a gateway refuses "Administrator" as the e-mail of the payer
	args.setdefault("recipient_id", user)
	frappe.set_user("Administrator")
	try:
		with payment_state.document_lock(order.doctype, order.name) as got:
			if not got:  # the other press is still at work: it is not an error, the payment is in process
				frappe.local.response["type"] = "redirect"
				frappe.local.response["location"] = payment_state.order_page_url(order.doctype, order.name)
				return None
			# nothing has been written: end the transaction so that the next reads (ours and the ones of ERPNext)
			# start a new snapshot and see the request that the other press has committed
			frappe.db.commit()
			if _payment_in_progress(payment_request, order, args):
				return None
			result = payment_request.make_payment_request(**args)
			frappe.db.commit()  # before the lock is released
			return result
	finally:
		frappe.set_user(user)


def _payment_in_progress(payment_request, order, args) -> bool:
	"""Send the customer to the payment that is already in progress; False when a new request may be made.

	The answer is a redirect, like the one of ERPNext to the gateway: to the page of the document, which says that
	the bank is checking the payment, or to the payment page of the open request.
	"""
	account = payment_state.gateway_account(args.get("company") or order.company, args)
	if args.get("loyalty_points"):
		state = payment_state.state_of(order.doctype, order.name)
		if state:
			frappe.throw(payment_state.message(state))
		return False
	if args.get("order_type") != "Shopping Cart":
		return False
	amount = payment_request.get_amount(order, account.get("payment_account"))
	state = payment_state.state_of(order.doctype, order.name, amount, account.get("name"))
	if not state:
		return False
	frappe.local.response["type"] = "redirect"
	if state["state"] == payment_state.PROCESSING:
		frappe.local.response["location"] = payment_state.order_page_url(order.doctype, order.name)
	else:
		frappe.local.response["location"] = payment_state.page_url(state)
	frappe.db.commit()  # the page of a new payment of the open request is an Integration Request that stays
	return True


def _customer_class():
	from erpnext.selling.doctype.customer.customer import Customer

	return Customer


def _payment_request_class():
	"""The class that the shop uses for a Payment Request (Webshop already replaces the one of ERPNext)."""
	from webshop.webshop.doctype.override_doctype.payment_request import PaymentRequest

	return PaymentRequest


class PaymentRequest(_payment_request_class()):
	"""A Payment Request whose payment is booked by the administrator.

	After a charge at the gateway the customer is the user of the session, and booking the payment (the Payment Entry)
	needs rights that a portal user does not have: the page ended with a message that the user may not select or
	read an account. ERPNext handles the guest in the same way (it books the payment as the administrator).
	"""

	def set_as_paid(self):
		user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			result = super().set_as_paid()
			issue_license(self)
			send_payment_letter(self)
			return result
		finally:
			frappe.set_user(user)


LINK_FUNCTION = "link_portal_users_to_contacts"


def _failed_in_link(error):
	"""True when the conflict was raised by the step that links the contacts of the portal users."""
	return any(frame.name == LINK_FUNCTION for frame in traceback.extract_tb(error.__traceback__))


def link_portal_contacts(customer):
	"""Link the contacts of the portal users of a customer: the step of ERPNext, run in a background job.

	The job reads the Contact in a transaction of its own, so it sees the change that made the first try fail. A conflict
	again raises RetryBackgroundJobError (Frappe retries the job, and logs an error only after the last try). The step
	adds only the links that are missing, so running it twice or for a customer with nothing to do changes nothing.
	"""
	from erpnext.controllers.website_list_for_contact import link_portal_users_to_contacts

	if not frappe.db.exists("Customer", customer):
		return
	try:
		link_portal_users_to_contacts(frappe.get_doc("Customer", customer))
	except frappe.TimestampMismatchError:
		raise frappe.RetryBackgroundJobError from None


class Customer(_customer_class()):
	"""A Customer whose last step, the link to the contacts of its portal users, never ends the request in an error.

	The step (link_portal_users_to_contacts of ERPNext, called by Customer.on_update) opens the Contact of the user
	and saves it with the link to the Customer. A new customer who signs up has that Contact written at the same
	moment by the job that User.on_update queues (create_contact), so the save can end in "Document has been modified
	after you have opened it" (TimestampMismatchError), and reading the Contact again in the same transaction does not
	help. That is a race, not a failure: the conflict is cleared and the step is queued as a job that runs after the
	commit (link_portal_contacts). Nothing is logged for it; a job that still conflicts after Frappe's retries logs
	its own error. A conflict raised by any other step is logged, as before, and the customer goes on.
	"""

	def on_update(self):
		try:
			super().on_update()
		except frappe.TimestampMismatchError as error:
			frappe.clear_last_message()
			if _failed_in_link(error):
				frappe.enqueue(
					"fossdoc_shop.overrides.link_portal_contacts",
					queue="short",
					customer=self.name,
					job_id=f"link_portal_contacts::{frappe.local.site}::{self.name}",
					deduplicate=True,
					enqueue_after_commit=True,
				)
				return
			frappe.log_error(
				title="Customer: the contacts of the portal users were not linked",
				message=frappe.get_traceback(),
				reference_doctype="Customer",
				reference_name=self.name,
			)


def send_payment_letter(request):
	"""Mail the confirmation of a paid order; a failure of the letter never undoes the payment.

	The text is the one of the Notification of the shop (the managers edit it in the desk). The letter carries
	the PDF of the confirmation and, when the order has one, the licence of the server as an attachment.
	"""
	if request.get("reference_doctype") != "Sales Order" or not request.get("email_to"):
		return
	from fossdoc_shop import licensing
	from fossdoc_shop.setup import PAYMENT_NOTIFICATION

	# the letter is made in the language of the order (the language that the buyer chose on the site)
	previous = frappe.local.lang
	frappe.local.lang = frappe.db.get_value("Sales Order", request.reference_name, "language") or previous
	try:
		notification = frappe.get_doc("Notification", PAYMENT_NOTIFICATION)
		context = {"doc": request}
		data = brand()
		attachments = []
		if notification.attach_print:
			attachments.append(
				frappe.attach_print(
					request.doctype, request.name, print_format=notification.print_format, doc=request
				)
			)
		licence_file = licensing.issued_file(request.reference_name)
		if licence_file:
			file = frappe.get_doc("File", licence_file)
			attachments.append({"fname": licensing.LICENSE_FILE, "fcontent": file.get_content()})
		frappe.sendmail(
			recipients=[request.email_to],
			cc=[data["cc"]] if data["cc"] else None,
			subject=frappe.render_template(notification.subject, context),
			message=frappe.render_template(notification.message, context),
			attachments=attachments,
			reference_doctype=request.doctype,
			reference_name=request.name,
			now=True,
		)
	except Exception:  # noqa: BLE001 - whatever goes wrong with a letter, the payment stays booked
		frappe.log_error(title="The letter of the payment was not sent")
	finally:
		frappe.local.lang = previous


def issue_license(request):
	"""Make the licence of a paid order before its letter is written; a failure only leaves the order to a manager."""
	if request.get("reference_doctype") != "Sales Order" or not request.get("reference_name"):
		return
	from fossdoc_shop import licensing

	try:
		licensing.issue_for_order(request.reference_name)
	except Exception:  # noqa: BLE001
		frappe.log_error(title="The licence of the order was not made")


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=100, seconds=60 * 60)
def send_message(sender: str, message: str, subject: str = "Website Query", recaptcha_token: str = ""):
	"""The contact form of the site: the stock send_message of Frappe after the check of reCAPTCHA."""
	from frappe.www.contact import send_message as stock

	captcha.verify(recaptcha_token, "contact")
	return stock(sender, message, subject)
