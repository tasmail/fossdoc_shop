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
- Two presses at once are serialised by a lock of the database connection on the document (`GET_LOCK` of MariaDB, keyed
  by site, doctype and name; `payment_state.document_lock`). A row lock (`FOR UPDATE`) is not enough: it waits for the
  first press, but the reads that follow still see the snapshot that the transaction opened earlier (REPEATABLE READ)
  and miss the request that the first press committed. So after getting the lock the wrapper ends its transaction
  (nothing has been written), looks at the open requests, calls ERPNext or redirects, commits and only then releases the
  lock (in a `finally`, on every path). A press that cannot get the lock in 30 seconds is sent to the page of the document
  with the "in process" notice, not to an error. The order of these calls is asserted in `tests/test_overrides.py`.
- The links disable themselves on the first click (`aria-disabled`, a repeated click or Enter is ignored) and come back
  when the page is restored by the Back button (`pageshow` with `persisted`), see `templates/payment_links.html`.
- The refusal of a call with loyalty points names the open payment and asks to finish it first; it does not promise the
  same page, because that call changes the amount.
- **Unverified: the same reference opened again.** "Continue" opens the page of the same Integration Request, i.e. the
  same `orderReference`, but `payment_form` of the wayforpay app signs a new `orderDate` (the current time) on every
  render. The Purchase page of WayForPay (wiki.wayforpay.com, checked) defines `orderReference` as "unique number of the
  order in merchant's system", `orderDate` as "date of order placing" and `orderTimeout` as "the interval within which the
  order can be paid, in seconds"; it says nothing about a repeated `orderReference`, about a changed `orderDate`, or about
  what `orderTimeout` counts from. So it is not known whether the gateway accepts the second render, and whether the
  timeout runs from the first date. Check it on the test merchant (open the continue link after the first page) before
  relying on it. If it is rejected, the minimal change belongs to the wayforpay app and is not made here: store the first
  `orderDate` in the data of the Integration Request when the form is first built and sign that value again in
  `checkout.payment_form` (and send `orderTimeout` as the time left); the shop code does not change.
- After payment the page shows "Paid".

The texts are Ukrainian source strings translated by `translations/en.csv` and `translations/ru.csv`. The decision
(`payment_state.classify`) is plain Python and tested without a site (`tests/test_payment_state.py`,
`tests/test_order_page.py`); the wrapper (lock, invoices, loyalty points), the translations and the database queries are
tested in the bench (`tests/test_overrides.py`, `tests/test_i18n.py`). The booking of a payment that still arrives for a
cancelled request is the job of the `wayforpay` app.
