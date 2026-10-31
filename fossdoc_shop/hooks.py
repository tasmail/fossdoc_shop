app_name = "fossdoc_shop"
app_title = "FossDoc Shop"
app_publisher = "FOSS-On-Line"
app_description = "FossDoc shop: calculation e-mail, commercial offer PDF and orders"
app_email = "foss@foss.ua"
app_license = "gpl-3.0"
# installed after these: the classes and the endpoints of the shop replace theirs
required_apps = ["erpnext", "payments", "wayforpay", "webshop"]

jinja = {
	"methods": [
		"fossdoc_shop.calculation.parse_calculation",
		"fossdoc_shop.calculation.describe",
		"fossdoc_shop.calculation.money",
		"fossdoc_shop.branding.brand",
		"fossdoc_shop.licensing.license_info",
		"fossdoc_shop.downloads.download_links",
		"fossdoc_shop.payment.payment_order",
	]
}

after_install = [
	"fossdoc_shop.orders.ensure_item_fields",
	"fossdoc_shop.setup.ensure_calculation_mail",
	"fossdoc_shop.setup.ensure_payment_mail",
]
after_migrate = [
	"fossdoc_shop.orders.ensure_item_fields",
	"fossdoc_shop.setup.ensure_calculation_mail",
	"fossdoc_shop.setup.ensure_payment_mail",
	"fossdoc_shop.rates.refresh",
]

doc_events = {
	"Email Queue": {"before_insert": "fossdoc_shop.overrides.set_reply_to"},
	"Customer": {"before_insert": "fossdoc_shop.orders.set_language"},
	"User": {"before_insert": "fossdoc_shop.orders.set_language"},
	"Quotation": {
		"before_insert": ["fossdoc_shop.orders.require_open_shop", "fossdoc_shop.orders.set_language"],
		"before_validate": "fossdoc_shop.orders.limit_quantities",
	},
	"Sales Order": {
		"before_insert": ["fossdoc_shop.orders.require_open_shop", "fossdoc_shop.orders.set_language"],
		"before_validate": "fossdoc_shop.orders.limit_quantities",
	},
}

# A payment of a customer is booked as the administrator: see overrides.PaymentRequest.
override_doctype_class = {
	"Payment Request": "fossdoc_shop.overrides.PaymentRequest",
	"Customer": "fossdoc_shop.overrides.Customer",
}

# The Download PDF button of the print page sends the word None and the Pay button of an order is refused to a
# customer: see overrides.download_pdf and overrides.make_payment_request.
override_whitelisted_methods = {
	"frappe.utils.print_format.download_pdf": "fossdoc_shop.overrides.download_pdf",
	"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request": (
		"fossdoc_shop.overrides.make_payment_request"
	),
}

# The rate of the National Bank: a new one makes the prices in hryvnia (see rates.py).
scheduler_events = {"hourly": ["fossdoc_shop.rates.update"]}
