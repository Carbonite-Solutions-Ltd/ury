// Dev-server proxy for the KDS.
//
// `../../../sites/common_site_config.json` only exists when this app is
// checked out INSIDE a bench (frappe-bench/apps/ury/URYMosaic → ../../../
// lands on frappe-bench/sites). It does not exist in a bare clone or on a
// CI runner.
//
// This must NOT be a hard `require` at module top level. Vite loads this
// file whenever it loads vite.config.js — including for `vite build`,
// where `server.proxy` is never even used — so a missing dev-only config
// was failing PRODUCTION builds outside a bench with:
//
//   ✘ [ERROR] Could not resolve "../../../sites/common_site_config.json"
//     failed to load config from .../URYMosaic/vite.config.js
//
// Fall back to Frappe's default webserver port instead. Inside a bench the
// real value is still read, so `yarn dev` behaviour is unchanged.
const FRAPPE_DEFAULT_WEBSERVER_PORT = 8000;

let webserver_port = FRAPPE_DEFAULT_WEBSERVER_PORT;
try {
	const common_site_config = require('../../../sites/common_site_config.json');
	webserver_port = common_site_config.webserver_port || FRAPPE_DEFAULT_WEBSERVER_PORT;
} catch {
	// Not inside a bench (bare clone / CI runner). Only affects `yarn dev`,
	// which needs a running Frappe anyway — `vite build` never uses this.
}

export default {
	'^/(app|api|assets|files)': {
		target: `http://localhost:${webserver_port}`,
		ws: true,
		router: function (req) {
			const site_name = req.headers.host.split(':')[0];
			return `http://${site_name}:${webserver_port}`;
		}
	}
};
