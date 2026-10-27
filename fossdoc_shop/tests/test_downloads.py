import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from lxml import etree

from fossdoc_shop import downloads, licensing
from fossdoc_shop.tests.seed import seed_settings, use_language


class TestDownloadLinks(FrappeTestCase):
	def test_the_version_of_a_release_is_read_from_its_code(self):
		self.assertEqual(downloads.version_of("FD-DL-7.4.32"), (7, 4, 32))
		self.assertGreater(downloads.version_of("FD-DL-7.10.1"), downloads.version_of("FD-DL-7.9.40"))
		self.assertIsNone(downloads.version_of("FD-MOD-audit"))

	def test_a_link_works_for_its_file_and_address_until_it_expires(self):
		now = time.time()
		expires = int(now + downloads.LINK_HOURS * 3600)
		signature = downloads.sign("F1", "A@x.org", expires)

		self.assertTrue(downloads.valid("F1", "a@x.org", expires, signature, now))
		self.assertFalse(downloads.valid("F2", "a@x.org", expires, signature, now))
		self.assertFalse(downloads.valid("F1", "b@x.org", expires, signature, now))
		self.assertFalse(downloads.valid("F1", "a@x.org", expires, signature, expires + 1))
		self.assertFalse(downloads.valid("F1", "a@x.org", expires, "", now))

	def test_a_request_with_a_filled_trap_field_creates_nothing(self):
		before = frappe.db.count("Lead")

		self.assertEqual(downloads.request_download("Bot", "bot@example.org", website="x"), {"sent": True})

		self.assertEqual(frappe.db.count("Lead"), before)

	def test_a_file_that_is_not_an_attachment_of_a_release_is_not_sent(self):
		expires = int(time.time() + 3600)
		with self.assertRaises(frappe.DoesNotExistError):
			downloads.download(
				"no-such-file", "a@x.org", expires, downloads.sign("no-such-file", "a@x.org", expires)
			)


class TestDemoLetter(FrappeTestCase):
	"""The form of the download: the links of the release and the demo licence for the name that was typed."""

	def setUp(self):
		from cryptography.hazmat.primitives.asymmetric import rsa

		from fossdoc_shop.tests.test_licensing import key_xml

		use_language(self)
		seed_settings(demo_users=5, demo_ecp_users=1, demo_months=6)
		key = key_xml(rsa.generate_private_key(public_exponent=65537, key_size=2048))
		self.originals = (licensing.license_version, licensing.license_key)
		licensing.license_version, licensing.license_key = (lambda: "7.4"), (lambda: key)
		release = {
			"code": "FD-DL-7.4.32",
			"version": (7, 4, 32),
			"notes": "",
			"files": [
				{"name": "F1", "file_name": "FossDoc_UA.exe", "file_url": "/private/files/x", "file_size": 1}
			],
		}
		patcher = patch.object(downloads, "current_release", return_value=release)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.email = "demo-letter@example.org"
		self.addCleanup(self.clean)

	def tearDown(self):
		licensing.license_version, licensing.license_key = self.originals

	def clean(self):
		for name in frappe.get_all("Lead", filters={"email_id": self.email}, pluck="name"):
			frappe.delete_doc("Lead", name, force=True)

	def request(self, organization="ТОВ Ромашка", name="Іван Петренко"):
		with patch("frappe.sendmail") as sendmail:
			downloads.request_download(name, self.email, lang="uk", organization=organization)
		return sendmail.call_args.kwargs

	def test_the_letter_carries_the_licence_for_the_typed_organisation_and_the_links(self):
		mail = self.request()

		(attachment,) = mail["attachments"]
		self.assertEqual(attachment["fname"], "License.xml")
		owner = etree.fromstring(attachment["fcontent"][3:]).findtext(
			f"{{{licensing.LICENSE_NS}}}Info/{{{licensing.LICENSE_NS}}}LicenseOwner"
		)
		self.assertEqual(owner, "ТОВ Ромашка")  # the organisation, not the name of the person
		self.assertIn("License.xml", mail["message"])
		self.assertIn("ТОВ Ромашка", mail["message"])
		self.assertIn("FossDoc_UA.exe", mail["message"])

	def test_a_second_request_gets_the_same_licence_and_the_lead_keeps_it(self):
		first = self.request()["attachments"][0]["fcontent"]
		second = self.request(organization="Інша організація", name="Інше Ім'я")["attachments"][0]["fcontent"]

		self.assertEqual(first, second)
		lead = frappe.db.get_value("Lead", {"email_id": self.email}, "name")
		self.assertEqual(
			frappe.db.count("File", {"attached_to_doctype": "Lead", "attached_to_name": lead}), 1
		)

	def test_the_organisation_is_required_and_goes_to_the_lead(self):
		with self.assertRaises(frappe.ValidationError):
			downloads.request_download("Іван Петренко", self.email, lang="uk", organization="  ")

		self.request()

		lead = frappe.db.get_value(
			"Lead", {"email_id": self.email}, ["company_name", "first_name"], as_dict=True
		)
		self.assertEqual((lead.company_name, lead.first_name), ("ТОВ Ромашка", "Іван"))

	def test_without_the_key_the_letter_has_the_links_and_no_licence(self):
		licensing.license_key = lambda: ""

		mail = self.request()

		self.assertIsNone(mail["attachments"])
		self.assertNotIn("License.xml", mail["message"])
		self.assertIn("FossDoc_UA.exe", mail["message"])
