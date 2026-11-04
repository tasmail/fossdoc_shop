"""Where the payment of an order is. These tests need no Frappe site (the decision is plain Python)."""

import json
import unittest
from datetime import datetime, timedelta

from fossdoc_shop import payment_state as ps

NOW = datetime(2026, 11, 3, 16, 30)


def irequest(minutes_ago, status="Queued", output=None, name="WFP-1", service="WayForPay"):
	return {
		"name": name,
		"status": status,
		"creation": NOW - timedelta(minutes=minutes_ago),
		"output": json.dumps(output) if output else None,
		"service": service,
	}


def request(irequests, name="PRQ-2", total=45.67, account="WayForPay-Shop - FD"):
	return {"name": name, "grand_total": total, "payment_gateway_account": account, "irequests": irequests}


class TestWindows(unittest.TestCase):
	def test_a_payment_started_a_few_minutes_ago_is_recent(self):
		self.assertTrue(ps.is_recent(irequest(2), NOW))
		self.assertTrue(ps.is_recent(irequest(15), NOW))
		self.assertFalse(ps.is_recent(irequest(16), NOW))

	def test_the_bank_answered_in_process_until_the_order_expires(self):
		answered = {"transactionStatus": "InProcessing"}
		self.assertTrue(ps.is_answered(irequest(120, output=answered), NOW))
		self.assertFalse(ps.is_answered(irequest(25 * 60, output=answered), NOW))
		# the window is the order_timeout of the gateway settings
		self.assertTrue(ps.is_answered(irequest(25 * 60, output=answered), NOW, timedelta(days=2)))

	def test_no_word_of_the_bank_is_not_an_answer(self):
		self.assertFalse(ps.is_answered(irequest(2), NOW))

	def test_a_settled_payment_is_neither_recent_nor_answered(self):
		answered = {"transactionStatus": "InProcessing"}
		for status in ("Completed", "Failed", "Cancelled", "Authorized"):
			self.assertFalse(ps.is_recent(irequest(1, status=status), NOW), status)
			self.assertFalse(ps.is_answered(irequest(1, status=status, output=answered), NOW), status)

	def test_a_broken_output_is_no_answer(self):
		row = irequest(60)
		row["output"] = "{not json"
		self.assertFalse(ps.is_answered(row, NOW))

	def test_the_statuses_that_the_modules_use_exist_in_erpnext(self):
		self.assertEqual(ps.OPEN_STATUSES, ("Requested",))
		self.assertEqual(ps.WAITING, ("Queued",))


class TestClassify(unittest.TestCase):
	def test_the_incident_a_second_press_two_minutes_after_the_first_continues_on_the_same_page(self):
		# the customer may have closed the bank page: he is not locked out, he is sent back to the same reference
		state = ps.classify([request([irequest(2, name="WFP-1")])], NOW, 45.67, "WayForPay-Shop - FD")

		self.assertEqual(
			state, {"state": "continue", "request": "PRQ-2", "irequest": "WFP-1", "recent": True}
		)

	def test_an_old_page_is_continued_without_the_recent_text(self):
		state = ps.classify([request([irequest(60, name="WFP-9")])], NOW, 45.67, "WayForPay-Shop - FD")

		self.assertEqual(
			state, {"state": "continue", "request": "PRQ-2", "irequest": "WFP-9", "recent": False}
		)

	def test_an_answer_in_process_of_the_bank_is_a_hard_block(self):
		answered = irequest(40, output={"transactionStatus": "InProcessing"})
		state = ps.classify([request([answered])], NOW, 45.67, "WayForPay-Shop - FD")

		self.assertEqual(state["state"], ps.PROCESSING)

	def test_an_answer_of_the_bank_blocks_whatever_the_amount_and_the_account(self):
		answered = irequest(40, output={"transactionStatus": "InProcessing"})
		state = ps.classify([request([answered], total=10)], NOW, 45.67, "Stripe - FD")

		self.assertEqual(state["state"], ps.PROCESSING)

	def test_an_expired_page_is_not_reused_but_the_request_is_continued(self):
		state = ps.classify([request([irequest(30 * 60)])], NOW, 45.67)

		self.assertEqual(state["state"], ps.CONTINUE)
		self.assertIsNone(state["irequest"])

	def test_the_newest_page_is_reused(self):
		rows = [irequest(300, name="OLD"), irequest(100, name="NEW")]
		self.assertEqual(ps.reusable_page(rows, NOW), "NEW")

	def test_a_request_of_another_amount_or_account_is_left_to_erpnext_when_it_is_old(self):
		self.assertIsNone(ps.classify([request([irequest(60)], total=10)], NOW, 45.67))
		self.assertIsNone(ps.classify([request([irequest(60)])], NOW, 45.67, "Stripe - FD"))
		self.assertIsNotNone(ps.classify([request([irequest(60)], total=45.674)], NOW, 45.67))

	def test_a_recent_request_that_does_not_fit_is_never_cancelled(self):
		state = ps.classify([request([irequest(3)], total=10)], NOW, 45.67, "Stripe - FD")

		self.assertEqual(state["state"], ps.PROCESSING)

	def test_no_request_no_state(self):
		self.assertIsNone(ps.classify([], NOW, 45.67))


if __name__ == "__main__":
	unittest.main()
