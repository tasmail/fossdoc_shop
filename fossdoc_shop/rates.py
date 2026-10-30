"""The USD price lists of the shop in hryvnia, at the official rate of the National Bank of Ukraine.

The prices are kept in USD (the price list and the pricing rules of the managers). A customer pays in hryvnia, so
the shop sells from a second price list in UAH that is made from the first one: every price of the USD list times
the rate of the National Bank, rounded to the step of the settings. The rate is stored as a Currency Exchange
record and the UAH list changes only when a new rate comes, so an order keeps the prices the customer saw.
"""

import datetime
import math

import frappe
import requests

NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
FROM_CURRENCY = "USD"
TO_CURRENCY = "UAH"
SUFFIX = " UAH"  # the title of a pricing rule of the UAH list is the title of the USD rule and this
TIMEOUT = 20
# The prices of the UAH list as the calculator of the site reads them; dropped when the list is made again.
SHEET_KEY = "fossdoc_shop:price_sheet"
SHEET_SECONDS = 600  # a price edited by hand in the UAH list reaches the calculator after this time
# The payments for services are an item of 1 USD that the customer buys as many times as the agreed amount: a whole
# hryvnia for it would be up to 1.1% away from the rate, so its price keeps the kopecks.
PAYMENTS_GROUP = "FossDoc Service Payments"
PAYMENTS_STEP = 0.01
SAVEPOINT = "fossdoc_uah_prices"


def fetch_nbu_rate(currency: str = FROM_CURRENCY) -> tuple[float, datetime.date]:
	"""The official rate of the currency in hryvnia and the date it is valid from."""
	response = requests.get(NBU_URL, params={"valcode": currency, "json": ""}, timeout=TIMEOUT)
	response.raise_for_status()
	return parse_nbu(response.json(), currency)


def parse_nbu(rows, currency: str = FROM_CURRENCY) -> tuple[float, datetime.date]:
	row = next((r for r in rows or [] if isinstance(r, dict) and r.get("cc") == currency), None)
	if not row or not row.get("rate") or not row.get("exchangedate"):
		raise ValueError(f"the National Bank sent no rate of {currency}")
	rate = float(row["rate"])
	if not 0 < rate < 1000:
		raise ValueError(f"the rate of {currency} is not credible: {rate}")
	return rate, datetime.datetime.strptime(row["exchangedate"], "%d.%m.%Y").date()


def round_to_step(value: float, step: float) -> float:
	"""The value rounded to the nearest multiple of the step (a half goes up)."""
	if step <= 0:
		return round(value, 2)
	return round(math.floor(value / step + 0.5) * step, 2)


def store_rate(rate: float, date: datetime.date) -> bool:
	"""Write the rate as a Currency Exchange record; False when the date has its record already."""
	if frappe.db.exists(
		"Currency Exchange",
		{"from_currency": FROM_CURRENCY, "to_currency": TO_CURRENCY, "date": date, "for_selling": 1},
	):
		return False
	if not frappe.db.get_value("Currency", TO_CURRENCY, "enabled"):
		frappe.db.set_value("Currency", TO_CURRENCY, "enabled", 1)
	frappe.get_doc(
		{
			"doctype": "Currency Exchange",
			"date": date,
			"from_currency": FROM_CURRENCY,
			"to_currency": TO_CURRENCY,
			"exchange_rate": rate,
			"for_buying": 1,
			"for_selling": 1,
		}
	).insert(ignore_permissions=True)
	return True


def current_rate() -> tuple[float, datetime.date] | None:
	"""The latest stored rate of USD in hryvnia that is not in the future."""
	row = frappe.db.get_value(
		"Currency Exchange",
		{
			"from_currency": FROM_CURRENCY,
			"to_currency": TO_CURRENCY,
			"for_selling": 1,
			"date": ["<=", frappe.utils.today()],
		},
		["exchange_rate", "date"],
		order_by="date desc",
	)
	return (float(row[0]), row[1]) if row else None


