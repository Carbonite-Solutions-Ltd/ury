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


def run_split_invoice_tests(*, verbosity: int = 2) -> str:
    """Invoke via
    `bench --site <site> execute ury.ury.doctype.ury_order.test_split_invoice.run_split_invoice_tests`.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ItemSplitPlanTests))
    result = unittest.TextTestRunner(verbosity=verbosity, stream=None).run(suite)
    line = (
        f"[URY split tests] ran={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)}"
    )
    print(line)
    return line
