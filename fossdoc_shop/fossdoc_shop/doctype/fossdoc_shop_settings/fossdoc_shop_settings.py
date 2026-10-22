from frappe.model.document import Document


class FossDocShopSettings(Document):
	"""The requisites, the contacts and the colours of the letter and the offer of the shop.

	The deploy of the site fills them (erpnext-infra, press/fossdoc_shop.py); a manager can change them here.
	"""