def settings() -> frappe._dict:
	return frappe.get_cached_doc("FossDoc Shop Settings")


def ensure_price_list(name: str) -> None:
	if not frappe.db.exists("Price List", name):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"currency": TO_CURRENCY,
				"selling": 1,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)


def sync_item_prices(master: str, target: str, rate: float, step: float) -> dict:
	"""Make the item prices of the target list from the master list; a price that left the master goes."""
	exact = set(frappe.get_all("Item", filters={"item_group": PAYMENTS_GROUP}, pluck="name"))
	wanted = {
		row.item_code: round_to_step(
			row.price_list_rate * rate, PAYMENTS_STEP if row.item_code in exact else step
		)
		for row in frappe.get_all(
			"Item Price",
			filters={"price_list": master, "selling": 1},
			fields=["item_code", "price_list_rate"],
			limit_page_length=0,
		)
	}
	have = {
		row.item_code: row
		for row in frappe.get_all(
			"Item Price",
			filters={"price_list": target},
			fields=["name", "item_code", "price_list_rate"],
			limit_page_length=0,
		)
	}
	result = {"created": 0, "changed": 0, "removed": 0}
	for code, price in wanted.items():
		if code not in have:
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": code,
					"price_list": target,
					"price_list_rate": price,
					"currency": TO_CURRENCY,
					"selling": 1,
				}
			).insert(ignore_permissions=True)
			result["created"] += 1
		elif round(have[code].price_list_rate, 2) != price:
			frappe.db.set_value("Item Price", have[code].name, "price_list_rate", price)
			result["changed"] += 1
	for code, row in have.items():
		if code not in wanted:
			frappe.delete_doc("Item Price", row.name, ignore_permissions=True)
			result["removed"] += 1
	return result


def sync_pricing_rules(master: str, target: str, rate: float, step: float) -> dict:
	"""Mirror the quantity rules of the master list (the seat) for the target list."""
	rules = frappe.get_all(
		"Pricing Rule",
		filters={"for_price_list": master, "currency": FROM_CURRENCY},
		fields=["name"],
		limit_page_length=0,
	)
	result = {"created": 0, "changed": 0, "removed": 0}
	titles = set()
	for row in rules:
		rule = frappe.get_doc("Pricing Rule", row.name)
		title = rule.title + SUFFIX
		titles.add(title)
		values = {
			"title": title,
			"for_price_list": target,
			"currency": TO_CURRENCY,
			"rate": round_to_step(rule.rate * rate, step),
		}
		name = frappe.db.get_value("Pricing Rule", {"title": title})
		if not name:
			doc = frappe.copy_doc(rule)
			doc.update(values)
			doc.insert(ignore_permissions=True)
			result["created"] += 1
		elif frappe.db.get_value("Pricing Rule", name, "rate") != values["rate"]:
			frappe.db.set_value("Pricing Rule", name, "rate", values["rate"])
			result["changed"] += 1
	for name, title in frappe.db.get_all(
		"Pricing Rule", filters={"for_price_list": target}, fields=["name", "title"], as_list=True
	):
		if title not in titles:
			frappe.delete_doc("Pricing Rule", name, ignore_permissions=True)
			result["removed"] += 1
	return result


def sync_prices(rate: float | None = None) -> dict:
	"""Make the UAH price list from the USD one at the given (or the latest stored) rate."""
	config = settings()
	if not (config.master_price_list and config.uah_price_list):
		return {"skipped": "the price lists are not set"}
	if rate is None:
		stored = current_rate()
		if not stored:
			return {"skipped": "there is no rate"}
		rate = stored[0]
	step = float(config.rounding_step or 1)
	ensure_price_list(config.uah_price_list)
	result = {
		"rate": rate,
		"items": sync_item_prices(config.master_price_list, config.uah_price_list, rate, step),
		"rules": sync_pricing_rules(config.master_price_list, config.uah_price_list, rate, step),
	}
	# dropped now (a request in this transaction reads the new prices) and again after the commit: a request between
	# the two would read the old committed prices and keep them for ten minutes
	frappe.cache().delete_value(SHEET_KEY)
	frappe.db.after_commit.add(lambda: frappe.cache().delete_value(SHEET_KEY))
	return result


