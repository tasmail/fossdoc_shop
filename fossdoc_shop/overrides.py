"""Hooks on the e-mail of the app."""

import email
from email import policy
from email.utils import formataddr

from fossdoc_shop.branding import requisites
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
	data = requisites()
	del message["Reply-To"]
	message["Reply-To"] = formataddr((data["company"], data["email"]))
	doc.message = message.as_string()
