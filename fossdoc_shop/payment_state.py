"""Where the payment of a sales order is: not started, started and open, or taken by the bank.

The Pay button of the order page and the make_payment_request wrapper (overrides.py) ask this module before they
start a new Payment Request. ERPNext cancels the open request of an order when the customer asks to pay again, and a
customer who pays on the page of the gateway that belongs to the cancelled request has paid for a request that no
longer exists. So an order whose payment is already in progress gets no second request.

The functions that decide are plain Python (no Frappe import); the ones that read the database import Frappe inside.
"""

import json
from datetime import datetime, timedelta

# The open states of a submitted Payment Request that the customer can still pay (ERPNext sets Initiated when the
# request has a payment url; it does not cancel such a request, it refuses a second one).
OPEN_STATUSES = ("Requested", "Initiated")
# The state of an Integration Request that waits for the bank.
WAITING = ("Queued",)
# A payment that was started this recently may be on the page of the bank or in its checks (the anti-fraud checks of
# WayForPay can take more than ten minutes). It decides only which text the customer reads (`recent`).
RECENT = timedelta(minutes=15)
# The default life of an order at the gateway, the orderTimeout of the WayForPay Settings (checkout.py of the
# wayforpay app uses `order_timeout or 86400`); the real value is read by order_window().
DEFAULT_WINDOW = timedelta(seconds=86400)
TOLERANCE = 0.005
CHECKOUT_PATH = "/wayforpay_checkout?order={}"
SERVICE = "WayForPay"
DOCTYPES = ("Sales Order", "Sales Invoice")

# The bank has answered "in process" and the money may be on its way: nothing new is started.
PROCESSING = "processing"
# An open request that the customer can continue on the same payment page.
CONTINUE = "continue"


def _answered(irequest: dict) -> bool:
	"""True when the bank has already reported the payment (a notification "in process" is kept in the output)."""
	try:
		output = json.loads(irequest.get("output") or "null") or {}
	except ValueError:
		return False
	return bool(isinstance(output, dict) and output.get("transactionStatus"))


def is_answered(irequest: dict, now: datetime, window: timedelta = DEFAULT_WINDOW) -> bool:
	"""True when the bank said "in process" about a payment that still waits and whose order has not expired."""
	return irequest.get("status") in WAITING and _answered(irequest) and now - irequest["creation"] <= window


def is_recent(irequest: dict, now: datetime) -> bool:
	"""True when a payment that still waits was started in the last minutes (the customer may have paid already)."""
	return irequest.get("status") in WAITING and now - irequest["creation"] <= RECENT


def reusable_page(irequests: list[dict], now: datetime, window: timedelta = DEFAULT_WINDOW) -> str | None:
	"""The name of the Integration Request whose payment page the customer can open again (the newest), or None.

	It is a request that still waits and whose order at the gateway has not expired; its name is the reference of
	the payment, so the customer lands on the same page and pays under the same reference.
	"""
	for irequest in sorted(irequests, key=lambda row: row["creation"], reverse=True):
		if (
			irequest.get("status") in WAITING
			and irequest.get("service", SERVICE) == SERVICE
			and now - irequest["creation"] < window
		):
			return irequest["name"]
	return None


def classify(
	requests: list[dict], now: datetime, amount=None, gateway_account=None, window: timedelta = DEFAULT_WINDOW
) -> dict | None:
	"""The state of the payment from the open Payment Requests (newest first) and their Integration Requests.

	Each request is a dict with `name`, `grand_total`, `payment_gateway_account` and `irequests`.
	- A payment that the bank answered "in process" is PROCESSING, whatever the amount (the money may be on its way).
	- An open request of the same gateway account and of the amount that is still owed is CONTINUE on its payment
	  page; `recent` tells that it was started in the last minutes, so the customer may have paid already.
	- A recent request that does not fit (another amount or account) is PROCESSING too: it must not be cancelled.
	- Anything else is None, and the caller starts a new request.
	"""
	for request in requests:
		if any(is_answered(irequest, now, window) for irequest in request["irequests"]):
			return {"state": PROCESSING, "request": request["name"], "irequest": None, "recent": True}
	for request in requests:
		recent = any(is_recent(irequest, now) for irequest in request["irequests"])
		fits = (amount is None or abs(float(request["grand_total"] or 0) - float(amount)) < TOLERANCE) and (
			not gateway_account or request.get("payment_gateway_account") == gateway_account
		)
		if fits:
			return {
				"state": CONTINUE,
				"request": request["name"],
				"irequest": reusable_page(request["irequests"], now, window),
				"recent": recent,
			}
		if recent:
			return {"state": PROCESSING, "request": request["name"], "irequest": None, "recent": True}
	return None


def order_window():
	"""How long an order lives at the gateway: the longest orderTimeout of the WayForPay Settings, or a day."""
	import frappe
	from frappe.utils import cint

	try:
		seconds = [cint(value) for value in frappe.get_all("WayForPay Settings", pluck="order_timeout")]
	except Exception:  # noqa: BLE001 - a site without the gateway app has no such doctype
		seconds = []
	return timedelta(seconds=max(seconds + [0]) or 86400)


def gateway_account(company: str, args: dict | None = None) -> dict:
	"""The Payment Gateway Account (name, payment_account) that make_payment_request of ERPNext would use."""
	import frappe
	from erpnext.accounts.doctype.payment_request import payment_request

	return payment_request.get_gateway_details(frappe._dict(args or {}, company=company)) or {}


def state_of(doctype: str, name: str, amount=None, account=None) -> dict | None:
	"""The state of the payment of a sales order or invoice (see classify); reads the database."""
	import frappe

	requests = frappe.get_all(
		"Payment Request",
		filters={
			"reference_doctype": doctype,
			"reference_name": name,
			"docstatus": 1,
			"status": ["in", list(OPEN_STATUSES)],
		},
		fields=["name", "grand_total", "payment_gateway_account"],
		order_by="creation desc",
	)
	for request in requests:
		request["irequests"] = frappe.get_all(
			"Integration Request",
			filters={"reference_doctype": "Payment Request", "reference_docname": request["name"]},
			fields=["name", "status", "creation", "output", "integration_request_service as service"],
		)
	return classify(requests, frappe.utils.now_datetime(), amount, account, order_window())


def page_url(state: dict) -> str:
	"""The address of the payment page of the request in `state`: the same page (the same reference) when it can
	be opened again, the page of a new payment of the same request otherwise."""
	import frappe
	from frappe.utils import get_url

	if state.get("irequest"):
		return get_url(CHECKOUT_PATH.format(state["irequest"]))
	return frappe.get_doc("Payment Request", state["request"]).get_payment_url()


def order_page_url(doctype: str, name: str) -> str:
	"""The page of the document with the mark that makes it say that the payment is in process."""
	from frappe.utils import get_url

	folder = "orders" if doctype == "Sales Order" else "invoices"
	return get_url(f"/{folder}/{name}?payment=processing")


def message(state: dict) -> str:
	"""The text for a customer whose payment is in progress (the same words as the notice of the page)."""
	from frappe import _

	if state["state"] == PROCESSING:
		return _(
			"Оплата обробляється банком, підтвердження може надійти не одразу. Після підтвердження вам буде надіслано лист. Не оплачуйте повторно."
		)
	return (
		_("Оплата цього замовлення вже розпочата")
		+ ". "
		+ _("Ви можете продовжити оплату на тій самій сторінці банку.")
	)
