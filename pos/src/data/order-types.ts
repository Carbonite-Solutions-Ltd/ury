import { Globe, Phone, ShoppingBag, Truck, Utensils } from "lucide-react";

export type OrderType = "Dine In" | "Take Away" | "Delivery" | "Phone In" | "Aggregators";

export type OrderTypes= {
    label: string;
    value: OrderType;
    icon: React.ElementType;
}

export const ORDER_TYPES: OrderTypes[] = [
    {
        label: "Dine In",
        value: "Dine In",
        icon: Utensils
    },
    {
        label: "Take Away",
        value: "Take Away",
        icon: ShoppingBag
    },
    {
        label: "Delivery",
        value: "Delivery",
        icon: Truck
    },
    {
        label: "Phone In",
        value: "Phone In",
        icon: Phone
    },
    {
        label: "Aggregators",
        value: "Aggregators",
        icon: Globe
    }
]

export const DINE_IN="Dine In"
export const DEFAULT_ORDER_TYPE="Take Away"
export const DEFAULT_PAYMENT_MODE="Cash"

export type OrderStatusType = "Draft" | "Unbilled" | "Recently Paid" | "Paid" | "Consolidated" | "Return" | "Room Charges" | "Pending KOTs" | "Incoming Transfers";

// Base status types that are always available.
// "Paid" was moved out of EXTENDED_ORDER_STATUS_TYPES on 2026-04-09
// per user request — cashiers need it unconditionally to see what
// they closed today, and gating it behind the POS Profile
// view_all_status flag was an unnecessary speed bump. Consolidated
// and Return stay in EXTENDED because they're admin-y.
//
// "Pending KOTs" (2026-04-16 print revamp Round 1) surfaces any
// invoice that still has at least one URY KOT with kot_printed=0 —
// a dedicated filter for the "did the bar miss this one?" glance.
// Paired with a live badge count in OrderStatusSidebar so cashiers
// see the state without having to click in.
export const BASE_ORDER_STATUS_TYPES = [
    {
        label: "Draft",
        value: "Draft"
    },
    {
        label: "Unbilled",
        value: "Unbilled"
    },
    {
        label: "Paid",
        value: "Paid"
    },
    {
        label: "Pending KOTs",
        value: "Pending KOTs"
    }
];

// Recently Paid status that appears when paid_limit > 0
export const RECENTLY_PAID_STATUS_TYPE = [
    {
        label: "Recently Paid",
        value: "Recently Paid"
    }
];

// Room Charges: draft POS Invoices flagged as charged-to-room via the
// iHotel integration. Only shown when `custom_ihotel_enabled` is on.
export const ROOM_CHARGES_STATUS_TYPE = [
    {
        label: "Room Charges",
        value: "Room Charges"
    }
];

// Incoming Transfers: drafts a captain has offered to this user at shift
// close, awaiting their approval. Shown when transfers are enabled on the
// POS Profile (custom_max_invoice_transfers > 0). 2026-06-05.
export const INCOMING_TRANSFERS_STATUS_TYPE = [
    {
        label: "Incoming Transfers",
        value: "Incoming Transfers"
    }
];

// Extended status types that are only available when view_all_status is enabled
export const EXTENDED_ORDER_STATUS_TYPES = [
    {
        label: "Consolidated",
        value: "Consolidated"
    },
    {
        label: "Return",
        value: "Return"
    }
];

// Function to get order status types based on POS profile settings
export const getOrderStatusTypes = (
    viewAllStatus?: number,
    paidLimit?: number,
    ihotelEnabled?: number,
    maxTransfers?: number
) => {
    let statusTypes = [...BASE_ORDER_STATUS_TYPES];

    // Add Recently Paid if paid_limit > 0
    if (paidLimit && paidLimit > 0) {
        statusTypes.push(...RECENTLY_PAID_STATUS_TYPE);
    }

    // Add Room Charges when iHotel is enabled on this POS Profile.
    if (ihotelEnabled === 1) {
        statusTypes.push(...ROOM_CHARGES_STATUS_TYPE);
    }

    // Add Incoming Transfers when transfers are enabled on this profile.
    if (maxTransfers && maxTransfers > 0) {
        statusTypes.push(...INCOMING_TRANSFERS_STATUS_TYPE);
    }

    // Add extended statuses if view_all_status is enabled
    if (viewAllStatus === 1) {
        statusTypes.push(...EXTENDED_ORDER_STATUS_TYPES);
    }

    return statusTypes;
};

// Legacy export for backward compatibility
export const ORDER_STATUS_TYPES = BASE_ORDER_STATUS_TYPES;