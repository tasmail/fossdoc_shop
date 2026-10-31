"""Google reCAPTCHA v3 check of the public forms (the calculator, the demo download, the contact form).

The keys live in FossDoc Shop Settings (the deploy of the site fills them from the secrets of the repository). A site
without a secret refuses the forms, except in developer mode and in tests, so a missing key never opens the forms.
"""

import frappe
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password

SETTINGS = "FossDoc Shop Settings"
VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
DEFAULT_SCORE = 0.5
TIMEOUT = 5


def site_key() -> str:
	"""The public key that the pages load the script of Google with."""
	return frappe.db.get_single_value(SETTINGS, "recaptcha_site_key") or ""


def verify(token: str | None, action: str) -> None:
	"""Throw unless Google says the token is valid, was made for `action` and scores at least the threshold."""
	secret = get_decrypted_password(SETTINGS, SETTINGS, "recaptcha_secret", raise_exception=False)
	if not secret:
		if frappe.conf.developer_mode or frappe.flags.in_test:
			return
		frappe.throw(_("The check of the form is not configured"), frappe.ValidationError)
	if not token:
		frappe.throw(
			_("The check of the form failed. Reload the page and try again."), frappe.ValidationError
		)
	try:
		reply = requests.post(
			VERIFY_URL,
			data={"secret": secret, "response": token, "remoteip": frappe.local.request_ip or ""},
			timeout=TIMEOUT,
		).json()
	except (requests.RequestException, ValueError):
		frappe.throw(
			_("The check of the form is not available now. Try again later."), frappe.ValidationError
		)
	threshold = frappe.db.get_single_value(SETTINGS, "recaptcha_score") or DEFAULT_SCORE
	if not (reply.get("success") and reply.get("action") == action and reply.get("score", 0) >= threshold):
		frappe.throw(
			_("The check of the form failed. Reload the page and try again."), frappe.ValidationError
		)
