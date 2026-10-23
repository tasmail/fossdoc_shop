"""The data of a paid order for the letter of the payment and its PDF.

The templates ask `payment_order(doc)` for the sales order of a Payment Request: what was bought, for how much,
and who pays. Everything that a customer typed (the name, the address) is a plain text here: a template escapes it.
"""

import re

import frappe

SUBJECT_MARK = "Оплату замовлення"


def _lines(html: str | None) -> list[str]:
	"""The lines of an address that Frappe keeps as HTML with <br>."""
	text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.IGNORECASE)
	text = frappe.utils.strip_html_tags(text)
	return [line.strip() for line in text.split("\n") if line.strip()]


def payment_order(doc) -> dict | None:
	"""The sales order that a Payment Request pays, or None for a payment of anything else."""
	if doc.get("reference_doctype") != "Sales Order" or not doc.get("reference_name"):
		return None
	order = frappe.get_doc("Sales Order", doc.get("reference_name"))
	return {
		"name": order.name,
		"date": order.get("transaction_date"),
		"currency": order.get("currency") or doc.get("currency"),
		"customer": order.get("customer_name") or order.get("customer"),
		"address": _lines(order.get("address_display")),
		"items": [
			{
				"name": row.get("item_name") or row.get("item_code"),
				"qty": row.get("qty"),
				"rate": row.get("rate"),
				"amount": row.get("amount"),
			}
			for row in order.get("items") or []
		],
		"total": order.get("grand_total"),
		"paid": doc.get("grand_total"),
		"paid_on": doc.get("modified") or frappe.utils.nowdate(),
		"gateway": "Stripe"
		if "stripe" in (doc.get("payment_gateway") or "").lower()
		else doc.get("payment_gateway"),
	}
