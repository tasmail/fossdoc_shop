import base64
import hashlib
from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from lxml import etree

from fossdoc_shop import licensing


def key_xml(private_key) -> str:
	"""A test key in the format of .NET (RSAKeyValue)."""
	numbers = private_key.private_numbers()

	def part(value):
		return base64.b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode()

	return (
		f"<RSAKeyValue><Modulus>{part(numbers.public_numbers.n)}</Modulus><Exponent>AQAB</Exponent>"
		f"<P>{part(numbers.p)}</P><Q>{part(numbers.q)}</Q><DP>{part(numbers.dmp1)}</DP>"
		f"<DQ>{part(numbers.dmq1)}</DQ><InverseQ>{part(numbers.iqmp)}</InverseQ><D>{part(numbers.d)}</D></RSAKeyValue>"
	)


def lines(*pairs):
	return [{"item_code": code, "qty": qty} for code, qty in pairs]


class TestLicenceOfAnOrder(FrappeTestCase):
	def test_the_users_the_modules_and_the_signature_users_come_from_the_lines(self):
		spec = licensing.spec_from_lines(
			lines(
				("FD-MOD-fosslook-platform", 1),
				("FD-MOD-storage", 1),
				("FD-MOD-resolution", 1),
				("FD-MOD-audit", 1),
				("FD-DB-mysql", 1),
				("FD-SEAT", 20),
				("FD-ECP-Bitis", 1),
				("FD-ECP-SEAT", 5),
				("FD-SRV-INSTALL", 1),
			),
			"ТОВ Тест",
			"7.4",
		)

		self.assertEqual((spec.users, spec.ecp_users, spec.version), (20, 5, "7.4"))
		self.assertEqual(spec.tags, ["EDMS_Resolutions", "EventLogger", "EDMS_DigitalSignature"])

	def test_a_rental_a_module_without_an_element_and_an_order_without_seats_are_left_to_a_manager(self):
		base = [("FD-MOD-fosslook-platform", 1), ("FD-SEAT", 3)]
		self.assertIsNone(licensing.spec_from_lines(lines(*base, ("FD-RENT-SEAT", 3)), "x", "7.4"))
		self.assertIsNone(licensing.spec_from_lines(lines(*base, ("FD-MOD-sev", 1)), "x", "7.4"))
		self.assertIsNone(licensing.spec_from_lines(lines(("FD-MOD-history", 1)), "x", "7.4"))
		self.assertIsNone(licensing.spec_from_lines(lines(*base, ("OTHER-ITEM", 1)), "x", "7.4"))

	def test_the_licence_is_signed_the_way_the_server_checks_it(self):
		from cryptography.hazmat.primitives import hashes
		from cryptography.hazmat.primitives.asymmetric import padding, rsa

		private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		spec = licensing.Spec(owner="ТОВ Тест", users=10, version="7.4", ecp_users=2, tags=["History"])

		data = licensing.generate(spec, key_xml(private_key), "ad1b64ca-1a2e-4f5e-b0f2-5c77c73c5025")

		self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
		root = etree.fromstring(data[3:], etree.XMLParser(remove_blank_text=True))  # as .NET loads a file
		ns = {"l": licensing.LICENSE_NS, "d": licensing.DSIG_NS}
		self.assertEqual(root.findtext("l:MaxUserAccounts", namespaces=ns), "10")
		self.assertEqual(root.findtext("l:Info/l:DigitalSignatureUsersCount", namespaces=ns), "2")
		self.assertEqual(root.findtext("l:Info/l:History", namespaces=ns), "true")
		signature = root.find("d:Signature", ns)
		value = base64.b64decode(signature.findtext("d:SignatureValue", namespaces=ns))
		canonical = etree.tostring(signature.find("d:SignedInfo", ns), method="c14n")
		private_key.public_key().verify(value, canonical, padding.PKCS1v15(), hashes.SHA1())
		digest = signature.findtext("d:SignedInfo/d:Reference/d:DigestValue", namespaces=ns)
		root.remove(signature)
		self.assertEqual(
			digest, base64.b64encode(hashlib.sha1(etree.tostring(root, method="c14n")).digest()).decode()
		)

	def test_an_order_without_the_key_has_no_licence(self):
		order = frappe._dict(
			items=[frappe._dict(item_code="FD-SEAT", qty=3)], customer_name="x", customer="x"
		)
		original = (licensing.license_version, licensing.license_key)
		licensing.license_version, licensing.license_key = (lambda: "7.4"), (lambda: "")
		try:
			self.assertIsNone(licensing.order_spec(order))
		finally:
			licensing.license_version, licensing.license_key = original

	def test_a_key_that_came_back_escaped_is_read_again_as_xml(self):
		class FakeSettings:
			def get(self, name):
				return "7.4"

			def get_password(self, name, raise_exception=True):
				return "&lt;RSAKeyValue&gt;&lt;Modulus&gt;AQAB&lt;/Modulus&gt;&lt;/RSAKeyValue&gt;"

		original = licensing.settings
		licensing.settings = FakeSettings
		try:
			self.assertEqual(licensing.license_key(), "<RSAKeyValue><Modulus>AQAB</Modulus></RSAKeyValue>")
		finally:
			licensing.settings = original

	def test_a_key_that_frappe_escaped_and_lower_cased_still_signs_the_same_way(self):
		import html
		import re

		from cryptography.hazmat.primitives.asymmetric import rsa

		private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		original = key_xml(private_key)
		# what was found on the site: angle brackets escaped, <P> and <Q> written as <p> and <q>
		saved = html.escape(
			re.sub(r"<(/?)([PQ])>", lambda m: f"<{m.group(1)}{m.group(2).lower()}>", original)
		)
		self.assertIn("&lt;p&gt;", saved)
		spec = licensing.Spec(owner="Test", users=3, version="7.4")

		fixed = licensing.generate(spec, html.unescape(saved), "11111111-2222-3333-4444-555555555555")
		clean = licensing.generate(spec, original, "11111111-2222-3333-4444-555555555555")

		self.assertEqual(fixed, clean)  # RSA PKCS#1 v1.5 is deterministic: the same key gives the same bytes

	def test_a_key_with_a_missing_part_is_refused_with_its_name(self):
		with self.assertRaisesRegex(ValueError, "inverseq"):
			licensing.load_private_key(
				"<RSAKeyValue><Modulus>AQAB</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>"
			)


