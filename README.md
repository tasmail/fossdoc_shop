# fossdoc_shop

Frappe app of the FossDoc shop (fossdoc.com): the calculation e-mail, the commercial offer PDF and orders.

Developed in the Docker dev bench of `tasmail/erpnext-infra` (`dev-bench/run.sh`), which mounts this directory.
Changes only by pull requests with tests (`dev-bench/run.sh test fossdoc_shop`).

The unit tests need a Frappe site, so they run in the dev bench; CI checks the style (`ruff`).

## The order page

`templates/pages/order.html` is a copy of the page of Webshop (`webshop/webshop/templates/pages/order.html`, branch
`version-15`, commit `a355cda`) with one change, the Pay button. The stock page shows `Pay <grand_total>` on every
Sales Order, paid or not; here `templates/pages/order.py` adds the unpaid remainder (the amount that the Payment Request
charges) and the button is shown only for a submitted document with a remainder above zero, printing that remainder.
A paid Sales Order shows a "Paid" mark instead; a Quotation, which cannot be paid, has no button. The page is found
before the one of Webshop because the app is installed after Webshop (`required_apps`); on a Webshop upgrade diff the copy
with the stock file.
