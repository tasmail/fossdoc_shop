app_name = "fossdoc_shop"
app_title = "FossDoc Shop"
app_publisher = "FOSS-On-Line"
app_description = "FossDoc shop: calculation e-mail, commercial offer PDF and orders"
app_email = "foss@foss.ua"
app_license = "gpl-3.0"
# installed after these: the classes and the endpoints of the shop replace theirs
required_apps = ["erpnext", "payments", "webshop"]

jinja = {
	"methods": [
		"fossdoc_shop.calculation.parse_calculation",
		"fossdoc_shop.calculation.describe",
		"fossdoc_shop.branding.brand",
	]
}

after_install = "fossdoc_shop.setup.ensure_calculation_mail"
after_migrate = ["fossdoc_shop.setup.ensure_calculation_mail"]

doc_events = {"Email Queue": {"before_insert": "fossdoc_shop.overrides.set_reply_to"}}

# A payment of a customer is booked as the administrator: see overrides.PaymentRequest.
override_doctype_class = {"Payment Request": "fossdoc_shop.overrides.PaymentRequest"}

# The Download PDF button of the print page sends the word None and the Pay button of an order is refused to a
# customer: see overrides.download_pdf and overrides.make_payment_request.
override_whitelisted_methods = {
	"frappe.utils.print_format.download_pdf": "fossdoc_shop.overrides.download_pdf",
	"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request": (
		"fossdoc_shop.overrides.make_payment_request"
	),
}
