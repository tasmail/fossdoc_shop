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
