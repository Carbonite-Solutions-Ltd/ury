/**
 * iHotel integration helpers.
 *
 * The React POS uses these to:
 *   - Find which rooms a selected customer is currently checked into
 *     (driven off the Guest → iHotel Profile link chain)
 *   - Validate a room selection right before the cashier starts an order
 *   - Charge a finished draft invoice to a guest's room (writes a
 *     Folio Charge on the matching iHotel Profile and stamps the
 *     POS Invoice as a "charged draft")
 *
 * See CLAUDE.md "Fixes log" 2026-04-12 for the full iHotel feature
 * postmortem (why charged drafts stay docstatus=0 forever, how the
 * Payment dialog picks up the intent, etc).
 */
import { call } from './frappe-sdk';

export interface GuestRoomOption {
  profile: string;
  room: string;
  guest: string;
  guest_name: string;
  check_in_date: string | null;
  check_out_date: string | null;
}

export interface RoomValidation {
  profile: string;
  guest: string;
  guest_name: string;
  room_rate: number;
}

export interface ChargeToRoomResult {
  invoice: string;
  ihotel_profile: string;
  folio_charge_row: string | null;
  amount: number;
}

/**
 * Return the list of rooms a customer is currently checked into.
 * Resolves via `Customer` → `Guest.customer` → `iHotel Profile.guest`
 * where `iHotel Profile.status = 'Open'`. Empty list means no
 * current stays — the cashier should either ask for a different
 * customer, ask the guest to check in first, or take the order as
 * a normal cash/card sale.
 */
export async function getGuestRoomsForCustomer(
  customer: string
): Promise<GuestRoomOption[]> {
  if (!customer) return [];
  const res = await call.get<{ message: GuestRoomOption[] }>(
    'ury.ury_pos.api.get_guest_rooms_for_customer',
    { customer }
  );
  return res.message || [];
}

/**
 * Double-check that (customer, room) maps to a single Open profile
 * before the cashier starts an order. Throws a clear ValidationError
 * when the room has no open stay or the guest on that room is linked
 * to a different customer.
 */
export async function validateHotelRoomForCustomer(
  customer: string,
  hotelRoom: string
): Promise<RoomValidation> {
  const res = await call.post<{ message: RoomValidation }>(
    'ury.ury_pos.api.validate_hotel_room_for_customer',
    { customer, hotel_room: hotelRoom }
  );
  return res.message;
}

/**
 * Charge a draft POS Invoice to a hotel guest's room. Writes a
 * Folio Charge row on the matching open iHotel Profile, marks the
 * invoice as "charged draft" (docstatus stays 0), and frees the
 * physical URY Table. The invoice shows up under the new "Room
 * Charges" status in the Orders page; iHotel's checkout flow will
 * post the actual GL entries when the guest settles their folio.
 */
export async function chargeInvoiceToRoom(
  invoice: string,
  hotelRoom: string
): Promise<ChargeToRoomResult> {
  const res = await call.post<{ message: ChargeToRoomResult }>(
    'ury.ury_pos.api.charge_invoice_to_room',
    { invoice, hotel_room: hotelRoom }
  );
  return res.message;
}
