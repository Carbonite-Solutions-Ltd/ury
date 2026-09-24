# Copyright (c) 2026, URY and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url

from ury.ury.sync import rules


class URYSyncSettings(Document):
	"""Branch -> cloud sync configuration.

	Deliberately disabled by default. While `enabled` is off, `queue.enqueue`
	and both scheduled workers return immediately, so installing this app on
	an existing site changes nothing at all until somebody switches it on.
	"""

	def validate(self):
		self._validate_not_pointing_at_self()
		self._validate_timeout_below_stale_threshold()

	def _validate_not_pointing_at_self(self):
		"""Refuse to let a site push to itself.

		This is the single worst way to misconfigure sync: the cloud site is
		the one people already have open in the desk, so it is the one they
		are most likely to type the remote URL into. Pointing a site at
		itself would have it re-ingest its own sales forever.
		"""
		if not self.enabled or not self.remote_url:
			return

		def host(url):
			return (url or "").strip().rstrip("/").split("//")[-1].split("/")[0].lower()

		if host(self.remote_url) and host(self.remote_url) == host(get_url()):
			frappe.throw(
				_(
					"Remote Site URL points at this site ({0}). A site cannot sync "
					"to itself — enable this only on a BRANCH site, and set the "
					"remote to the cloud site it reports into."
				).format(host(get_url())),
				title=_("Remote Is This Site"),
			)

	def _validate_timeout_below_stale_threshold(self):
		"""A transport timeout at or above the sweeper's stale-claim window
		would let the sweeper reclaim a row that is still legitimately in
		flight, and the same sale would be pushed twice."""
		timeout = int(self.connection_timeout_seconds or 0)
		if timeout >= rules.STALE_SENDING_SECONDS:
			frappe.throw(
				_(
					"Connection Timeout ({0}s) must be well below the stale-claim "
					"threshold of {1}s, otherwise a push still in flight could be "
					"retried and the same sale sent twice."
				).format(timeout, rules.STALE_SENDING_SECONDS),
				title=_("Timeout Too Long"),
			)
