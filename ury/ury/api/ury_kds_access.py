"""Who may open which kitchen screen (URY Production Unit), and where a
kitchen user lands after login.

Each URY Production Unit carries a "Screen Access" table of users. The rules:

- A unit with an EMPTY table is open to anyone signed in. This keeps every
  existing screen working the day this ships; nothing is locked until an
  admin lists users on a unit.
- A unit with users listed is open only to those users, plus the elevated
  roles below.
- Administrator, System Manager, URY Manager and URY Captain can open every
  unit (they run the floor and must be able to look at any screen).

Landing (``/Mosaic`` with no unit): a user listed on exactly one unit goes
straight to it; listed on several, they get a picker; listed nowhere, they
see the open (empty-table) units, or a "not assigned" message if there are
none. Elevated users see every unit.

The pure functions at the top hold the rules so they can be unit-tested
without a database.
"""

import frappe
from frappe import _

PRODUCTION_ROLE = "URY Production User"

KDS_ELEVATED_ROLES = frozenset({"System Manager", "URY Manager", "URY Captain"})

# Menu Course mode screens (see ury_kot_display.MENU_COURSE_TARGETS). They
# are not access-gated: the Screen Access table lives on production units.
DEPARTMENT_SCREENS = ("Food", "Drinks", "Other", "All")


# ───────────────────────────────────────────────────────────────────
# Pure rules
# ───────────────────────────────────────────────────────────────────


def is_kds_elevated(user, roles):
	"""True for users who may open every unit regardless of the tables."""
	if user == "Administrator":
		return True
	return bool(set(roles or ()) & KDS_ELEVATED_ROLES)


def can_open_unit(unit_users, user, elevated):
	"""May ``user`` open a unit whose Screen Access table is ``unit_users``?"""
	if elevated:
		return True
	if not unit_users:
		return True  # empty table = open to anyone signed in
	return user in unit_users


def units_for_user(unit_users_map, user, elevated):
	"""Which units belong in ``user``'s picker, in the map's order.

	Returns ``(unit_names, scope)`` where scope is:
	  - ``"all"``      elevated: every unit
	  - ``"assigned"`` the units the user is listed on
	  - ``"open"``     listed nowhere: the units with an empty table
	  - ``"none"``     listed nowhere and every unit is restricted
	"""
	names = list(unit_users_map)
	if elevated:
		return names, "all"
	assigned = [n for n in names if user in unit_users_map[n]]
	if assigned:
		return assigned, "assigned"
	open_units = [n for n in names if not unit_users_map[n]]
	return open_units, ("open" if open_units else "none")


def screen_groups(routing_modes):
	"""Which kinds of screen the picker offers, from the POS Profiles' modes.

	Production units are only real screens in "URY Production Unit" mode; in
	"Menu Course" mode the screens are the departments. A site running both
	(different outlets) gets both. Returns ``(show_units, department_screens)``.
	"""
	modes = {m or "Menu Course" for m in routing_modes}
	if not modes:
		return True, []
	show_units = "URY Production Unit" in modes
	departments = list(DEPARTMENT_SCREENS) if "Menu Course" in modes else []
	return show_units, departments


# ───────────────────────────────────────────────────────────────────
# Data access
# ───────────────────────────────────────────────────────────────────


def _load_units():
	"""All production units, ordered by name, plus each unit's user set."""
	units = frappe.get_all(
		"URY Production Unit",
		fields=["name", "unit_type", "branch"],
		order_by="name asc",
	)
	rows = frappe.db.sql(
		"""
		SELECT parent, user
		FROM `tabURY Production Unit User`
		WHERE parenttype = 'URY Production Unit' AND IFNULL(user, '') != ''
		""",
		as_dict=True,
	)
	users_map = {u.name: set() for u in units}
	for r in rows:
		if r.parent in users_map:
			users_map[r.parent].add(r.user)
	return units, users_map


def _session_elevated(user=None):
	user = user or frappe.session.user
	return is_kds_elevated(user, frappe.get_roles(user))


def unit_access_denied(target, user=None):
	"""True when ``target`` is a real production unit the user may not open.

	A target that is not a production unit (a Menu Course department such as
	"Food", or "All") is never denied here, since the Screen Access table only
	exists on production units.
	"""
	if not target or not frappe.db.exists("URY Production Unit", target):
		return False
	user = user or frappe.session.user
	elevated = _session_elevated(user)
	if elevated:
		return False
	unit_users = set(
		frappe.get_all(
			"URY Production Unit User",
			filters={"parent": target, "parenttype": "URY Production Unit"},
			pluck="user",
		)
	)
	return not can_open_unit(unit_users, user, False)


def require_unit_access(target):
	"""Throw a PermissionError when the user may not open ``target``."""
	if unit_access_denied(target):
		frappe.throw(
			_("You don't have access to the {0} screen. Ask a manager to add you to its Screen Access table.").format(
				target
			),
			frappe.PermissionError,
			title=_("No Access"),
		)


def kds_branch(target):
	"""The branch a KDS screen belongs to.

	A production unit carries its own branch, so a kitchen user does not
	need a URY User row on the Branch just to open their screen. Anything
	else (a Menu Course department, "All", a unit with no branch) falls back
	to the user's own branch.
	"""
	if target:
		branch = frappe.db.get_value("URY Production Unit", target, "branch")
		if branch:
			return branch
	from ury.ury_pos.api import getBranch

	return getBranch()


def branch_from_assigned_units(user):
	"""Branch of the first production unit ``user`` is listed on, or None.

	getBranch() falls back to this for a kitchen user who has no URY User
	row on any Branch.
	"""
	row = frappe.db.sql(
		"""
		SELECT pu.branch
		FROM `tabURY Production Unit User` puu
		INNER JOIN `tabURY Production Unit` pu ON pu.name = puu.parent
		WHERE puu.parenttype = 'URY Production Unit'
		  AND puu.user = %s
		  AND IFNULL(pu.branch, '') != ''
		ORDER BY pu.name
		LIMIT 1
		""",
		user,
	)
	return row[0][0] if row else None


# ───────────────────────────────────────────────────────────────────
# Endpoint
# ───────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_my_production_units(current=None):
	"""The units the signed-in user may pick, and whether ``current`` is allowed.

	The KDS calls this on load. With no ``current`` (the ``/Mosaic`` landing
	page) it routes on the list: one unit goes straight there, several show
	a picker. With a ``current`` unit it checks access before loading the board.
	"""
	user = frappe.session.user
	elevated = _session_elevated(user)
	units, users_map = _load_units()
	routing_modes = frappe.get_all(
		"POS Profile", filters={"disabled": 0}, pluck="custom_kds_routing_mode"
	)
	show_units, departments = screen_groups(routing_modes)
	if not show_units:
		units, users_map = [], {}
	names, scope = units_for_user(users_map, user, elevated)
	wanted = set(names)

	current_is_unit = bool(current) and current in users_map
	current_allowed = (
		can_open_unit(users_map[current], user, elevated) if current_is_unit else True
	)

	return {
		"units": [
			{"name": u.name, "unit_type": u.unit_type or "Kitchen", "branch": u.branch}
			for u in units
			if u.name in wanted
		],
		"departments": departments,
		"scope": scope,
		"elevated": int(elevated),
		"current_is_unit": int(current_is_unit),
		"current_allowed": int(current_allowed),
		"full_name": frappe.utils.get_fullname(user),
	}