class TestIssueForOrder(FrappeTestCase):
	"""The whole way of an order: the settings, the lines, the file attached to the order, the terms."""

	def setUp(self):
		from cryptography.hazmat.primitives.asymmetric import rsa

		self.key = key_xml(rsa.generate_private_key(public_exponent=65537, key_size=2048))
		self.originals = (licensing.license_version, licensing.license_key)
		licensing.license_version, licensing.license_key = (lambda: "7.4"), (lambda: self.key)

	def tearDown(self):
		licensing.license_version, licensing.license_key = self.originals

	def make_order(self, items):
		customer = frappe.get_all("Customer", limit=1, pluck="name")
		if not customer:
			self.skipTest("the site has no customer to make an order for")
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": customer[0],
				"delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
				"items": [
					{
						"item_code": code,
						"qty": qty,
						"rate": 1,
						"delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
					}
					for code, qty in items
				],
			}
		)
		order.flags.ignore_mandatory = True
		order.insert(ignore_permissions=True)
		return order

	def test_a_paid_order_gets_a_private_licence_file_and_its_parameters_in_the_terms(self):
		for code in ("FD-SEAT", "FD-MOD-fosslook-platform", "FD-MOD-storage"):
			if not frappe.db.exists("Item", code):
				self.skipTest(f"the site has no item {code}")
		order = self.make_order([("FD-MOD-fosslook-platform", 1), ("FD-MOD-storage", 1), ("FD-SEAT", 7)])

		name = licensing.issue_for_order(order.name)

		file = frappe.get_doc("File", name)
		self.assertTrue(file.is_private)
		self.assertEqual((file.attached_to_doctype, file.attached_to_name), ("Sales Order", order.name))
		self.assertIn(b"<MaxUserAccounts>7</MaxUserAccounts>", file.get_content())
		self.assertIn("Користувачів: 7", frappe.db.get_value("Sales Order", order.name, "terms"))
		self.assertEqual(licensing.issue_for_order(order.name), name)  # a second call makes no second licence

	def test_a_rental_gets_no_licence(self):
		if not frappe.db.exists("Item", "FD-RENT-SEAT"):
			self.skipTest("the site has no rental item")
		order = self.make_order([("FD-RENT-SEAT", 3)])

		self.assertIsNone(licensing.issue_for_order(order.name))
		self.assertFalse(
			licensing.license_info(frappe._dict(reference_doctype="Sales Order", reference_name=order.name))[
				"issued"
			]
		)


