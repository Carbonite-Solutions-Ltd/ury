# Colocated controller for www/sw-min.js (the POS service worker).
#
# WHY THIS FILE EXISTS: Frappe won't serve a plain `.js` from www/ via the
# StaticPage renderer (`js` is in UNSUPPORTED_STATIC_PAGE_TYPES), but the
# TemplatePage renderer serves any file ending in `min.js` as RAW static
# source (no Jinja) — see frappe/website/page_renderers/template_page.py
# render_template(). So the built service worker is copied to
# `ury/www/sw-min.js` at build time and served at `/sw-min.js` with a
# `text/javascript` content-type (mimetypes.guess_type) — a root path
# whose scope covers /pos.
#
# `no_cache = 1` disables Frappe's 30-minute redis html cache for this
# route so a redeployed service worker is served immediately (a stale SW
# would delay update propagation). Same knob www/pos.py uses for the
# shell.
no_cache = 1
