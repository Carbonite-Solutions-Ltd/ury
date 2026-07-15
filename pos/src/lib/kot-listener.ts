import { printKotWithQz } from './print-qz';

let pollingInterval: NodeJS.Timeout | null = null;
let lastCheckedKot: string | null = null;

export function setupKotListener() {
  if (typeof window === 'undefined') return;

  console.log('✅ KOT polling listener initialized');

  // Poll every 3 seconds for new KOTs
  pollingInterval = setInterval(async () => {
    try {
      await checkForNewKots();
    } catch (error) {
      console.error('Error checking for KOTs:', error);
    }
  }, 3000);
}

async function checkForNewKots() {
  try {
    // Get the latest KOT
    const response = await fetch('/api/method/ury.ury_pos.api.get_latest_kot');
    const result = await response.json();

    if (!result?.message) return;

    const {
      kot_name,
      pos_profile: _pos_profile,
      printers,
      print_jobs,
      kot_printed,
      production_unit_mode,
      qz_host,
    } = result.message as {
      kot_name?: string;
      pos_profile?: string;
      kot_printed?: number;
      // QZ websocket host for this profile. Empty/absent ⇒ localhost.
      // A remote value routes KOTs to the LAN print-server gateway so
      // tablets (which can't run QZ) still reach a printer (2026-07-14).
      qz_host?: string;
      // Set to 1 when the POS Profile's KDS routing mode is
      // "URY Production Unit". In that case each print_job's
      // `department` field is the production name (not Food/Drinks/
      // Other) and the whole KOT is stamped as printed after all
      // rows fire, not per-department.
      production_unit_mode?: number;
      // Legacy shape — whole-KOT prints to a list of printers.
      printers?: Array<{ printer: string; custom_kot_print_format?: string }>;
      // New shape (2026-04-16 print revamp) — per-department print
      // jobs with pre-rendered filtered HTML.
      print_jobs?: Array<{
        printer: string;
        department: string;
        html: string;
      }>;
    };

    // Skip if already printed or if we've already processed this KOT
    if (!kot_name || kot_printed || kot_name === lastCheckedKot) return;

    console.log('🔔 New KOT detected:', kot_name);
    lastCheckedKot = kot_name;

    // ---- New unified config path ----
    // Backend already filtered the items per department and
    // rendered each print job's HTML. We iterate and send, then
    // stamp the result according to the routing mode:
    //   - Menu Course mode (default): stamp each successfully-
    //     printed department via mark_kot_departments_printed so
    //     the pending-KOT tracker knows what made it to paper.
    //     kot_printed auto-flips to 1 when EVERY department has
    //     been stamped — held Drinks keeps the KOT visible in the
    //     pending-KOT sidebar until bill-print fires it.
    //   - URY Production Unit mode: the `department` field on each
    //     print_job is actually the production name, not a course
    //     department. There's no partial-fire tracking in PU mode
    //     (every KOT fires fully at order time through its
    //     production's printers), so we just stamp the whole KOT
    //     as printed via the old mark_kot_printed endpoint.
    if (print_jobs && print_jobs.length > 0) {
      const isPuMode = production_unit_mode === 1;
      const printedDepts: string[] = [];
      let anyPrinted = false;
      for (const job of print_jobs) {
        try {
          console.log(
            `🖨️ Printing ${isPuMode ? 'PU ' : ''}${job.department} KOT ${kot_name} to ${job.printer}`,
          );
          await printKotWithQz(job.printer, job.html, qz_host);
          console.log(
            `✅ ${job.department} KOT printed to ${job.printer}`,
          );
          anyPrinted = true;
          if (!isPuMode) {
            printedDepts.push(job.department);
          }
        } catch (error) {
          console.error(
            `❌ Failed to print ${job.department} KOT to ${job.printer}:`,
            error,
          );
        }
      }
      if (isPuMode) {
        if (anyPrinted) {
          await markKotAsPrinted(kot_name);
        }
      } else if (printedDepts.length > 0) {
        await markKotDepartmentsPrinted(kot_name, printedDepts);
      }
      return;
    }

    // ---- Legacy path ----
    if (!printers || printers.length === 0) {
      console.error('No printers configured for KOT');
      return;
    }

    for (const printerSetting of printers) {
      const printerName = printerSetting.printer;
      const printFormat = printerSetting.custom_kot_print_format || 'KOT Print';

      try {
        console.log(`🖨️ Printing KOT ${kot_name} to ${printerName}`);

        // Fetch KOT HTML (legacy path renders the full KOT per printer)
        const html = await getKotPrintHtml(kot_name, printFormat);

        // Print with QZ to specific printer (via the profile's qz_host
        // gateway when set, else localhost).
        await printKotWithQz(printerName, html, qz_host);

        console.log(`✅ KOT printed to ${printerName}`);

        // Mark as printed
        await markKotAsPrinted(kot_name);
      } catch (error) {
        console.error(`❌ Failed to print KOT to ${printerName}:`, error);
      }
    }
  } catch (error) {
    // Silently fail if no KOTs found
  }
}

