"""The licence of the FossDoc server for a paid order.

The server reads an XML document that the old generator of the product (Foss.FossDoc.Licensing) wrote and signed
with XML-DSig (RSA, SHA-1, an enveloped signature, no key info): the type, the number of users, an `Info` element
with a flag for every licensed module, the owner, the localization, the version of the server and the number of
users of the digital signature. This module writes the same document for the lines of an order and signs it with
the private key of the version, which lives in the Password field of FossDoc Shop Settings (never in the code).

An order gets a licence only when every line is known (see MODULE_TAGS) and the key is set; a rental and anything
else is left to a manager, and the letter to the customer says that he will be contacted.
"""

import base64
import hashlib
import uuid
from dataclasses import dataclass, field

import frappe
from lxml import etree

LICENSE_NS = "http://www.foss.kharkov.ua/FossDoc/ApplicationServer/License"
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
LICENSE_FILE = "License.xml"
SETTINGS = "FossDoc Shop Settings"
ROOT_TAG = "FossDocApplicationServerLicense"
LICENSE_TYPE = "FossDoc"
LOCALIZATION = "uk-UA"

SEAT = "FD-SEAT"
ECP_SEAT = "FD-ECP-SEAT"
RENT_SEAT = "FD-RENT-SEAT"

# The module of the shop (FD-MOD-<id>) -> the elements of `Info` that switch it on. An empty list is a module that
# the platform has always; None is a module whose element is not known yet: an order with it is left to a manager.
MODULE_TAGS: dict[str, list[str] | None] = {
	"fosslook-platform": [],
	"storage": [],
	"resolution": ["EDMS_Resolutions"],
	"document-projects": ["EDMS_Projects"],
	"recurring-tasks": ["EDMS_Reminders"],
	"service-desk": ["EDMS_InternalNotes"],
	"transfer-journal": ["DocumentTransferJournal"],
	"history": ["History"],
	"web-server": ["WebXsp"],
	"domain-authorisation": ["DirectoryIntegration"],
	"control": ["ControllableDocument"],
	"citizen-request": ["EDMS_CitizenRequests"],
	"audit": ["EventLogger"],
	"statistics": ["WorkStatistics"],
	"internet-mail": ["InternetMailTransport"],
	"calcfields": ["CalculatedFields"],
	"routing_notifier": ["NotificationsRouting"],
	"document-chat": ["DocumentDiscussion"],
	"mobileid": ["MobileID"],
	"ptah": ["EDI"],
	"vchasno": ["Vchasno"],
	"assistant": None,
	"web_portal": None,
	"sev": None,
	"scanning": None,
	"archive": None,
	"qrcode": None,
	"execution_status": None,
}
# Lines that change nothing in the licence: databases, services, the providers of the digital signature.
NEUTRAL_PREFIXES = ("FD-DB-", "FD-SRV-")
DIGITAL_SIGNATURE_TAG = "EDMS_DigitalSignature"


@dataclass
class Spec:
	"""What the licence says."""

	owner: str
	users: int
	version: str
	ecp_users: int = 0
	tags: list[str] = field(default_factory=list)

	def lines(self) -> list[str]:
		"""The parameters in words, for the letter and the order."""
		out = [f"Користувачів: {self.users}"]
		if self.ecp_users:
			out.append(f"Користувачів з ЕЦП: {self.ecp_users}")
		out.append(f"Версія сервера: {self.version}")
		if self.tags:
			out.append("Модулі: " + ", ".join(self.tags))
		return out


def spec_from_lines(lines: list[dict], owner: str, version: str) -> Spec | None:
	"""The licence of the lines of an order [{item_code, qty}], or None when it cannot be made automatically."""
	users = ecp_users = 0
	tags: list[str] = []
	for line in lines:
		code, qty = line["item_code"], int(line.get("qty") or 0)
		if code == RENT_SEAT:
			return None
		if code == SEAT:
			users += qty
		elif code == ECP_SEAT:
			ecp_users += qty
		elif code.startswith("FD-MOD-"):
			known = MODULE_TAGS.get(code.removeprefix("FD-MOD-"), None)
			if known is None:
				return None
			tags += [tag for tag in known if tag not in tags]
		elif code.startswith("FD-ECP-"):
			if DIGITAL_SIGNATURE_TAG not in tags:
				tags.append(DIGITAL_SIGNATURE_TAG)
		elif not code.startswith(NEUTRAL_PREFIXES):
			return None
	if users <= 0:
		return None
	if ecp_users and DIGITAL_SIGNATURE_TAG not in tags:
		tags.append(DIGITAL_SIGNATURE_TAG)
	return Spec(owner=owner, users=users, version=version, ecp_users=ecp_users, tags=tags)


# The XML ---------------------------------------------------------------------------------------------------


def _element(parent, name: str, text: str):
	child = etree.SubElement(parent, f"{{{LICENSE_NS}}}{name}")
	child.text = text
	return child


def build_document(spec: Spec, license_id: str):
	"""The unsigned licence, in the order of elements that the generator of the product writes."""
	root = etree.Element(f"{{{LICENSE_NS}}}{ROOT_TAG}", nsmap={None: LICENSE_NS})
	_element(root, "ID", license_id)
	_element(root, "Type", LICENSE_TYPE)
	_element(root, "MaxUserAccounts", str(spec.users))
	_element(root, "SchemaExtendingAllowed", "true")
	info = etree.SubElement(root, f"{{{LICENSE_NS}}}Info")
	_element(info, "Commercial", "true")
	_element(info, "LicenseOwner", spec.owner)
	_element(info, "Localization", LOCALIZATION)
	if spec.ecp_users:
		_element(info, "DigitalSignatureUsersCount", str(spec.ecp_users))
	_element(info, "Version", spec.version)
	for tag in spec.tags:
		_element(info, tag, "true")
	return root


