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
	def run_it(self, allowed, state=None, **args):
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
			patch("erpnext.accounts.doctype.payment_request.payment_request.get_gateway_details"),
			patch("erpnext.accounts.doctype.payment_request.payment_request.get_amount", return_value=45.67),
			patch("fossdoc_shop.overrides.payment_state.state_of", return_value=state),
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

	def test_a_payment_in_the_hands_of_the_bank_starts_nothing_and_goes_back_to_the_order_page(self):
		frappe.local.response = frappe._dict()
		state = {"state": "processing", "request": "PRQ-1", "irequest": None}

		done = self.run_it(True, state, dt="Sales Order", dn="SAL-1", order_type="Shopping Cart")

		self.assertIsNone(done.result)
		done.original.assert_not_called()  # ERPNext would cancel the open request
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertTrue(frappe.local.response["location"].endswith("/orders/SAL-1?payment=processing"))

	def test_an_open_request_is_not_replaced_and_the_customer_goes_to_its_payment_page(self):
		frappe.local.response = frappe._dict()
		state = {"state": "continue", "request": "PRQ-1", "irequest": "WFP-1"}

		done = self.run_it(True, state, dt="Sales Order", dn="SAL-1", order_type="Shopping Cart")

		self.assertIsNone(done.result)
		done.original.assert_not_called()
		self.assertTrue(frappe.local.response["location"].endswith("/wayforpay_checkout?order=WFP-1"))

	def test_without_a_payment_in_progress_erpnext_makes_the_request(self):
		done = self.run_it(True, None, dt="Sales Order", dn="SAL-1", order_type="Shopping Cart")

		self.assertEqual(done.result, "PR")
		done.original.assert_called_once()

	def test_the_check_is_for_the_cart_only_and_not_for_loyalty_points(self):
		state = {"state": "processing", "request": "PRQ-1", "irequest": None}

		done = self.run_it(
			True, state, dt="Sales Order", dn="SAL-1", order_type="Shopping Cart", loyalty_points=5
		)

		self.assertEqual(done.result, "PR")  # the amount differs, the stock rules apply
		self.assertEqual(self.run_it(True, state, dt="Sales Order", dn="SAL-1").result, "PR")

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


class TestCustomerContactConflict(FrappeTestCase):
	def test_a_conflict_while_linking_the_portal_users_is_logged_and_does_not_end_the_request(self):
		from unittest.mock import patch

		from erpnext.selling.doctype.customer.customer import Customer as ErpnextCustomer

		from fossdoc_shop import overrides

		customer = overrides.Customer({"doctype": "Customer", "customer_name": "Conflict Test"})

		with (
			patch.object(ErpnextCustomer, "on_update", side_effect=frappe.TimestampMismatchError),
			patch.object(frappe, "log_error") as log,
		):
			customer.on_update()

		log.assert_called_once()

	def test_a_conflict_in_the_link_step_is_queued_again_and_is_not_an_error(self):
		from erpnext.selling.doctype.customer.customer import Customer as ErpnextCustomer

		from fossdoc_shop import overrides

		def link_portal_users_to_contacts(*args):
			raise frappe.TimestampMismatchError

		customer = overrides.Customer({"doctype": "Customer", "customer_name": "Conflict Test"})
		customer.name = "CUST-CONFLICT"

		with (
			patch.object(
				ErpnextCustomer,
				"on_update",
				side_effect=lambda *args: link_portal_users_to_contacts(),
			),
			patch.object(frappe, "log_error") as log,
			patch.object(frappe, "enqueue") as enqueue,
		):
			customer.on_update()

		log.assert_not_called()
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args, ("fossdoc_shop.overrides.link_portal_contacts",))
		self.assertEqual(enqueue.call_args.kwargs["customer"], "CUST-CONFLICT")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertTrue(enqueue.call_args.kwargs["deduplicate"])

	def test_the_job_links_the_contacts_and_does_nothing_for_a_missing_customer(self):
		from fossdoc_shop import overrides

		with (
			patch("erpnext.controllers.website_list_for_contact.link_portal_users_to_contacts") as link,
			patch.object(frappe.db, "exists", return_value=False),
		):
			overrides.link_portal_contacts("CUST-GONE")
		link.assert_not_called()

		with (
			patch("erpnext.controllers.website_list_for_contact.link_portal_users_to_contacts") as link,
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value="DOC"),
		):
			overrides.link_portal_contacts("CUST-1")
			overrides.link_portal_contacts("CUST-1")  # idempotent: the step only adds the missing links
		self.assertEqual(link.call_count, 2)
		link.assert_called_with("DOC")

	def test_a_conflict_in_the_job_asks_frappe_to_retry_it(self):
		from fossdoc_shop import overrides

		with (
			patch(
				"erpnext.controllers.website_list_for_contact.link_portal_users_to_contacts",
				side_effect=frappe.TimestampMismatchError,
			),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value="DOC"),
			self.assertRaises(frappe.RetryBackgroundJobError),
		):
			overrides.link_portal_contacts("CUST-1")

	def test_the_class_of_the_customer_is_the_one_of_the_app(self):
		from fossdoc_shop import overrides

		doc = frappe.get_doc({"doctype": "Customer", "customer_name": "Class Test"})
		self.assertIs(doc.__class__, overrides.Customer)