async function getKotPrintHtml(kotName: string, printFormat: string): Promise<string> {
  const params = new URLSearchParams({
    doc: 'URY KOT',
    name: kotName,
    print_format: printFormat,
    _lang: 'en',
    no_letterhead: '1',
    letterhead: 'No Letterhead',
    settings: '{}'
  });

  const response = await fetch(`/api/method/frappe.www.printview.get_html_and_style?${params}`);
  const result = await response.json();
  
  if (!result?.message?.html) {
    throw new Error('Failed to fetch KOT HTML');
  }

  return `
    <html>
      <head>
        <style>${result.message.style || ''}</style>
      </head>
      <body>${result.message.html}</body>
    </html>
  `;
}

async function markKotAsPrinted(kotName: string): Promise<void> {
  try {
    // Use GET request which doesn't require CSRF
    const response = await fetch(`/api/method/ury.ury_pos.api.mark_kot_printed?kot_name=${encodeURIComponent(kotName)}`);

    if (!response.ok) {
      console.error('Failed to mark KOT as printed:', response.status);
    } else {
      console.log('✅ KOT marked as printed in database');
    }
  } catch (error) {
    console.error('Error marking KOT as printed:', error);
  }
}

/**
 * Stamp a list of departments as successfully printed for a given
 * KOT. The backend merges the list into
 * ``URY KOT.custom_printed_departments`` (JSON) and flips
 * ``kot_printed = 1`` when every department in the KOT's items has
 * been stamped. Called after each batch of QZ print jobs so the
 * pending-KOT tracker stays accurate.
 */
async function markKotDepartmentsPrinted(
  kotName: string,
  departments: string[],
): Promise<void> {
  try {
    const csrfToken =
      (window as any).csrf_token ||
      (window as any).frappe?.csrf_token ||
      '';
    const formData = new FormData();
    formData.append('kot_name', kotName);
    formData.append('departments', JSON.stringify(departments));
    const response = await fetch(
      '/api/method/ury.ury.api.ury_print.mark_kot_departments_printed',
      {
        method: 'POST',
        headers: csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {},
        body: formData,
      },
    );
    if (!response.ok) {
      console.error(
        'Failed to stamp KOT departments as printed:',
        response.status,
      );
    } else {
      const result = await response.json();
      console.log(
        `✅ KOT ${kotName} stamped with ${departments.join(', ')} (kot_printed=${result?.message?.kot_printed ?? '?'})`,
      );
    }
  } catch (error) {
    console.error('Error stamping KOT departments as printed:', error);
  }
}

/**
 * Fire any held / un-printed KOT departments for an invoice through
 * QZ Tray, then return the list of department names that actually
 * printed so the caller can react (e.g. show a toast). Called by the
 * Orders page's Print Invoice button BEFORE the bill prints — this
 * is how held Drinks KOTs finally reach the bar when the cashier
 * closes out.
 *
 * Returns an array of {kotName, department} pairs for everything that
 * made it to paper. Failures are logged but don't throw — a broken
 * bar printer shouldn't block the bill print.
 */
export async function firePendingKotsForInvoice(
  invoice: string,
): Promise<Array<{ kotName: string; department: string }>> {
  const fired: Array<{ kotName: string; department: string }> = [];
  if (!invoice) return fired;

  try {
    const response = await fetch(
      `/api/method/ury.ury_pos.api.print_pending_kots_for_invoice?invoice=${encodeURIComponent(invoice)}`,
    );
    if (!response.ok) {
      console.error(
        `Failed to fetch pending KOTs for ${invoice}:`,
        response.status,
      );
      return fired;
    }
    const result = await response.json();
    // In URY Production Unit mode the `department` field is the production
    // name, not a course department — there's no partial-fire tracking, so
    // we mark the WHOLE KOT printed after firing (not per-department).
    const isPuMode = result?.message?.production_unit_mode === 1;
    // QZ gateway host for this profile (empty ⇒ localhost). Routes held
    // KOTs to the same print-server the bill uses (2026-07-14).
    const qzHost = result?.message?.qz_host as string | undefined;
    const print_jobs = result?.message?.print_jobs as
      | Array<{
          printer: string;
          department: string;
          html: string;
          kot_name: string;
        }>
      | undefined;

    if (!print_jobs || print_jobs.length === 0) {
      console.log(`ℹ️ No pending KOTs to fire for invoice ${invoice}`);
      return fired;
    }

    // Group successful prints by kot_name so we can stamp each KOT
    // with the subset of departments that actually reached a printer.
    const stampsByKot: Record<string, string[]> = {};

    for (const job of print_jobs) {
      try {
        console.log(
          `🖨️ Firing pending ${job.department} KOT ${job.kot_name} to ${job.printer} (invoice ${invoice})`,
        );
        await printKotWithQz(job.printer, job.html, qzHost);
        console.log(
          `✅ Pending ${job.department} KOT printed to ${job.printer}`,
        );
        fired.push({ kotName: job.kot_name, department: job.department });
        stampsByKot[job.kot_name] = stampsByKot[job.kot_name] || [];
        stampsByKot[job.kot_name].push(job.department);
      } catch (error) {
        console.error(
          `❌ Failed to fire pending ${job.department} KOT to ${job.printer}:`,
          error,
        );
      }
    }

    for (const [kotName, depts] of Object.entries(stampsByKot)) {
      if (isPuMode) {
        await markKotAsPrinted(kotName);
      } else {
        await markKotDepartmentsPrinted(kotName, depts);
      }
    }
  } catch (error) {
    console.error('Error firing pending KOTs:', error);
  }
  return fired;
}

export function stopKotListener() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
    console.log('🛑 KOT polling listener stopped');
  }
}