"""Context of the order page (/orders/<name>, /invoices/<name>, /quotations/<name>).

The page template is the copy of the one of Webshop (see order.html). The stock context of Webshop is built first and
this module only adds what the Pay button needs: the unpaid remainder.
"""

from decimal import ROUND_HALF_UP, Decimal

# The documents whose unpaid remainder ERPNext computes in get_amount() of the Payment Request.
ORDERS = ("Sales Order", "Purchase Order")
INVOICES = ("Sales Invoice", "Purchase Invoice")


def _number(value):
	return float(value or 0)


def _round_half_up(value, precision):
	"""The rounding of flt() of Frappe (half up on the decimal text of the number), without importing Frappe."""
	return float(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP))


def unpaid_amount(doc, precision=2):
	"""What a customer still has to pay for the document, in the currency of the document; 0 when nothing.

	It follows get_amount() of erpnext/accounts/doctype/payment_request/payment_request.py (version-15), which is
	what the Payment Request charges: for an order (rounded_total or grand_total) less the advance paid, for an
	invoice the outstanding amount. A draft, a cancelled document and a document of any other type (a Quotation
	cannot be paid at all) have no remainder, so the button is not shown for them.
	"""
	if getattr(doc, "docstatus", None) != 1:
		return 0
	doctype = getattr(doc, "doctype", None)
	other_currency = getattr(doc, "party_account_currency", None) != getattr(doc, "currency", None)
	rate = _number(getattr(doc, "conversion_rate", None)) or 1

	if doctype in ORDERS:
		advance = _number(getattr(doc, "advance_paid", None))
		if other_currency:
			advance = advance / rate
		total = _number(getattr(doc, "rounded_total", None)) or _number(getattr(doc, "grand_total", None))
		amount = total - advance
	elif doctype in INVOICES:
		amount = _number(getattr(doc, "outstanding_amount", None))
		if other_currency:
			amount = amount / rate
	else:
		return 0
	return _round_half_up(amount, precision) if amount > 0 else 0


def get_context(context):
	from erpnext.accounts.utils import get_currency_precision
	from frappe.utils import fmt_money
	from webshop.templates.pages.order import get_context as stock_get_context

	stock_get_context(context)

	doc = context.doc
	context.pay_amount = unpaid_amount(doc, get_currency_precision())
	context.pay_amount_formatted = (
		fmt_money(context.pay_amount, currency=doc.currency) if context.pay_amount else ""
	)
	# the status of a paid order does not say it ("To Deliver and Bill"); the status of an invoice does
	context.is_paid = bool(
		doc.doctype == "Sales Order"
		and doc.docstatus == 1
		and not context.pay_amount
		and _number(doc.advance_paid) > 0
	)
