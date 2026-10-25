"""Download of the demo release: the form of the site fills the CRM and mails links that work for 24 hours.

A release is an Item of the group FossDoc Downloads whose name carries the version (FD-DL-7.4.32), whose
description is the list of changes and whose private attachments are the installers. A manager adds a release in
the desk and nothing else. The newest version is the one that is offered; a link is signed with the key of the
site, so it cannot be guessed, expires and names one file.
"""

import hashlib
import hmac
import re
import time
from email.utils import formataddr
from urllib.parse import quote

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_email_address
from werkzeug.exceptions import HTTPException

from fossdoc_shop.branding import brand

GROUP = "FossDoc Downloads"
LINK_HOURS = 24
VERSION = re.compile(r"(\d+(?:\.\d+)+)")
MAIL_TEMPLATE = "templates/download_mail.html"


def version_of(code: str) -> tuple[int, ...] | None:
	"""(7, 4, 32) for FD-DL-7.4.32; None for a code without a version."""
	found = VERSION.search(code or "")
	return tuple(int(part) for part in found.group(1).split(".")) if found else None


def releases() -> list[dict]:
	"""The releases with their installers, the newest first."""
	items = frappe.get_all(
		"Item",
		filters={"item_group": GROUP, "disabled": 0},
		fields=["name", "item_name", "description", "creation"],
		limit_page_length=0,
	)
	rows = []
	for item in items:
		version = version_of(item.name)
		if version is None:
			continue
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Item", "attached_to_name": item.name, "is_folder": 0},
			fields=["name", "file_name", "file_url", "file_size"],
			order_by="file_name",
			limit_page_length=0,
		)
		rows.append({"code": item.name, "version": version, "notes": item.description, "files": files})
	return sorted(rows, key=lambda row: row["version"], reverse=True)


def current_release() -> dict | None:
	"""The newest release that has at least one installer."""
	return next((row for row in releases() if row["files"]), None)


def sign(file: str, email: str, expires: int) -> str:
	key = frappe.local.conf.get("encryption_key") or frappe.local.conf.get("secret") or ""
	text = f"{file}|{email.lower()}|{expires}".encode()
	return hmac.new(str(key).encode(), text, hashlib.sha256).hexdigest()


def valid(file: str, email: str, expires: int, signature: str, now: float | None = None) -> bool:
	"""True for a link that was signed by this site and has not expired."""
	if (now if now is not None else time.time()) > expires:
		return False
	return hmac.compare_digest(sign(file, email, expires), signature or "")


def link(file: str, email: str, now: float | None = None, hours: int = LINK_HOURS) -> str:
	expires = int((now if now is not None else time.time()) + hours * 3600)
	query = f"file={file}&email={quote(email)}&expires={expires}&sig={sign(file, email, expires)}"
	return f"{brand()['site']}/api/method/fossdoc_shop.downloads.download?{query}"


def size_text(size: int | None) -> str:
	size = int(size or 0)
	return (
		f"{size / 1024 / 1024:.1f} " + _("МБ")
		if size >= 1024 * 1024
		else f"{max(size // 1024, 1)} " + _("КБ")
	)


def ensure_lead(full_name: str, email: str, phone: str, version: str):
	"""The person of the request is a Lead of the CRM; a known address gets a note and no second Lead."""
	name = frappe.db.get_value("Lead", {"email_id": email}, "name")
	note = f"Запит демо-версії FossDoc {version}"
	if name:
		lead = frappe.get_doc("Lead", name)
	else:
		first, _sep, last = full_name.partition(" ")
		lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": first,
				"last_name": last.strip() or None,
				"email_id": email,
				"mobile_no": phone or None,
				"status": "Lead",
			}
		).insert(ignore_permissions=True)
	lead.add_comment("Comment", note)
	return lead


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=10, seconds=60 * 60)
def request_download(full_name: str, email: str, phone: str = "", website: str = "", lang: str = ""):
	"""Store the request as a Lead and mail the links of the newest release (a filled `website` is a robot)."""
	if website:
		return {"sent": True}
	if lang in ("uk", "ru", "en"):  # the language of the page that the visitor used
		frappe.local.lang = lang
	email = validate_email_address(email, throw=True)
	full_name = (full_name or "").strip()
	if not full_name:
		frappe.throw(_("Enter your name"), frappe.ValidationError)
	release = current_release()
	if release is None:
		frappe.throw(_("The demo version is not available now"), frappe.ValidationError)
	version = ".".join(map(str, release["version"]))
	ensure_lead(full_name, email, (phone or "").strip(), version)
	data = brand()
	links = [
		{"name": row["file_name"], "size": size_text(row["file_size"]), "url": link(row["name"], email)}
		for row in release["files"]
	]
	frappe.sendmail(
		recipients=[email],
		subject=f"{_('Демо-версія')} {data['brand']} {version}",
		message=frappe.render_template(
			"fossdoc_shop/" + MAIL_TEMPLATE,
			{"name": full_name, "version": version, "links": links, "hours": LINK_HOURS, "b": data},
		),
		reply_to=formataddr((data["company"], data["email"])) if data["email"] else None,
		now=True,
	)
	return {"sent": True}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=60, seconds=60 * 60)
def download(file: str, email: str, expires: int, sig: str):
	"""Send the installer when the link is valid; only the attachments of a release can be taken."""
	if not valid(file, email, int(expires), sig):
		frappe.throw(_("The link is not valid or has expired"), frappe.PermissionError)
	row = frappe.db.get_value(
		"File", file, ["file_name", "file_url", "attached_to_doctype", "attached_to_name"], as_dict=True
	)
	group = frappe.db.get_value("Item", row.attached_to_name, "item_group") if row else None
	if not row or row.attached_to_doctype != "Item" or group != GROUP:
		raise frappe.DoesNotExistError
	from frappe.utils.response import send_private_file

	response = send_private_file(row.file_url.removeprefix("/private/"))
	response.headers["Content-Disposition"] = f'attachment; filename="{row.file_name}"'
	raise HTTPException(response=response)


ORDER_LINK_HOURS = 7 * 24


def download_links(doc) -> list[dict]:
	"""For the letter about a paid order: the files of the newest release with links that work for a week."""
	email = doc.get("email_to")
	release = current_release() if email else None
	if release is None:
		return []
	return [
		{
			"name": row["file_name"],
			"size": size_text(row["file_size"]),
			"url": link(row["name"], email, hours=ORDER_LINK_HOURS),
		}
		for row in release["files"]
	]
