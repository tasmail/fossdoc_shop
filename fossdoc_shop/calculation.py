"""The calculation that the calculator of the site sends by e-mail.

The page sends the contact form (`frappe.www.contact.send_message`); the message is the marker line followed
by one line of JSON (the lines in words for the manager follow it). Frappe turns the message into a Communication and the Notification of this app mails it.
The text comes from a guest, so everything is validated and limited here before a template shows it.
"""

import html
import json
import math

import frappe
from frappe import _

MARKER = "Розрахунок вартості FossDoc"
LANGUAGES = ("uk", "ru", "en")
KINDS = (
	"calculator",
	"cart",
	"topup",
)  # where it comes from: the calculator, the cart or the extra seats form
MAX_LINES = 120
MAX_TEXT = 200


def _number(value, default=0.0, high=1e9):
	try:
		number = float(value)
	except (TypeError, ValueError):
		return default
	if math.isnan(number) or number < 0:
		return default
	return min(number, high)


def parse_calculation(content: str | None) -> dict | None:
	"""Return the calculation of a message or None when the message is not a valid calculation."""
	if not content:
		return None
	# the contact form escapes the markup of the message (quotes of the JSON too)
	text = html.unescape(content)
	head, _, body = text.strip().partition("\n")
	if head.strip() != MARKER:
		return None
	try:
		raw = json.loads(body.strip().split("\n", 1)[0])
	except ValueError:
		return None
	if not isinstance(raw, dict) or not isinstance(raw.get("lines"), list):
		return None
	lines = []
	for row in raw["lines"][:MAX_LINES]:
		if not isinstance(row, dict) or not isinstance(row.get("code"), str):
			continue
		lines.append(
			{
				"code": row["code"][:MAX_TEXT],
				"name": str(row.get("name") or row["code"])[:MAX_TEXT],
				"qty": int(_number(row.get("qty"), 1, 100000)) or 1,
				"unit": _number(row.get("unit")),
				"total": _number(row.get("total")),
			}
		)
	if not lines:
		return None
	language = raw.get("lang") if raw.get("lang") in LANGUAGES else "uk"
	return {
		"lang": language,
		"kind": raw.get("kind") if raw.get("kind") in KINDS else "calculator",
		# the licence that the extra seats are for (the manager checks it before the invoice)
		"licensee": str(raw.get("licensee") or "").strip()[:MAX_TEXT],
		"lines": lines,
		"total": _number(raw.get("total")),
		"per_month": bool(raw.get("perMonth")),
	}


def describe(codes: list[str]) -> dict:
	"""The descriptions of the items of a calculation (only items that exist), by item code."""
	if not codes:
		return {}
	rows = frappe.get_all(
		"Item", filters={"name": ["in", codes]}, fields=["name", "description"], limit_page_length=len(codes)
	)
	return {row.name: frappe.utils.strip_html_tags(row.description or "") for row in rows}


def money(value) -> str:
	"""An amount in hryvnia for a letter: whole numbers without kopecks, a space between the thousands."""
	number = float(value or 0)
	text = f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"
	return text.replace(",", "\u00a0") + "\u00a0" + _("грн")
