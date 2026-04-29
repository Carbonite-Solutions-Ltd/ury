import frappe
from frappe.model.document import Document


class URYBiometricSettings(Document):
	def validate(self):
		if self.enabled and not self.issonline_ws_url:
			frappe.throw("ISSOnline WebSocket URL is required when Biometric Authentication is enabled.")
		for field, floor in (
			("match_threshold", 1),
			("min_template_bytes", 1),
			("max_template_bytes", 1),
			("pin_max_attempts", 1),
			("pin_lockout_minutes", 1),
			("biometric_login_max_attempts", 1),
			("template_lookup_max_attempts", 1),
			("biometric_login_rate_limit_seconds", 1),
			("template_lookup_rate_limit_seconds", 1),
		):
			if (self.get(field) or 0) < floor:
				frappe.throw(f"{field.replace('_', ' ').title()} must be at least {floor}.")
		if (self.min_template_bytes or 0) >= (self.max_template_bytes or 0):
			frappe.throw("Min Template Bytes must be less than Max Template Bytes.")
