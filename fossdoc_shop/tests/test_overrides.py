from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.calculation import MARKER
from fossdoc_shop.overrides import _clean, download_pdf, make_payment_request, set_reply_to
from fossdoc_shop.tests.seed import seed_settings

MIME = "From: ERP CRM <noreply@example.org>\nTo: a@example.org\nSubject: {subject}\nReply-To: noreply@example.org\n\nbody\n"


def queue(subject, doctype="Communication"):
	return frappe._dict(reference_doctype=doctype, message=MIME.format(subject=subject))


class TestSetReplyTo(FrappeTestCase):
	def test_the_letter_with_a_calculation_gets_the_reply_to_of_sales(self):
		seed_settings()
		doc = queue(MARKER)

		set_reply_to(doc)

		self.assertIn("Reply-To:", doc.message)
		self.assertIn("sales@test.example", doc.message)
		self.assertNotIn("noreply@example.org\n\nbody", doc.message)

	def test_other_mail_is_left_alone(self):
		other = queue("Password reset")
		wrong_doctype = queue(MARKER, doctype="User")

		set_reply_to(other)
		set_reply_to(wrong_doctype)

		self.assertEqual(other.message, MIME.format(subject="Password reset"))
		self.assertEqual(wrong_doctype.message, MIME.format(subject=MARKER))


class TestDownloadPdf(FrappeTestCase):
	def test_the_word_none_that_the_print_page_writes_into_the_address_is_no_value(self):
		for word in ("None", "none", "null", "", " None "):
			self.assertIsNone(_clean(word), word)
		self.assertEqual(_clean("Standard"), "Standard")
		self.assertEqual(_clean(None), None)

	def test_the_endpoint_of_frappe_gets_clean_values_when_the_page_sends_none(self):
		with patch("frappe.utils.print_format.download_pdf") as original:
			download_pdf(
				"Quotation",
				"QTN-1",
				format="Standard",
				no_letterhead="None",
				letterhead="None",
				language="uk",
			)

		original.assert_called_once_with(
			"Quotation",
			"QTN-1",
			format="Standard",
			doc=None,
			no_letterhead=0,
			language="uk",
			letterhead=None,
			pdf_generator=None,
		)

	def test_a_real_request_for_no_letterhead_is_kept(self):
		with patch("frappe.utils.print_format.download_pdf") as original:
			download_pdf("Quotation", "QTN-1", no_letterhead="1")

		self.assertEqual(original.call_args.kwargs["no_letterhead"], 1)

	def test_the_hook_points_at_the_override(self):
		from fossdoc_shop import hooks

		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.utils.print_format.download_pdf"],
			"fossdoc_shop.overrides.download_pdf",
		)
		self.assertIs(frappe.get_attr("fossdoc_shop.overrides.download_pdf"), download_pdf)


class TestMakePaymentRequest(FrappeTestCase):
	def run_it(self, allowed, **args):
		"""Call the override with the endpoint of ERPNext and the rule of the portal replaced; returns the doubles."""
		order = MagicMock()
		with (
			patch("frappe.get_doc", return_value=order) as get_doc,
			patch(
				"erpnext.controllers.website_list_for_contact.has_website_permission", return_value=allowed
			) as rule,
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request"
			) as original,
		):
			users = []
			original.side_effect = lambda **kw: users.append(frappe.session.user) or "PR"
			try:
				result = make_payment_request(**args)
			except frappe.PermissionError:
				result = "refused"
		return result, original, rule, get_doc, users

	def test_the_customer_of_the_order_pays_it_and_the_endpoint_of_erpnext_runs_with_the_rights_it_needs(
		self,
	):
		frappe.set_user("Administrator")
		with patch.object(frappe.local.session, "user", "customer@example.org"):
			result, original, rule, get_doc, users = self.run_it(
				True, dt="Sales Order", dn="SAL-1", submit_doc=1
			)

		self.assertEqual(result, "PR")
		original.assert_called_once_with(dt="Sales Order", dn="SAL-1", submit_doc=1)
		self.assertEqual(users, ["Administrator"])  # the rights of the endpoint of ERPNext
		rule.assert_called_once()

	def test_somebody_else_cannot_pay_the_order_and_the_endpoint_is_not_called(self):
		result, original, rule, get_doc, users = self.run_it(False, dt="Sales Order", dn="SAL-1")

		self.assertEqual(result, "refused")
		original.assert_not_called()

	def test_other_documents_go_to_the_endpoint_of_erpnext_as_they_are(self):
		result, original, rule, get_doc, users = self.run_it(False, dt="Sales Invoice", dn="SINV-1")

		self.assertEqual(result, "PR")
		original.assert_called_once_with(dt="Sales Invoice", dn="SINV-1")
		rule.assert_not_called()

	def test_the_hook_points_at_the_override(self):
		from fossdoc_shop import hooks

		self.assertEqual(
			hooks.override_whitelisted_methods[
				"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request"
			],
			"fossdoc_shop.overrides.make_payment_request",
		)
