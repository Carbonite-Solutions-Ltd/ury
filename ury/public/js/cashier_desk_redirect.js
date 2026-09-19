// URY Cashier / Production User desk redirect.
//
// Loaded into the Frappe desk via `app_include_js` in hooks.py. When a
// user with ONLY the URY Cashier role (no elevated role like System
// Manager / URY Manager / URY Captain) opens /app or /desk, this
// script immediately replaces the location with /pos.
//
// This is the sole mechanism for the cashier lockdown — modern Frappe
// (v15+) removed the User.home_page field that we'd otherwise use to
// configure a smoother server-side post-login redirect. The field
// `default_app` exists but requires registering URY POS as a Frappe
// "app" via `add_to_apps_screen` and using a Select field whose
// options are populated dynamically — more invasive than warranted.
//
// Trade-off: there's a brief flash of the desk before the redirect
// fires (the desk page loads, app_include_js runs, then we redirect).
// Acceptable for a feature meant to keep cashiers out of the desk —
// they're still kept out, just with a half-second flash on the way.

(function () {
	if (typeof frappe === "undefined" || !frappe.user) return;

	var elevated = [
		"Administrator",
		"System Manager",
		"URY Manager",
		"URY Captain",
	];
	var hasElevated = elevated.some(function (role) {
		return frappe.user.has_role(role);
	});
	if (hasElevated) return;

	// Kitchen / bar staff go to the kitchen screen (2026-09-18). Checked
	// before the POS roles so it matches the login landing, which comes from
	// the URY Production User role's home page. /Mosaic with no unit sends
	// them to their own unit, or to a picker when they have several.
	if (frappe.user.has_role("URY Production User")) {
		window.location.replace("/Mosaic");
		return;
	}

	// POS-only roles (cashier + self-serve waiter) get bounced to /pos.
	var isPosOnly =
		frappe.user.has_role("URY Cashier") || frappe.user.has_role("URY Waiter");

	if (isPosOnly) {
		// Replace (not assign) so the desk doesn't sit in browser history.
		window.location.replace("/pos");
	}
})();
