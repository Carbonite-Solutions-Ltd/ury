"""Unit tests for the item-split allocation planner.

Per CLAUDE.md rule 6, `bench run-tests` is blocked on this site by a
pre-existing ERPNext bootstrap trap. Run these via:

    bench --site <site> execute ury.ury.doctype.ury_order.test_split_invoice.run_split_invoice_tests

These cover the pure allocation math in `_plan_item_split` (partial qty,
over/under allocation, leftover detection, decimal qtys) — the non-trivial
logic of the item split. The surrounding `split_invoice_by_item` endpoint
is thin DB/ERPNext glue over this planner. See CLAUDE.md "Fixes log"
2026-06-05.
"""

from __future__ import annotations

import unittest

from ury.ury.doctype.ury_order import ury_order


def _codes(errors):
    return [code for (_idx, code, _row) in errors]


class ItemSplitPlanTests(unittest.TestCase):
    def test_clean_two_bill_split(self):
        item_qtys = {"r1": 2, "r2": 1}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 1}]},
            {
                "allocations": [
                    {"source_row": "r1", "qty": 1},
                    {"source_row": "r2", "qty": 1},
                ]
            },
        ]
        errors, _remaining, leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftovers, [])

    def test_partial_qty_split(self):
        # 5 of one item split 3 + 2.
        item_qtys = {"r1": 5}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 3}]},
            {"allocations": [{"source_row": "r1", "qty": 2}]},
        ]
        errors, _remaining, leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftovers, [])

    def test_under_allocation_leaves_leftover(self):
        # 3 + 1 of 5 → 1 left unallocated, no per-allocation error.
        item_qtys = {"r1": 5}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 3}]},
            {"allocations": [{"source_row": "r1", "qty": 1}]},
        ]
        errors, remaining, leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftovers, ["r1"])
        self.assertAlmostEqual(remaining["r1"], 1.0)

    def test_over_allocation_flagged(self):
        item_qtys = {"r1": 5}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 3}]},
            {"allocations": [{"source_row": "r1", "qty": 3}]},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertIn("over", _codes(errors))

    def test_empty_bill_flagged(self):
        item_qtys = {"r1": 1}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 1}]},
            {"allocations": []},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertIn("empty", _codes(errors))

    def test_unknown_row_flagged(self):
        item_qtys = {"r1": 1}
        bills = [
            {"allocations": [{"source_row": "rX", "qty": 1}]},
            {"allocations": [{"source_row": "r1", "qty": 1}]},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertIn("unknown", _codes(errors))

    def test_nonpositive_qty_flagged(self):
        item_qtys = {"r1": 1}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 0}]},
            {"allocations": [{"source_row": "r1", "qty": 1}]},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertIn("nonpositive", _codes(errors))

    def test_negative_qty_flagged(self):
        item_qtys = {"r1": 2}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": -1}]},
            {"allocations": [{"source_row": "r1", "qty": 2}]},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertIn("nonpositive", _codes(errors))

    def test_decimal_qty_split(self):
        # 1.0 split into 0.5 + 0.5 — float tolerance must hold.
        item_qtys = {"r1": 1.0}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 0.5}]},
            {"allocations": [{"source_row": "r1", "qty": 0.5}]},
        ]
        errors, _remaining, leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftovers, [])

    def test_three_way_split_full(self):
        item_qtys = {"r1": 6, "r2": 3}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 2}, {"source_row": "r2", "qty": 1}]},
            {"allocations": [{"source_row": "r1", "qty": 2}, {"source_row": "r2", "qty": 1}]},
            {"allocations": [{"source_row": "r1", "qty": 2}, {"source_row": "r2", "qty": 1}]},
        ]
        errors, _remaining, leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftovers, [])

    def test_bill_index_in_error(self):
        # The empty bill is index 1 (0-based) → error tuple carries idx=1.
        item_qtys = {"r1": 1}
        bills = [
            {"allocations": [{"source_row": "r1", "qty": 1}]},
            {"allocations": []},
        ]
        errors, _remaining, _leftovers = ury_order._plan_item_split(item_qtys, bills)
        self.assertTrue(any(idx == 1 and code == "empty" for (idx, code, _r) in errors))


class ManyBillsTests(unittest.TestCase):
    """A table of fourteen guests each wanting their own receipt.

    The old POS capped the split at 6 bills; the planner never had a limit,
    so these prove the backend was always ready for it.
    """

    def test_fourteen_bills_one_item_each(self):
        item_qtys = {f"r{i}": 1 for i in range(12)}
        item_qtys["jollof"] = 2
        rows = [{"source_row": k, "qty": 1} for k in item_qtys if k != "jollof"]
        rows += [{"source_row": "jollof", "qty": 1}] * 2
        bills = [{"allocations": [r]} for r in rows]
        self.assertEqual(len(bills), 14)
        errors, _remaining, leftover = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftover, [])

    def test_thirty_bills_still_planned(self):
        item_qtys = {"a": 30}
        bills = [{"allocations": [{"source_row": "a", "qty": 1}]} for _ in range(30)]
        errors, _remaining, leftover = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftover, [])

    def test_more_bills_than_items_flags_the_empty_one(self):
        """13 units across 14 bills leaves one empty - that must be rejected,
        not silently printed as a blank receipt."""
        item_qtys = {f"r{i}": 1 for i in range(13)}
        bills = [
            {"allocations": [{"source_row": f"r{i}", "qty": 1}]} for i in range(13)
        ]
        bills.append({"allocations": []})
        errors, _remaining, leftover = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(leftover, [])
        self.assertEqual(errors, [(13, "empty", None)])

    def test_fractional_row_split_across_bills(self):
        item_qtys = {"kg": 2.5}
        bills = [
            {"allocations": [{"source_row": "kg", "qty": 1}]},
            {"allocations": [{"source_row": "kg", "qty": 1}]},
            {"allocations": [{"source_row": "kg", "qty": 0.5}]},
        ]
        errors, _remaining, leftover = ury_order._plan_item_split(item_qtys, bills)
        self.assertEqual(errors, [])
        self.assertEqual(leftover, [])


def run_split_invoice_tests(*, verbosity: int = 2) -> str:
    """Invoke via
    `bench --site <site> execute ury.ury.doctype.ury_order.test_split_invoice.run_split_invoice_tests`.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ItemSplitPlanTests))
    suite.addTests(loader.loadTestsFromTestCase(ManyBillsTests))
    result = unittest.TextTestRunner(verbosity=verbosity, stream=None).run(suite)
    line = (
        f"[URY split tests] ran={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)}"
    )
    print(line)
    return line
