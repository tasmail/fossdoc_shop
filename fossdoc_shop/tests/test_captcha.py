from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop import captcha
from fossdoc_shop.api import recaptcha_site_key
from fossdoc_shop.tests.seed import seed_settings


def reply(**values):
	response = MagicMock()
	response.json.return_value = values
	return response


class TestCaptcha(FrappeTestCase):
	def setUp(self):
		seed_settings(recaptcha_site_key="public-key", recaptcha_secret="secret-key", recaptcha_score=0.5)

	def verify(self, response, token="token", action="calculation"):
		with patch("fossdoc_shop.captcha.requests.post", return_value=response) as post:
			captcha.verify(token, action)
		return post

	def test_a_good_score_for_the_right_action_passes_and_the_secret_goes_to_google(self):
		post = self.verify(reply(success=True, action="calculation", score=0.9))

		self.assertEqual(post.call_args.args[0], captcha.VERIFY_URL)
		self.assertEqual(post.call_args.kwargs["data"]["secret"], "secret-key")
		self.assertEqual(post.call_args.kwargs["data"]["response"], "token")

	def test_a_low_score_another_action_a_failure_or_no_token_is_refused(self):
		for response in (
			reply(success=True, action="calculation", score=0.1),
			reply(success=True, action="contact", score=0.9),
			reply(success=False, action="calculation", score=0.9),
		):
			with self.assertRaises(frappe.ValidationError):
				self.verify(response)
		with self.assertRaises(frappe.ValidationError):
			self.verify(reply(success=True, action="calculation", score=0.9), token="")

	def test_google_not_answering_closes_the_form(self):
		import requests

		with (
			patch("fossdoc_shop.captcha.requests.post", side_effect=requests.ConnectionError),
			self.assertRaises(frappe.ValidationError),
		):
			captcha.verify("token", "calculation")

	def test_without_a_secret_the_forms_are_refused_outside_developer_mode_and_tests(self):
		seed_settings(recaptcha_secret="")
		frappe.flags.in_test = False
		previous = frappe.conf.get("developer_mode")
		frappe.conf.developer_mode = 0
		self.addCleanup(frappe.conf.update, {"developer_mode": previous})

		with self.assertRaises(frappe.ValidationError):
			captcha.verify("token", "calculation")

		frappe.flags.in_test = True
		captcha.verify("", "calculation")  # a test run does not need the keys

	def test_the_public_key_is_served_to_the_pages(self):
		self.assertEqual(recaptcha_site_key(), {"site_key": "public-key"})

	def test_every_public_form_is_refused_without_a_token_once_the_keys_are_set(self):
		from fossdoc_shop.api import send_calculation
		from fossdoc_shop.downloads import request_download
		from fossdoc_shop.overrides import send_message
		from fossdoc_shop.tests.test_api import calculation

		with self.assertRaises(frappe.ValidationError):
			send_calculation("client@example.org", calculation())
		with self.assertRaises(frappe.ValidationError):
			request_download("Name Surname", "client@example.org", organization="Org")
		with self.assertRaises(frappe.ValidationError):
			send_message("client@example.org", "Hello")

	def test_a_filled_honeypot_is_answered_without_asking_google(self):
		from fossdoc_shop.downloads import request_download

		with patch("fossdoc_shop.captcha.requests.post") as post:
			self.assertEqual(
				request_download("Robot", "bot@example.org", website="http://spam"), {"sent": True}
			)

		post.assert_not_called()

	def test_a_token_made_on_another_host_is_refused(self):
		request = MagicMock()
		request.host = "www.fossdoc.com:443"
		request.headers = {}
		with patch.object(frappe.local, "request", request, create=True):
			self.verify(reply(success=True, action="calculation", score=0.9, hostname="www.fossdoc.com"))
			with self.assertRaises(frappe.ValidationError):
				self.verify(reply(success=True, action="calculation", score=0.9, hostname="evil.example"))
			with self.assertRaises(frappe.ValidationError):
				self.verify(reply(success=True, action="calculation", score=0.9))

	def test_the_public_name_is_accepted_behind_a_proxy_that_changes_the_host_header(self):
		request = MagicMock()
		request.host = "n1.internal"  # what the bench sees
		request.headers = {
			"X-Forwarded-Host": "www.fossdoc.com"
		}  # a header that a client can send: not trusted
		with patch.object(frappe.local, "request", request, create=True):
			with self.assertRaises(frappe.ValidationError):
				self.verify(reply(success=True, action="calculation", score=0.9, hostname="www.fossdoc.com"))
		request.headers = {"X-Frappe-Site-Name": "fossdocprod.erp-crm.org"}
		with patch.object(frappe.local, "request", request, create=True):
			self.verify(
				reply(success=True, action="calculation", score=0.9, hostname="fossdocprod.erp-crm.org")
			)
			with self.assertRaises(frappe.ValidationError):
				self.verify(reply(success=True, action="calculation", score=0.9, hostname="www.fossdoc.com"))

	def test_the_configured_host_name_a_port_a_trailing_dot_and_the_case_are_handled(self):
		request = MagicMock()
		request.host = "internal:8000"
		request.headers = {}
		with (
			patch.object(frappe.local, "request", request, create=True),
			patch.object(frappe.conf, "host_name", "https://WWW.fossdoc.com/", create=True),
		):
			self.verify(reply(success=True, action="calculation", score=0.9, hostname="www.fossdoc.com."))
		self.assertEqual(captcha._clean("[::1]:8000"), "[::1]")
		self.assertEqual(captcha._clean(None), "")

	def test_a_score_of_zero_is_a_setting_and_not_the_default(self):
		seed_settings(recaptcha_score=0)

		self.verify(reply(success=True, action="calculation", score=0))

	def test_an_answer_that_is_not_json_closes_the_form(self):
		response = MagicMock()
		response.json.side_effect = ValueError
		with self.assertRaises(frappe.ValidationError):
			self.verify(response)
