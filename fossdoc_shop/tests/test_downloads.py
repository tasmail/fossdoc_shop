import time

import frappe
from frappe.tests.utils import FrappeTestCase

from fossdoc_shop import downloads


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
