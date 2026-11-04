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
Payment Request of the document and makes a new one. A customer who then pays on the first page of the gateway has paid
for a cancelled request. The shop therefore never replaces a payment in progress (`payment_state.py`, used by the wrapper
`overrides.make_payment_request` and by the order page). The wrapper covers a Sales Order and a Sales Invoice (the rule of
the portal pages and the run as Administrator apply to both); the page asks for the same gateway account and amount.

- **An open request** (docstatus 1, status `Requested` or `Initiated`) of the same gateway account whose amount equals the remaining
  amount is continued, not replaced: Pay (and "Продовжити оплату" in the notice) redirects to the same WayForPay page, the
  same reference (`/wayforpay_checkout?order=<Integration Request>`). The Integration Request is created when the payment
  page is rendered, so a customer who closed the bank page can always go on. When the request was started in the last 15
  minutes the notice also says "if you have already paid, wait for the letter, do not pay again"; the timer only chooses
  the text. A page older than the gateway order life is not reused (a new payment page of the same request is made).
- **The bank answered "in process"** (the Queued Integration Request has a `transactionStatus` in its output, as for the
  anti-fraud checks) and the gateway order has not expired: a hard block. Pay starts nothing, redirects to the page of the
  document (`?payment=processing`, a pop-up shown once and then removed from the address) and the notice has no button.
  The life of the order is the longest `order_timeout` of the WayForPay Settings (a day when not set), like `checkout.py`
  of the wayforpay app.
- A recent open request that does not fit (another amount or account) is never cancelled either: it blocks like the
  answer of the bank. An old one that does not fit goes to ERPNext as before.
- A call with loyalty points while a payment is open is refused with a message and not passed on (the amount would
  differ and ERPNext would cancel the open request).
- Only the order type Shopping Cart is redirected: `cancel_old_payment_requests` of ERPNext runs only in that branch;
  the other order types subtract the open amount and cancel nothing.
- Two presses at once are serialised: the wrapper locks the document row (`SELECT ... FOR UPDATE`) before the check, and
  the lock is held until the commit that follows the new request or the redirect. The links also disable themselves on
  the first click.
- After payment the page shows "Paid".

The texts are Ukrainian source strings translated by `translations/en.csv` and `translations/ru.csv`. The decision
(`payment_state.classify`) is plain Python and tested without a site (`tests/test_payment_state.py`,
`tests/test_order_page.py`); the wrapper (lock, invoices, loyalty points), the translations and the database queries are
tested in the bench (`tests/test_overrides.py`, `tests/test_i18n.py`). The booking of a payment that still arrives for a
cancelled request is the job of the `wayforpay` app.
