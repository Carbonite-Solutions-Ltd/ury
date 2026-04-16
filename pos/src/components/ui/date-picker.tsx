import { useEffect, useRef, useState } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';
import { DayPicker } from 'react-day-picker';
import { format, parseISO, isValid } from 'date-fns';
import { cn } from '../../lib/utils';

import 'react-day-picker/dist/style.css';

/**
 * Branded single-date picker for the Reports page. Built on
 * react-day-picker for the calendar grid + Tailwind for styling.
 *
 * Pill trigger button + inline popover calendar (no radix dep) with
 * click-outside + Escape close. Dates are exchanged with the parent
 * as ISO "yyyy-MM-dd" strings so the Reports endpoints don't have
 * to change. For from/to ranges the Reports page uses two of these
 * side by side (cleaner UX than the unified range picker we tried
 * first — picking the second date in range mode kept feeling clunky).
 */

// ---------------------------------------------------------------
// Shared popover wrapper
// ---------------------------------------------------------------

interface PopoverWrapProps {
  open: boolean;
  onClose: () => void;
  trigger: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

function PopoverWrap({
  open,
  onClose,
  trigger,
  children,
  className,
}: PopoverWrapProps) {
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    // Defer one tick so the click that opened the popover doesn't
    // immediately close it.
    const t = setTimeout(() => {
      document.addEventListener('mousedown', onDown);
      document.addEventListener('keydown', onKey);
    }, 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  return (
    <div ref={wrapRef} className="relative inline-block">
      {trigger}
      {open && (
        <div
          className={cn(
            'absolute right-0 mt-2 z-50 bg-white rounded-xl shadow-lg border border-gray-200 p-3',
            className
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// Shared calendar CSS — injected once to override react-day-picker
// defaults with a flat, shadcn-flavored look.
// ---------------------------------------------------------------

const PICKER_CLASS_NAMES = {
  root: 'ury-rdp',
  month_caption:
    'flex justify-center items-center text-sm font-semibold text-gray-800 py-1 mb-2',
  caption_label: 'text-sm font-semibold',
  nav: 'flex items-center gap-1',
  button_previous:
    'h-7 w-7 rounded-md inline-flex items-center justify-center hover:bg-gray-100 disabled:opacity-30 transition-colors',
  button_next:
    'h-7 w-7 rounded-md inline-flex items-center justify-center hover:bg-gray-100 disabled:opacity-30 transition-colors',
  table: 'w-full border-collapse',
  weekdays: 'flex',
  weekday:
    'w-8 h-8 text-[11px] font-medium text-gray-400 uppercase flex items-center justify-center',
  week: 'flex w-full',
  day: 'w-8 h-8 text-center text-sm p-0',
  day_button:
    'w-8 h-8 rounded-md inline-flex items-center justify-center hover:bg-blue-50 hover:text-blue-700 transition-colors text-gray-700',
  today: 'font-semibold text-blue-600',
  outside: 'text-gray-300',
  disabled: 'text-gray-300 cursor-not-allowed hover:bg-transparent',
  selected:
    '[&>button]:bg-blue-600 [&>button]:text-white [&>button]:hover:bg-blue-700',
  range_start:
    '[&>button]:bg-blue-600 [&>button]:text-white [&>button]:rounded-r-none',
  range_middle:
    '[&>button]:bg-blue-50 [&>button]:text-blue-700 [&>button]:rounded-none [&>button]:hover:bg-blue-100',
  range_end:
    '[&>button]:bg-blue-600 [&>button]:text-white [&>button]:rounded-l-none',
};

// ---------------------------------------------------------------
// DatePicker (single date)
// ---------------------------------------------------------------

interface DatePickerProps {
  value: string; // ISO yyyy-MM-dd
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

const parseIsoLoose = (iso?: string): Date | undefined => {
  if (!iso) return undefined;
  const d = parseISO(iso);
  return isValid(d) ? d : undefined;
};

const toIso = (d: Date): string => format(d, 'yyyy-MM-dd');

// Build a react-day-picker `disabled` matcher from loose min/max
// bounds. Returns undefined when both are missing so we pass through
// "nothing disabled" instead of `{ before: undefined, after: undefined }`
// which the matcher engine doesn't interpret the way we want.
const buildDisabledMatcher = (min?: Date, max?: Date) => {
  if (!min && !max) return undefined;
  const m: { before?: Date; after?: Date } = {};
  if (min) m.before = min;
  if (max) m.after = max;
  return m as any;
};

export function DatePicker({
  value,
  onChange,
  min,
  max,
  disabled,
  placeholder = 'Pick a date',
  className,
}: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const selected = parseIsoLoose(value);
  const minDate = parseIsoLoose(min);
  const maxDate = parseIsoLoose(max);

  const display = selected
    ? format(selected, 'MMM d, yyyy')
    : placeholder;

  return (
    <PopoverWrap
      open={open}
      onClose={() => setOpen(false)}
      trigger={
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            'flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200 text-sm text-gray-800 cursor-pointer hover:bg-gray-100 hover:border-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
            open && 'bg-white border-blue-400 ring-2 ring-blue-100',
            className
          )}
        >
          <CalendarIcon className="w-4 h-4 text-gray-500" />
          <span className={cn(!selected && 'text-gray-400')}>{display}</span>
        </button>
      }
    >
      <DayPicker
        mode="single"
        selected={selected}
        defaultMonth={selected}
        onSelect={(day) => {
          if (day) {
            onChange(toIso(day));
            setOpen(false);
          }
        }}
        disabled={buildDisabledMatcher(minDate, maxDate)}
        classNames={PICKER_CLASS_NAMES}
        showOutsideDays
      />
    </PopoverWrap>
  );
}
