from types import SimpleNamespace
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
		"""Call the override with the endpoint of ERPNext and the rule of the portal replaced by doubles."""
		users = []
		with (
			patch("frappe.get_doc", return_value=MagicMock()),
			patch(
				"erpnext.controllers.website_list_for_contact.has_website_permission", return_value=allowed
			) as rule,
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request"
			) as original,
		):
			original.side_effect = lambda **kw: users.append(frappe.session.user) or "PR"
			try:
				result = make_payment_request(**args)
			except frappe.PermissionError:
				result = "refused"
		return SimpleNamespace(result=result, original=original, rule=rule, users=users)

	def test_the_customer_of_the_order_pays_it_and_the_endpoint_of_erpnext_runs_with_the_rights_it_needs(
		self,
	):
		frappe.set_user("customer@example.org")
		self.addCleanup(frappe.set_user, "Administrator")

		done = self.run_it(True, dt="Sales Order", dn="SAL-1", submit_doc=1)

		self.assertEqual(done.result, "PR")
		# the payer is the customer and not the owner of the order (the administrator for a cart)
		done.original.assert_called_once_with(
			dt="Sales Order", dn="SAL-1", submit_doc=1, recipient_id="customer@example.org"
		)
		self.assertEqual(done.users, ["Administrator"])  # the rights of the endpoint of ERPNext
		self.assertEqual(frappe.session.user, "customer@example.org")  # and the session is given back
		done.rule.assert_called_once()

	def test_somebody_else_cannot_pay_the_order_and_the_endpoint_is_not_called(self):
		done = self.run_it(False, dt="Sales Order", dn="SAL-1")

		self.assertEqual(done.result, "refused")
		done.original.assert_not_called()

	def test_other_documents_go_to_the_endpoint_of_erpnext_as_they_are(self):
		done = self.run_it(False, dt="Sales Invoice", dn="SINV-1")

		self.assertEqual(done.result, "PR")
		done.original.assert_called_once_with(dt="Sales Invoice", dn="SINV-1")
		done.rule.assert_not_called()

	def test_the_hook_points_at_the_override(self):
		from fossdoc_shop import hooks

		self.assertEqual(
			hooks.override_whitelisted_methods[
				"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request"
			],
			"fossdoc_shop.overrides.make_payment_request",
		)


class TestPaymentRequestClass(FrappeTestCase):
	def test_the_class_of_the_shop_replaces_the_one_of_webshop_in_the_hooks(self):
		from webshop.webshop.doctype.override_doctype.payment_request import PaymentRequest as Webshop

		from fossdoc_shop import hooks
		from fossdoc_shop.overrides import PaymentRequest

		self.assertTrue(issubclass(PaymentRequest, Webshop))
		self.assertEqual(
			hooks.override_doctype_class["Payment Request"], "fossdoc_shop.overrides.PaymentRequest"
		)
		self.assertIn(
			"fossdoc_shop.overrides.PaymentRequest",
			frappe.get_hooks("override_doctype_class")["Payment Request"],
		)
		# the last app wins, so the shop has to be installed after Webshop: it says so
		self.assertIn("webshop", hooks.required_apps)

	def test_the_payment_is_booked_by_the_administrator_and_the_session_is_given_back(self):
		from fossdoc_shop.overrides import PaymentRequest

		users = []
		request = PaymentRequest.__new__(PaymentRequest)
		frappe.set_user("customer@example.org")
		self.addCleanup(frappe.set_user, "Administrator")

		with patch.object(
			PaymentRequest.__mro__[1], "set_as_paid", lambda self: users.append(frappe.session.user) or "paid"
		):
			result = request.set_as_paid()

		self.assertEqual((result, users), ("paid", ["Administrator"]))
		self.assertEqual(frappe.session.user, "customer@example.org")

	def test_the_session_is_given_back_when_the_booking_fails(self):
		from fossdoc_shop.overrides import PaymentRequest

		def fail(self):
			raise ValueError("no")

		request = PaymentRequest.__new__(PaymentRequest)
		frappe.set_user("customer@example.org")
		self.addCleanup(frappe.set_user, "Administrator")

		with patch.object(PaymentRequest.__mro__[1], "set_as_paid", fail), self.assertRaises(ValueError):
			request.set_as_paid()

		self.assertEqual(frappe.session.user, "customer@example.org")


class TestCustomerContactRetry(FrappeTestCase):
	def test_a_stale_contact_while_linking_the_portal_users_is_retried_once_with_a_fresh_read(self):
		from unittest.mock import patch

		from erpnext.selling.doctype.customer.customer import Customer as ErpnextCustomer

		from fossdoc_shop import overrides

		customer = overrides.Customer({"doctype": "Customer", "customer_name": "Retry Test"})

		with (
			patch.object(ErpnextCustomer, "on_update", side_effect=frappe.TimestampMismatchError),
			patch.object(overrides, "link_portal_users_to_contacts") as link,
		):
			customer.on_update()

		link.assert_called_once_with(customer)

	def test_the_class_of_the_customer_is_the_one_of_the_app(self):
		self.assertIs(
			frappe.get_doc({"doctype": "Customer", "customer_name": "Class Test"}).__class__,
			__import__("fossdoc_shop.overrides", fromlist=["Customer"]).Customer,
		)
