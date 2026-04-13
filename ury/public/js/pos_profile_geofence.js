// Desk-side helper for the POS Profile geofence fields.
//
// Adds a "Get Current Location" button next to the Company Latitude /
// Company Longitude fields. Clicking it asks the browser for the
// current GPS position and stamps both fields in one shot, so the
// admin doesn't have to look up coordinates manually.
//
// Wired via `doctype_js` in ury/hooks.py. See CLAUDE.md
// "Fixes log" 2026-04-10 for the geofence feature rollout.
frappe.ui.form.on("POS Profile", {
    refresh(frm) {
        if (!frm.fields_dict.custom_company_latitude) return;

        // Custom Button that lives in the Actions menu so it's visible
        // regardless of scroll position on the form. Label shows under
        // the Geofence section as well via a field-level description.
        frm.add_custom_button(
            __("Get Current Location"),
            () => capture_current_location(frm),
            __("Geofence")
        );
    },
});

function capture_current_location(frm) {
    if (!navigator.geolocation) {
        frappe.msgprint({
            title: __("Geolocation Unavailable"),
            message: __(
                "This browser does not support the Geolocation API. Enter coordinates manually."
            ),
            indicator: "red",
        });
        return;
    }

    frappe.show_alert({
        message: __("Requesting your current location…"),
        indicator: "blue",
    });

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = Number(pos.coords.latitude.toFixed(6));
            const lon = Number(pos.coords.longitude.toFixed(6));
            const accuracy = Math.round(pos.coords.accuracy || 0);

            frm.set_value("custom_company_latitude", lat);
            frm.set_value("custom_company_longitude", lon);
            if (!frm.doc.custom_geofence_enabled) {
                frm.set_value("custom_geofence_enabled", 1);
            }

            frappe.show_alert(
                {
                    message: __(
                        "Location captured: {0}, {1} (±{2} m). Don't forget to Save.",
                        [lat, lon, accuracy]
                    ),
                    indicator: "green",
                },
                6
            );
        },
        (err) => {
            let msg = __("Failed to get your location.");
            if (err.code === err.PERMISSION_DENIED) {
                msg = __(
                    "Location permission denied. Allow it in your browser settings and try again."
                );
            } else if (err.code === err.POSITION_UNAVAILABLE) {
                msg = __(
                    "Your device couldn't determine its location. Check GPS / Wi-Fi."
                );
            } else if (err.code === err.TIMEOUT) {
                msg = __("Timed out while trying to get your location.");
            }
            frappe.msgprint({
                title: __("Location Error"),
                message: msg,
                indicator: "red",
            });
        },
        {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0,
        }
    );
}