class TestDemoLicence(FrappeTestCase):
	"""The licence that the form of the demo download mails: the one of the sample of the old generator."""

	def setUp(self):
		from cryptography.hazmat.primitives.asymmetric import rsa

		from fossdoc_shop.tests.seed import seed_settings

		seed_settings(demo_users=5, demo_ecp_users=1, demo_months=6)
		self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		self.key = key_xml(self.private_key)
		self.originals = (licensing.license_version, licensing.license_key)
		licensing.license_version, licensing.license_key = (lambda: "7.4"), (lambda: self.key)
		self.lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": "Demo",
				"email_id": "demo-licence@example.org",
				"status": "Lead",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Lead", self.lead.name, force=True)

	def tearDown(self):
		licensing.license_version, licensing.license_key = self.originals

	def parse(self, data):
		return etree.fromstring(data[3:], etree.XMLParser(remove_blank_text=True))

	def test_the_document_is_the_one_of_the_sample_a_demo_type_an_end_that_cannot_be_prolonged_and_every_module(
		self,
	):
		now = datetime(2026, 10, 25, 11, 4, 41)

		spec = licensing.demo_spec("Іван Петренко", now)
		data = licensing.generate(spec, self.key, "2acaed4e-d440-4a63-9a1f-b48501b5f7b4")

		root = self.parse(data)
		ns = {"l": licensing.LICENSE_NS}
		self.assertEqual(
			[etree.QName(child).localname for child in root][:4],
			["ID", "Type", "MaxUserAccounts", "SchemaExtendingAllowed"],
		)
		self.assertEqual(root.findtext("l:Type", namespaces=ns), "Generic")
		self.assertEqual(root.findtext("l:MaxUserAccounts", namespaces=ns), "5")
		info = [etree.QName(child).localname for child in root.find("l:Info", ns)]
		self.assertEqual(
			info[:5],
			[
				"LicenseOwner",
				"ExpireDate",
				"ExpireDateNotProlongable",
				"DigitalSignatureUsersCount",
				"Version",
			],
		)
		self.assertEqual(info[5:], licensing.DEMO_TAGS)
		self.assertNotIn("Commercial", info)
		self.assertNotIn("Localization", info)
		self.assertEqual(root.findtext("l:Info/l:LicenseOwner", namespaces=ns), "Іван Петренко")
		self.assertEqual(root.findtext("l:Info/l:ExpireDate", namespaces=ns), "04/25/2027 11:04:41")
		self.assertEqual(root.findtext("l:Info/l:ExpireDateNotProlongable", namespaces=ns), "true")
		self.assertEqual(root.findtext("l:Info/l:DigitalSignatureUsersCount", namespaces=ns), "1")
		self.assertEqual(root.findtext("l:Info/l:Version", namespaces=ns), "7.4")

	def test_the_demo_is_signed_the_way_the_server_checks_it(self):
		from cryptography.hazmat.primitives import hashes
		from cryptography.hazmat.primitives.asymmetric import padding

		data = licensing.generate(licensing.demo_spec("Тест"), self.key)

		root = self.parse(data)
		ns = {"d": licensing.DSIG_NS}
		signature = root.find("d:Signature", ns)
		value = base64.b64decode(signature.findtext("d:SignatureValue", namespaces=ns))
		canonical = etree.tostring(signature.find("d:SignedInfo", ns), method="c14n")
		self.private_key.public_key().verify(value, canonical, padding.PKCS1v15(), hashes.SHA1())

	def test_the_numbers_come_from_the_settings_and_not_from_the_code(self):
		from fossdoc_shop.tests.seed import seed_settings

		seed_settings(demo_users=12, demo_ecp_users=0, demo_months=3)

		spec = licensing.demo_spec("Тест", datetime(2026, 1, 31, 10, 0, 0))

		self.assertEqual((spec.users, spec.ecp_users), (12, 0))
		self.assertEqual(spec.expires, datetime(2026, 4, 30, 10, 0, 0))

	def test_without_the_version_or_the_key_the_shop_signs_nothing(self):
		licensing.license_key = lambda: ""

		self.assertIsNone(licensing.demo_spec("Тест"))
		self.assertIsNone(licensing.demo_license(self.lead.name, "Тест"))

	def test_a_lead_gets_a_licence_once_while_it_lasts_and_a_new_one_after_it_ends(self):
		now = datetime(2026, 10, 25, 11, 0, 0)

		first = licensing.demo_license(self.lead.name, "Іван Петренко", now)
		again = licensing.demo_license(self.lead.name, "Інше Ім'я", now + timedelta(days=100))
		later = licensing.demo_license(self.lead.name, "Іван Петренко", now + timedelta(days=200))

		self.assertTrue(first["new"])
		self.assertFalse(again["new"])
		self.assertEqual(again["content"], first["content"])  # the same licence, the same end: no prolonging
		self.assertEqual(again["owner"], "Іван Петренко")
		self.assertTrue(later["new"])
		self.assertNotEqual(later["content"], first["content"])
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Lead", "attached_to_name": self.lead.name},
			fields=["file_name", "is_private"],
		)
		self.assertEqual([f.is_private for f in files], [1, 1])
		self.assertTrue(all(f.file_name.startswith("License") for f in files))
		# the renewal is found again (its file has another name): a request after it gets it and no third one is made
		renewed = licensing.demo_license(self.lead.name, "Іван Петренко", now + timedelta(days=210))
		self.assertEqual((renewed["new"], renewed["content"]), (False, later["content"]))
		comments = frappe.get_all(
			"Comment", filters={"reference_name": self.lead.name, "content": ["like", "Демо-ліцензія%"]}
		)
		self.assertEqual(len(comments), 2)
