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
	wanted = {
		row.item_code: round_to_step(row.price_list_rate * rate, step)
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
	return {
		"rate": rate,
		"items": sync_item_prices(config.master_price_list, config.uah_price_list, rate, step),
		"rules": sync_pricing_rules(config.master_price_list, config.uah_price_list, rate, step),
	}


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
