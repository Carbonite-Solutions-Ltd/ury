import frappe
from frappe.model.document import Document


class URYBiometricEnrollment(Document):
	def validate(self):
		if self.failed_pin_attempts and self.failed_pin_attempts < 0:
			self.failed_pin_attempts = 0

	def on_trash(self):
		frappe.logger().info(
			f"[URY Biometric] enrollment deleted for user={self.user} "
			f"by={frappe.session.user} at={frappe.utils.now()}"
		)
