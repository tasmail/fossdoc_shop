"""Where the payment of a sales order is: not started, started and open, or taken by the bank.

The Pay button of the order page and the make_payment_request wrapper (overrides.py) ask this module before they
start a new Payment Request. ERPNext cancels the open request of an order when the customer asks to pay again, and a
customer who pays on the page of the gateway that belongs to the cancelled request has paid for a request that no
longer exists. So an order whose payment is already in progress gets no second request.

The functions that decide are plain Python (no Frappe import); the ones that read the database import Frappe inside.
"""

import json
from datetime import datetime, timedelta

# The open states of a submitted Payment Request that the customer can still pay.
OPEN_STATUSES = ("Requested", "Pending")
# The states of an Integration Request that wait for the bank.
WAITING = ("Queued", "Pending")
# A payment that was started this recently may be on the page of the bank or in its checks (the anti-fraud checks of
# WayForPay can take more than ten minutes), so it is "in process" even before the bank says anything.
RECENT = timedelta(minutes=15)
# A payment that the bank has answered "in process" stays so until the order of the gateway expires (the
# orderTimeout of WayForPay, a day); after that the notification or the check of the state has settled it.
ANSWERED = timedelta(hours=24)
TOLERANCE = 0.005
CHECKOUT_PATH = "/wayforpay_checkout?order={}"
SERVICE = "WayForPay"

PROCESSING = "processing"
CONTINUE = "continue"


def _answered(irequest: dict) -> bool:
	"""True when the bank has already reported the payment (a notification "in process" is kept in the output)."""
	try:
		output = json.loads(irequest.get("output") or "null") or {}
	except ValueError:
		return False
	return bool(isinstance(output, dict) and output.get("transactionStatus"))


def is_processing(irequest: dict, now: datetime) -> bool:
	"""True when the payment of an Integration Request may be in the hands of the bank."""
	if irequest.get("status") not in WAITING:
		return False
	age = now - irequest["creation"]
	return age <= RECENT or (_answered(irequest) and age <= ANSWERED)


def reusable_page(irequests: list[dict], now: datetime) -> str | None:
	"""The name of the Integration Request whose payment page the customer can open again (the newest), or None.

	It is a request that still waits and whose order at the gateway has not expired; its name is the reference of
	the payment, so the customer lands on the same page and pays under the same reference.
	"""
	for irequest in sorted(irequests, key=lambda row: row["creation"], reverse=True):
		if (
			irequest.get("status") in WAITING
			and irequest.get("service", SERVICE) == SERVICE
			and now - irequest["creation"] < ANSWERED
		):
			return irequest["name"]
	return None


def classify(requests: list[dict], now: datetime, amount=None, gateway_account=None) -> dict | None:
	"""The state of the payment from the open Payment Requests (newest first) and their Integration Requests.

	Each request is a dict with `name`, `grand_total`, `payment_gateway_account` and `irequests`. A payment in the
	hands of the bank wins over everything (whatever the amount: the money may be on its way). Otherwise an open
	request of the same gateway account and of the amount that is still owed is continued. Anything else is None, and
	the caller starts a new request.
	"""
	for request in requests:
		if any(is_processing(irequest, now) for irequest in request["irequests"]):
			return {"state": PROCESSING, "request": request["name"], "irequest": None}
	for request in requests:
		if amount is not None and abs(float(request["grand_total"] or 0) - float(amount)) >= TOLERANCE:
			continue
		if gateway_account and request.get("payment_gateway_account") != gateway_account:
			continue
		return {
			"state": CONTINUE,
			"request": request["name"],
			"irequest": reusable_page(request["irequests"], now),
		}
	return None


def state_of(order: str, amount=None, gateway_account=None) -> dict | None:
	"""The state of the payment of a sales order (see classify); reads the database."""
	import frappe

	requests = frappe.get_all(
		"Payment Request",
		filters={
			"reference_doctype": "Sales Order",
			"reference_name": order,
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
	return classify(requests, frappe.utils.now_datetime(), amount, gateway_account)


def page_url(state: dict) -> str:
	"""The address of the payment page of the request in `state`: the same page (the same reference) when it can
	be opened again, the page of a new payment of the same request otherwise."""
	import frappe
	from frappe.utils import get_url

	if state.get("irequest"):
		return get_url(CHECKOUT_PATH.format(state["irequest"]))
	return frappe.get_doc("Payment Request", state["request"]).get_payment_url()


def order_page_url(order: str) -> str:
	"""The order page with the mark that makes it say that the payment is in process."""
	from frappe.utils import get_url

	return get_url(f"/orders/{order}?payment=processing")
