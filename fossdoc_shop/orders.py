"""What the shop adds to the orders of the buyers: their language and the limit of the quantity of an item."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

LANGUAGES = ("uk", "ru", "en")
MAX_ORDER_QTY = "max_order_qty"


def ensure_item_fields():
	"""The field of the item: the most that one order may hold of it (0 is no limit), as min_order_qty is the least."""
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": MAX_ORDER_QTY,
					"fieldtype": "Float",
					"label": "Maximum order quantity",
					"insert_after": "min_order_qty",
					"description": "0 is no limit. A module is bought once; the seats of users have no limit.",
					"default": "0",
				}
			]
		}
	)


def require_open_shop(doc, method=None):
	"""While the shop is closed a visitor of the site cannot start a cart or an order; the staff still can."""
	from fossdoc_shop.branding import shop_open

	if shop_open() or frappe.session.user == "Administrator":
		return
	if frappe.db.get_value("User", frappe.session.user, "user_type") == "System User":
		return
	frappe.throw(_("The shop is not open yet. Please send us the calculation and we will answer."))


def set_language(doc, method=None):
	"""A customer, a quotation, an order and a buyer who signs up keep the language that was used on the site."""
	if doc.get("user_type") not in (None, "Website User"):
		return  # a user of the desk keeps the language that the manager gives
	if not doc.get("language") and frappe.local.lang in LANGUAGES:
		doc.language = frappe.local.lang


def limit_quantities(doc, method=None):
	"""A row does not hold more than the item allows: the quantity goes down to the limit and the buyer is told."""
	codes = [row.item_code for row in doc.get("items") or [] if row.item_code]
	if not codes:
		return
	limits = {
		row.name: row[MAX_ORDER_QTY]
		for row in frappe.get_all(
			"Item", filters={"name": ["in", codes], MAX_ORDER_QTY: [">", 0]}, fields=["name", MAX_ORDER_QTY]
		)
	}
	for row in doc.get("items"):
		limit = limits.get(row.item_code)
		if limit and row.qty > limit:
			row.qty = limit
			frappe.msgprint(_("{0}: not more than {1} in one order").format(_(row.item_name), int(limit)))
