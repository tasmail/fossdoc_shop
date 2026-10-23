app_name = "fossdoc_shop"
app_title = "FossDoc Shop"
app_publisher = "FOSS-On-Line"
app_description = "FossDoc shop: calculation e-mail, commercial offer PDF and orders"
app_email = "foss@foss.ua"
app_license = "gpl-3.0"

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

# The Download PDF button of the print page sends the word None and the Pay button of an order is refused to a
# customer: see overrides.download_pdf and overrides.make_payment_request.
override_whitelisted_methods = {
	"frappe.utils.print_format.download_pdf": "fossdoc_shop.overrides.download_pdf"
}
