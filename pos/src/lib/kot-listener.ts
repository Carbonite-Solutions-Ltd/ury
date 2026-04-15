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
    } = result.message as {
      kot_name?: string;
      pos_profile?: string;
      kot_printed?: number;
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
    // rendered each print job's HTML. We just iterate and send.
    if (print_jobs && print_jobs.length > 0) {
      for (const job of print_jobs) {
        try {
          console.log(
            `🖨️ Printing ${job.department} KOT ${kot_name} to ${job.printer}`,
          );
          await printKotWithQz(job.printer, job.html);
          console.log(`✅ ${job.department} KOT printed to ${job.printer}`);
        } catch (error) {
          console.error(
            `❌ Failed to print ${job.department} KOT to ${job.printer}:`,
            error,
          );
        }
      }
      // Mark the KOT as printed ONCE after all print jobs, not per job.
      await markKotAsPrinted(kot_name);
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

        // Print with QZ to specific printer
        await printKotWithQz(printerName, html);

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

export function stopKotListener() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
    console.log('🛑 KOT polling listener stopped');
  }
}