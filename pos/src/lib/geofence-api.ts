/**
 * Geofence client. Thin wrapper around the browser Geolocation API +
 * the two backend endpoints that feature-gate and validate the user's
 * position at login time.
 *
 * The whole feature is opt-in on the POS Profile
 * (`custom_geofence_enabled`). When off, `getGeofenceConfig` returns
 * `{enabled: 0}` and the caller should skip the permission prompt
 * entirely — no annoying geolocation popup for sites that aren't
 * using the feature.
 *
 * See CLAUDE.md "Fixes log" 2026-04-10.
 */
import { call } from './frappe-sdk';

export interface GeofenceConfig {
  enabled: 0 | 1;
  radius_meters: number;
  source: 'user' | 'company' | null;
}

export interface GeofenceValidation {
  ok: 1;
  enabled?: 0 | 1;
  distance_meters?: number;
  radius_meters?: number;
  source?: 'user' | 'company' | null;
}

export async function getGeofenceConfig(
  terminal?: string | null
): Promise<GeofenceConfig> {
  const params: Record<string, string> = {};
  if (terminal) params.terminal = terminal;
  const res = await call.get<{ message: GeofenceConfig }>(
    'ury.ury_pos.api.get_geofence_config',
    params
  );
  return res.message;
}

export async function validateGeofence(
  latitude: number,
  longitude: number,
  terminal?: string | null
): Promise<GeofenceValidation> {
  const params: Record<string, any> = { latitude, longitude };
  if (terminal) params.terminal = terminal;
  const res = await call.post<{ message: GeofenceValidation }>(
    'ury.ury_pos.api.validate_geofence',
    params
  );
  return res.message;
}

/**
 * Ask the browser for the user's current position. Wraps
 * navigator.geolocation.getCurrentPosition in a Promise so callers can
 * await it. Rejects with a friendly Error when permission is denied,
 * the device can't get a fix, or the browser doesn't support the API.
 */
export function getBrowserPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      reject(new Error('Your browser does not support geolocation.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(pos),
      (err) => {
        // Translate the native error codes to something human-readable
        // so the blocking screen can tell the user what to do next.
        let msg = 'Failed to get your location.';
        switch (err.code) {
          case err.PERMISSION_DENIED:
            msg =
              'Location permission was denied. Enable it in your browser settings and reload.';
            break;
          case err.POSITION_UNAVAILABLE:
            msg =
              "Your device couldn't determine its location. Make sure GPS / Wi-Fi is on.";
            break;
          case err.TIMEOUT:
            msg = 'Timed out while trying to get your location. Try again.';
            break;
        }
        reject(new Error(msg));
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 30000, // accept a 30s-old fix — plenty for login
      }
    );
  });
}
