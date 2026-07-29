# Copyright (c) 2026, Carbonite and contributors
# For license information, please see license.txt

"""Unit tests for per-outlet warehouse resolution (_pick_outlet_warehouse).

The rule under test: an item's Default Warehouse names the stock CATEGORY, the
till's cost centre names the OUTLET, and the sale deducts from the warehouse
that is both. See _pick_outlet_warehouse's docstring for why a single Item
Default cannot express this on a one-company site.

Run:
    bench --site <site> execute \
      ury.ury.doctype.ury_order.test_outlet_warehouse.run_outlet_warehouse_tests

(Direct unittest runner per CLAUDE.md rule 6 — bench run-tests is blocked by a
pre-existing ERPNext bootstrap issue on this bench.)
"""

import unittest

from ury.ury.doctype.ury_order.ury_order import _pick_outlet_warehouse


# A cut-down version of the real Landing Restaurant tree: four category groups,
# each with an Airport / Sitout / HO leaf, plus the Food group's unsuffixed
# warehouse that is Airport's by convention (the one being renamed).
TREE = {
    # --- Beverage ---
    "Beverage Stores WH": {"is_group": 1, "parent_warehouse": "All Warehouses", "cost_center": None},
    "Beverage - Airport": {"is_group": 0, "parent_warehouse": "Beverage Stores WH", "cost_center": "200 - Airport"},
    "Beverage - Sitout": {"is_group": 0, "parent_warehouse": "Beverage Stores WH", "cost_center": "300 - Sitout"},
    "Beverage - HO": {"is_group": 0, "parent_warehouse": "Beverage Stores WH", "cost_center": "400 - HO"},
    # --- Food ---
    "Food Warehouse WH": {"is_group": 1, "parent_warehouse": "All Warehouses", "cost_center": None},
    "Food - Airport": {"is_group": 0, "parent_warehouse": "Food Warehouse WH", "cost_center": "200 - Airport"},
    "Food - Sitout": {"is_group": 0, "parent_warehouse": "Food Warehouse WH", "cost_center": "300 - Sitout"},
    # --- Operating Supplies: only HO exists (an incomplete category) ---
    "Ops Store WH": {"is_group": 1, "parent_warehouse": "All Warehouses", "cost_center": None},
    "Ops - HO": {"is_group": 0, "parent_warehouse": "Ops Store WH", "cost_center": "400 - HO"},
    # --- A standalone warehouse with no group and no outlet split ---
    "Finished Menu": {"is_group": 0, "parent_warehouse": "All Warehouses", "cost_center": None},
    # --- An untagged leaf under a tagged group ---
    "Beverage - Untagged": {"is_group": 0, "parent_warehouse": "Beverage Stores WH", "cost_center": None},
}

AIRPORT = "200 - Airport"
SITOUT = "300 - Sitout"
HO = "400 - HO"


class OutletWarehouseTests(unittest.TestCase):
    # ---------------------------------------------------------------- the ask

    def test_fanta_at_airport_deducts_from_airport(self):
        """The motivating case: one product, two tills, outlet decides."""
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", AIRPORT, TREE),
            "Beverage - Airport",
        )

    def test_fanta_at_sitout_deducts_from_sitout(self):
        """Same item default, different till -> different warehouse."""
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", SITOUT, TREE),
            "Beverage - Sitout",
        )

    def test_fanta_at_ho_deducts_from_ho(self):
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", HO, TREE),
            "Beverage - HO",
        )

    def test_the_actual_landing_bug(self):
        """A drink defaulted to a FOOD warehouse still resolves to the drink's
        own category for that outlet once the default is corrected. Guards the
        regression where B5009 looked for itself in Food Stores."""
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Sitout", AIRPORT, TREE),
            "Beverage - Airport",
        )

    # ------------------------------------------------------------- item default
    # points at the GROUP rather than a leaf (17 items on landing do this)

    def test_group_default_resolves_to_outlet_leaf(self):
        self.assertEqual(
            _pick_outlet_warehouse("Beverage Stores WH", SITOUT, TREE),
            "Beverage - Sitout",
        )

    def test_group_default_with_no_leaf_for_outlet_falls_back(self):
        """Ops has only an HO leaf; an Airport till falls back to the group."""
        self.assertEqual(
            _pick_outlet_warehouse("Ops Store WH", AIRPORT, TREE),
            "Ops Store WH",
        )

    # ----------------------------------------------------------------- fallbacks

    def test_no_cost_centre_keeps_item_default(self):
        """Till has no cost centre -> behave exactly as before this feature."""
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", None, TREE),
            "Beverage - Airport",
        )
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", "", TREE),
            "Beverage - Airport",
        )

    def test_category_missing_outlet_falls_back_not_guesses(self):
        """Food has no HO leaf. Must NOT silently drain Airport or Sitout."""
        self.assertEqual(
            _pick_outlet_warehouse("Food - Airport", HO, TREE),
            "Food - Airport",
        )

    def test_standalone_warehouse_with_no_outlet_split(self):
        """Finished Menu has no per-outlet children -> unchanged."""
        self.assertEqual(
            _pick_outlet_warehouse("Finished Menu", AIRPORT, TREE),
            "Finished Menu",
        )

    def test_unknown_warehouse_falls_back(self):
        """Default warehouse not in the tree (disabled, other company)."""
        self.assertEqual(
            _pick_outlet_warehouse("Nonexistent WH", AIRPORT, TREE),
            "Nonexistent WH",
        )

    def test_no_default_warehouse_returns_none(self):
        self.assertIsNone(_pick_outlet_warehouse(None, AIRPORT, TREE))
        self.assertIsNone(_pick_outlet_warehouse("", AIRPORT, TREE))

    # ------------------------------------------------------------- edge cases

    def test_untagged_leaf_is_never_selected(self):
        """A leaf with no cost centre must not be picked for any outlet."""
        for cc in (AIRPORT, SITOUT, HO):
            self.assertNotEqual(
                _pick_outlet_warehouse("Beverage Stores WH", cc, TREE),
                "Beverage - Untagged",
            )

    def test_already_correct_warehouse_is_left_alone(self):
        """Short-circuit: default already carries the till's cost centre."""
        self.assertEqual(
            _pick_outlet_warehouse("Food - Sitout", SITOUT, TREE),
            "Food - Sitout",
        )

    def test_unknown_cost_centre_falls_back(self):
        """A cost centre no warehouse is tagged with must not pick at random."""
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", "999 - Nowhere", TREE),
            "Beverage - Airport",
        )

    def test_empty_tree_falls_back(self):
        self.assertEqual(
            _pick_outlet_warehouse("Beverage - Airport", AIRPORT, {}),
            "Beverage - Airport",
        )

    def test_resolution_is_deterministic(self):
        """Same inputs, same answer — dict ordering must not leak through."""
        first = _pick_outlet_warehouse("Beverage Stores WH", AIRPORT, TREE)
        for _ in range(20):
            self.assertEqual(
                _pick_outlet_warehouse("Beverage Stores WH", AIRPORT, TREE), first
            )


def run_outlet_warehouse_tests():
    """Direct runner — see module docstring."""
    suite = unittest.TestLoader().loadTestsFromTestCase(OutletWarehouseTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        "\n%d run, %d failures, %d errors"
        % (result.testsRun, len(result.failures), len(result.errors))
    )
    return {
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }
