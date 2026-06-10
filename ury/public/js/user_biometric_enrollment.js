/**
 * URY User form — "Enrol Biometrics" custom button.
 *
 * Adds a button to the User form that deep-links to the URY POS
 * enrollment page at /pos/biometric-enrollment, with the target user
 * preloaded. Only visible to captain / manager / admin users and only
 * when:
 *   - The user being edited has at least one URY login role
 *     (URY Cashier / URY Captain / URY Manager).
 *   - URY Biometric Settings.enabled is 1.
 *
 * The button lives under the "Biometrics" group in the menu. A second
 * item in the same group jumps straight to the user's enrollment
 * doctype in the desk (URY Biometric Enrollment/<user>) for admins
 * who want to inspect raw fields.
 *
 * Loaded via `doctype_js` in hooks.py. See also:
 *   - ury/ury/biometric/api.py — backend auth surface
 *   - pos/src/pages/BiometricEnrollment.tsx — the React wizard
 */

(function () {
	const URY_ROLES = ['URY Cashier', 'URY Captain', 'URY Manager'];
	const ADMIN_ROLES = ['Administrator', 'System Manager', 'URY Manager', 'URY Captain'];

	function callerIsEnrolmentAdmin() {
		if (!frappe.user) return false;
		if (frappe.user.name === 'Administrator') return true;
		const roles = frappe.user.has_role(ADMIN_ROLES);
		// has_role returns truthy when user has ANY of the passed roles in newer Frappe
		return Boolean(roles);
	}

	function userHasUryLoginRole(doc) {
		if (!doc || !Array.isArray(doc.roles)) return false;
		return doc.roles.some((r) => URY_ROLES.includes(r.role));
	}

	async function isBiometricEnabled() {
		try {
			const r = await frappe.call({
				method: 'frappe.client.get_single_value',
				args: { doctype: 'URY Biometric Settings', field: 'enabled' },
			});
			return Boolean(r && r.message);
		} catch {
			return false;
		}
	}

	function openEnrollmentInPOS(user) {
		const url = '/pos/biometric-enrollment?user=' + encodeURIComponent(user);
		window.open(url, '_blank');
	}

	function openEnrollmentDoctype(user) {
		window.open('/app/ury-biometric-enrollment/' + encodeURIComponent(user), '_blank');
	}

	async function openAdminReset(frm) {
		const user = frm.doc.name;
		const confirm = await new Promise((resolve) => {
			frappe.confirm(
				__(
					`Unlock ${user}'s PIN and clear the failed-attempt counter? ` +
						`Their fingerprint and PIN hash will remain intact.`
				),
				() => resolve(true),
				() => resolve(false)
			);
		});
		if (!confirm) return;
		try {
			await frappe.call({
				method: 'ury.ury.biometric.api.admin_reset_enrollment',
				args: { user: user, delete: 0 },
			});
			frappe.show_alert({
				message: __(`PIN unlocked for ${user}.`),
				indicator: 'green',
			});
		} catch (err) {
			frappe.msgprint({
				title: __('Reset failed'),
				message: (err && err.message) || __('Unknown error.'),
				indicator: 'red',
			});
		}
	}

	frappe.ui.form.on('User', {
		async refresh(frm) {
			if (!frm || !frm.doc) return;
			if (frm.is_new()) return;

			// NOTE: do NOT call frm.clear_custom_buttons() here — it takes no
			// group argument and clears ALL custom buttons (including the
			// standard "Reset Password", "Reset OTP Secret", etc. that
			// Frappe/ERPNext's user.js adds), leaving only our Biometrics
			// buttons. Frappe already clears custom buttons at the start of
			// every form refresh, and add_custom_button dedupes by label, so
			// our buttons never duplicate without this. See CLAUDE.md
			// "Fixes log" 2026-06-10.

			if (!callerIsEnrolmentAdmin()) return;
			if (!userHasUryLoginRole(frm.doc)) return;

			const enabled = await isBiometricEnabled();
			if (!enabled) {
				// Show a subtle hint button that opens the settings page
				frm.add_custom_button(
					__('Biometric Auth Disabled'),
					() => window.open('/app/ury-biometric-settings', '_blank'),
					__('Biometrics')
				);
				return;
			}

			frm.add_custom_button(
				__('Enrol Fingerprint + PIN'),
				() => openEnrollmentInPOS(frm.doc.name),
				__('Biometrics')
			);

			// Only show these when an enrollment exists for this user
			try {
				const r = await frappe.db.exists(
					'URY Biometric Enrollment',
					frm.doc.name
				);
				if (r) {
					frm.add_custom_button(
						__('View Enrollment Record'),
						() => openEnrollmentDoctype(frm.doc.name),
						__('Biometrics')
					);
					frm.add_custom_button(
						__('Unlock PIN / Reset Lockout'),
						() => openAdminReset(frm),
						__('Biometrics')
					);
				}
			} catch (_) {
				// `db.exists` is robust but guard anyway
			}
		},
	});
})();
