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

## A payment that is already in progress

When the customer presses Pay a second time, ERPNext (`make_payment_request`, order type Shopping Cart) cancels the open
Payment Request of the order and makes a new one. A customer who then pays on the first page of the gateway has paid for
a cancelled request. The shop therefore never replaces a payment in progress (`payment_state.py`, used by the wrapper
`overrides.make_payment_request` and by the order page):

- **The bank is processing it**: an Integration Request of an open request (docstatus 1, `Requested`/`Pending`) is
  `Queued`/`Pending` and was created in the last 15 minutes, or the gateway has answered "in process" (the output holds a
  `transactionStatus`) and the gateway order is younger than 24 hours. Pay starts nothing and redirects to the order page
  (`?payment=processing`), which shows a pop-up and the notice "Оплата цього замовлення вже розпочата ... Не оплачуйте
  повторно". The page has no payment button in this state.
- **An open request was left on its page**: a request of the same gateway account whose amount equals the remaining
  amount is not replaced. Pay (and "Продовжити оплату" in the notice) redirects to the same WayForPay page, the same
  reference (`/wayforpay_checkout?order=<Integration Request>`); when that page is older than 24 hours a new payment page of
  the same request is made.
- Any other case (no open request, another amount or account, loyalty points) goes to ERPNext as before. The checks of the
  wrapper (`has_website_permission`, the call as Administrator) are unchanged. After payment the page shows "Paid".

The texts are Ukrainian source strings translated by `translations/en.csv` and `translations/ru.csv`. The decision
(`payment_state.classify`) is plain Python and tested without a site (`tests/test_payment_state.py`,
`tests/test_order_page.py`); the wrapper, the translations and the database queries are tested in the bench
(`tests/test_overrides.py`, `tests/test_i18n.py`). The booking of a payment that still arrives for a cancelled request is
the job of the `wayforpay` app.
