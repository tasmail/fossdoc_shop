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


class TestIsProcessing(unittest.TestCase):
	def test_a_payment_started_a_few_minutes_ago_may_be_in_the_hands_of_the_bank(self):
		self.assertTrue(ps.is_processing(irequest(2), NOW))
		self.assertTrue(ps.is_processing(irequest(15, status="Pending"), NOW))

	def test_an_old_payment_with_no_word_of_the_bank_was_left_on_its_page(self):
		self.assertFalse(ps.is_processing(irequest(16), NOW))

	def test_a_payment_that_the_bank_answered_in_process_stays_so_until_the_order_expires(self):
		answered = {"transactionStatus": "InProcessing"}
		self.assertTrue(ps.is_processing(irequest(120, output=answered), NOW))
		self.assertFalse(ps.is_processing(irequest(25 * 60, output=answered), NOW))

	def test_a_settled_payment_is_not_in_process(self):
		for status in ("Completed", "Failed", "Cancelled", "Authorized"):
			self.assertFalse(ps.is_processing(irequest(1, status=status), NOW), status)

	def test_a_broken_output_is_no_answer(self):
		row = irequest(60)
		row["output"] = "{not json"
		self.assertFalse(ps.is_processing(row, NOW))


class TestClassify(unittest.TestCase):
	def test_the_incident_a_second_press_two_minutes_after_the_first_is_a_payment_in_process(self):
		state = ps.classify([request([irequest(2)])], NOW, 45.67, "WayForPay-Shop - FD")

		self.assertEqual(state, {"state": "processing", "request": "PRQ-2", "irequest": None})

	def test_an_open_request_that_was_left_on_its_page_is_continued_on_the_same_reference(self):
		state = ps.classify([request([irequest(60, name="WFP-9")])], NOW, 45.67, "WayForPay-Shop - FD")

		self.assertEqual(state, {"state": "continue", "request": "PRQ-2", "irequest": "WFP-9"})

	def test_an_expired_page_is_not_reused_but_the_request_is_continued(self):
		state = ps.classify([request([irequest(30 * 60)])], NOW, 45.67)

		self.assertEqual(state, {"state": "continue", "request": "PRQ-2", "irequest": None})

	def test_the_newest_page_is_reused(self):
		rows = [irequest(300, name="OLD"), irequest(100, name="NEW")]
		self.assertEqual(ps.reusable_page(rows, NOW), "NEW")

	def test_a_request_of_another_amount_or_account_is_left_to_erpnext(self):
		self.assertIsNone(ps.classify([request([irequest(60)], total=10)], NOW, 45.67))
		self.assertIsNone(ps.classify([request([irequest(60)])], NOW, 45.67, "Stripe - FD"))
		self.assertIsNotNone(ps.classify([request([irequest(60)], total=45.674)], NOW, 45.67))

	def test_a_payment_in_process_wins_whatever_the_amount_and_the_account(self):
		state = ps.classify([request([irequest(3)], total=10)], NOW, 45.67, "Stripe - FD")

		self.assertEqual(state["state"], ps.PROCESSING)

	def test_no_request_no_state(self):
		self.assertIsNone(ps.classify([], NOW, 45.67))


if __name__ == "__main__":
	unittest.main()