def latest_rate() -> float | None:
	"""The rate that the hourly job applied last: the newest stored one, also when the bank dated it tomorrow."""
	rate = frappe.db.get_value(
		"Currency Exchange",
		{"from_currency": FROM_CURRENCY, "to_currency": TO_CURRENCY, "for_selling": 1},
		"exchange_rate",
		order_by="date desc",
	)
	return float(rate) if rate else None


def refresh() -> None:
	"""Hook after a migrate: make the UAH prices again from the rate that the hourly job applied last, so that a change
	of how they are made (the step of an item, a new rule) reaches the site with the new code and not with the next rate
	of the bank. The prices do not change when nothing did, and a failure must not stop the migrate: its writes are
	rolled back to the savepoint and logged."""
	rate = latest_rate()
	if rate is None:
		return
	frappe.db.savepoint(SAVEPOINT)
	try:
		sync_prices(rate)
	except Exception:  # noqa: BLE001 - whatever goes wrong with the prices, the migrate goes on
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(title="The UAH prices were not made after the migrate")


def price_sheet() -> dict:
	"""The prices of the UAH list for the calculator of the site: {"items": {code: price}, "slabs": {code: rows}}.

	The page of the calculator embeds the prices of the day it was published; it reads these on opening, so it
	shows the prices the cart charges. A row of the slabs is (min qty, max qty, price) of a quantity rule; max 0
	means no upper limit, as in the Pricing Rule.
	"""
	cached = frappe.cache().get_value(SHEET_KEY)
	if cached is not None:
		return cached
	target = settings().uah_price_list
	sheet = {"items": {}, "slabs": {}}
	if target:
		sheet["items"] = {
			row.item_code: row.price_list_rate
			for row in frappe.get_all(
				"Item Price",
				filters={"price_list": target, "selling": 1},
				fields=["item_code", "price_list_rate"],
				limit_page_length=0,
			)
		}
		for row in frappe.get_all(
			"Pricing Rule",
			filters={"for_price_list": target, "disable": 0, "selling": 1, "apply_on": "Item Code"},
			fields=[
				"`tabPricing Rule Item Code`.item_code as item_code",
				"min_qty",
				"max_qty",
				"rate",
				"valid_from",
				"valid_upto",
			],
			limit_page_length=0,
		):
			if not in_force(row):
				continue
			sheet["slabs"].setdefault(row.item_code, []).append([row.min_qty, row.max_qty, row.rate])
		for rows in sheet["slabs"].values():
			rows.sort()
	if sheet[
		"items"
	]:  # an empty sheet (no list yet, or one being made) is not kept: the next request asks again
		frappe.cache().set_value(SHEET_KEY, sheet, expires_in_sec=SHEET_SECONDS)
	return sheet


def in_force(rule, today=None) -> bool:
	"""A pricing rule that applies today (the cart ignores one outside of its dates, so the calculator does too)."""
	today = today or frappe.utils.getdate()
	start, end = rule.get("valid_from"), rule.get("valid_upto")
	return (not start or frappe.utils.getdate(start) <= today) and (
		not end or frappe.utils.getdate(end) >= today
	)


def update() -> dict:
	"""The job of the scheduler: fetch the rate; when it is new, make the UAH prices from it."""
	try:
		rate, date = fetch_nbu_rate()
	except (requests.RequestException, ValueError) as error:
		frappe.log_error(title="The rate of the National Bank was not fetched", message=str(error))
		return {"error": str(error)}
	if not store_rate(rate, date):
		return {"rate": rate, "date": str(date), "new": False}
	frappe.db.commit()
	return {"rate": rate, "date": str(date), "new": True, **sync_prices(rate)}