def _b64(value: bytes) -> str:
	return base64.b64encode(value).decode()


def _number(xml: etree._Element, name: str) -> int:
	return int.from_bytes(base64.b64decode(xml.findtext(name)), "big")


def load_private_key(key_xml: str):
	"""The key in the format of .NET (<RSAKeyValue>) as a key of the `cryptography` library."""
	from cryptography.hazmat.primitives.asymmetric import rsa

	xml = etree.fromstring(key_xml.strip().encode())
	public = rsa.RSAPublicNumbers(_number(xml, "Exponent"), _number(xml, "Modulus"))
	return rsa.RSAPrivateNumbers(
		p=_number(xml, "P"),
		q=_number(xml, "Q"),
		d=_number(xml, "D"),
		dmp1=_number(xml, "DP"),
		dmq1=_number(xml, "DQ"),
		iqmp=_number(xml, "InverseQ"),
		public_numbers=public,
	).private_key()


def _dsig(parent, name: str, **attributes):
	return etree.SubElement(parent, f"{{{DSIG_NS}}}{name}", attributes)


def sign(root, private_key) -> None:
	"""Append the enveloped signature of the way of .NET SignedXml: the digest of the canonical document, then
	the signature of the canonical SignedInfo (inclusive C14N, RSA-SHA1)."""
	from cryptography.hazmat.primitives import hashes
	from cryptography.hazmat.primitives.asymmetric import padding

	digest = hashlib.sha1(etree.tostring(root, method="c14n")).digest()
	signature = etree.SubElement(root, f"{{{DSIG_NS}}}Signature", nsmap={None: DSIG_NS})
	signed_info = _dsig(signature, "SignedInfo")
	_dsig(signed_info, "CanonicalizationMethod", Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
	_dsig(signed_info, "SignatureMethod", Algorithm=f"{DSIG_NS}rsa-sha1")
	reference = _dsig(signed_info, "Reference", URI="")
	transforms = _dsig(reference, "Transforms")
	_dsig(transforms, "Transform", Algorithm=f"{DSIG_NS}enveloped-signature")
	_dsig(reference, "DigestMethod", Algorithm=f"{DSIG_NS}sha1")
	_dsig(reference, "DigestValue").text = _b64(digest)
	canonical = etree.tostring(signed_info, method="c14n")
	value = private_key.sign(canonical, padding.PKCS1v15(), hashes.SHA1())
	_dsig(signature, "SignatureValue").text = _b64(value)


def generate(spec: Spec, key_xml: str, license_id: str | None = None) -> bytes:
	"""The signed licence as a file: UTF-8 with a byte order mark and indented, like the one of the generator."""
	root = build_document(spec, license_id or str(uuid.uuid4()))
	sign(root, load_private_key(key_xml))
	etree.indent(root, space="  ")
	return b"\xef\xbb\xbf" + etree.tostring(root, encoding="utf-8")


# The order ---------------------------------------------------------------------------------------------------


def settings():
	return frappe.get_cached_doc(SETTINGS)


def license_version() -> str:
	return (settings().get("license_version") or "").strip()


def license_key() -> str:
	return (settings().get_password("license_signing_key", raise_exception=False) or "").strip()


def order_spec(order) -> Spec | None:
	version = license_version()
	if not version or not license_key():
		return None
	lines = [{"item_code": row.item_code, "qty": row.qty} for row in order.get("items") or []]
	owner = order.get("customer_name") or order.get("customer") or ""
	return spec_from_lines(lines, owner, version)


def issued_file(order_name: str) -> str | None:
	"""The File of the licence of the order, if one was made."""
	return frappe.db.get_value(
		"File",
		{"attached_to_doctype": "Sales Order", "attached_to_name": order_name, "file_name": LICENSE_FILE},
		"name",
	)


def issue_for_order(order_name: str) -> str | None:
	"""Make the licence of a paid order, attach it to the order (private) and write its parameters into the
	terms of the order. Returns the name of the File, or None when the order is left to a manager."""
	existing = issued_file(order_name)
	if existing:
		return existing
	order = frappe.get_doc("Sales Order", order_name)
	spec = order_spec(order)
	if spec is None:
		return None
	content = generate(spec, license_key())
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": LICENSE_FILE,
			"attached_to_doctype": "Sales Order",
			"attached_to_name": order_name,
			"is_private": 1,
			"content": content,
		}
	).insert(ignore_permissions=True)
	text = "<br>".join(["<b>Ліцензія FossDoc</b>", *spec.lines()])
	frappe.db.set_value("Sales Order", order_name, "terms", text, update_modified=False)
	return file.name


def license_info(doc) -> dict:
	"""For the template of the letter: has the order of this Payment Request a licence, and what does it say."""
	if doc.get("reference_doctype") != "Sales Order" or not doc.get("reference_name"):
		return {"issued": False, "lines": []}
	name = doc.get("reference_name")
	if not issued_file(name):
		return {"issued": False, "lines": []}
	spec = order_spec(frappe.get_doc("Sales Order", name))
	return {"issued": True, "lines": spec.lines() if spec else []}
