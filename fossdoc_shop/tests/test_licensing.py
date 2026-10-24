import base64
import hashlib

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
