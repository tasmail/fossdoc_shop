"""The whole way of a calculation: the endpoint of the app, the Notification, the mail queue, the SMTP server.

The dev bench has a mail catcher (Mailpit, `mailpit:8025`); without it the test is skipped.
"""

import json
import unittest
import urllib.request

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.api import send_calculation
from fossdoc_shop.calculation import MARKER
from fossdoc_shop.setup import NOTIFICATION, ensure_calculation_mail

MAILPIT = "http://mailpit:8025/api/v1"


def mailpit(path, method="GET"):
	request = urllib.request.Request(MAILPIT + path, method=method)
	with urllib.request.urlopen(request, timeout=5) as response:
		data = response.read()
	return json.loads(data) if method == "GET" else None


class TestMailEndToEnd(FrappeTestCase):
	def setUp(self):
		try:
			mailpit("/messages", "DELETE")
		except OSError:
			raise unittest.SkipTest("the mail catcher of the dev bench is not reachable")
		self.use_the_mail_catcher()
		frappe.flags.testing_email = True  # Frappe does not send mail in tests unless told to
		self.addCleanup(setattr, frappe.flags, "testing_email", False)
		frappe.delete_doc("Notification", NOTIFICATION, force=True)  # a fresh one, as an install makes it
		ensure_calculation_mail()

	@staticmethod
	def use_the_mail_catcher():
		"""The default outgoing account of the dev site sends to Mailpit (no TLS, no login)."""
		values = {
			"email_id": "noreply@fossdoc.test",
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"smtp_server": "mailpit",
			"smtp_port": 1025,
			"use_tls": 0,
			"use_ssl_for_outgoing": 0,
			"always_use_account_email_id_as_sender": 1,
		}
		if frappe.db.exists("Email Account", "Dev Mail Catcher"):
			doc = frappe.get_doc("Email Account", "Dev Mail Catcher")
			doc.update(values)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{"doctype": "Email Account", "email_account_name": "Dev Mail Catcher", **values}
			).insert(ignore_permissions=True)

	def test_a_calculation_sent_from_the_site_arrives_as_a_letter_with_the_pdf_offer(self):
		body = {
			"lang": "uk",
			"total": 200,
			"lines": [{"code": "resolution", "name": "Резолюції", "qty": 2, "unit": 100, "total": 200}],
		}
		frappe.set_user("Guest")
		try:
			send_calculation(
				sender="client@example.org", message=f"{MARKER}\n{json.dumps(body, ensure_ascii=False)}"
			)
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()

		from frappe.email.queue import flush

		flush()
		messages = mailpit("/messages")["messages"]
		# the same finished letter goes to the client and (Cc) to sales: one message for each address, and nothing
		# else (no raw forward of the text)
		self.assertEqual(len(messages), 2, [(m["To"][0]["Address"], m["Subject"]) for m in messages])
		for item in messages:
			self.assertEqual(item["To"][0]["Address"], "client@example.org")
			self.assertEqual([c["Address"] for c in item["Cc"]], ["sales@foss.ua"])
			self.assertEqual(item["Attachments"], 1)
		letters = messages
		letter = mailpit(f"/message/{letters[0]['ID']}")
		self.assertIn("Резолюції", letter["HTML"])
		self.assertIn("$ 200.00", letter["HTML"])
		self.assertEqual([a["ContentType"] for a in letter["Attachments"]], ["application/pdf"])
