from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop.calculation import MARKER
from fossdoc_shop.overrides import _clean, download_pdf, set_reply_to
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
