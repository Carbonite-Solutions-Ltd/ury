import { useEffect, useRef, useState } from 'react';
import { Calendar as CalendarIcon, X, ArrowRight } from 'lucide-react';
import { DayPicker, type DateRange } from 'react-day-picker';
import { format, parseISO, isValid } from 'date-fns';
import { cn } from '../../lib/utils';

import 'react-day-picker/dist/style.css';

/**
 * Branded date pickers that replace the native `<input type="date">`
 * on the Reports page. Built on react-day-picker for the calendar
 * grid + Tailwind for styling.
 *
 * Two exports:
 *   - <DatePicker>       — single date, pill button + popover calendar
 *   - <DateRangePicker>  — from/to range in a single calendar
 *
 * Both use a local popover (no radix dependency) with click-outside
 * to close + Escape key handler. Dates are exchanged with the
 * parent as ISO "yyyy-MM-dd" strings so the Reports endpoints don't
 * have to change.
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

// ---------------------------------------------------------------
// DateRangePicker (from / to)
// ---------------------------------------------------------------

interface DateRangePickerProps {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  className?: string;
}

export function DateRangePicker({
  from,
  to,
  onChange,
  min,
  max,
  disabled,
  className,
}: DateRangePickerProps) {
  const [open, setOpen] = useState(false);

  const fromDate = parseIsoLoose(from);
  const toDate = parseIsoLoose(to);
  const minDate = parseIsoLoose(min);
  const maxDate = parseIsoLoose(max);

  // Local draft so we can let the user pick the second date before
  // committing. Sync to props when they change.
  const [draft, setDraft] = useState<DateRange | undefined>({
    from: fromDate,
    to: toDate,
  });

  useEffect(() => {
    setDraft({ from: fromDate, to: toDate });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  const display = () => {
    if (fromDate && toDate) {
      if (toIso(fromDate) === toIso(toDate)) {
        return format(fromDate, 'MMM d, yyyy');
      }
      return `${format(fromDate, 'MMM d')} → ${format(toDate, 'MMM d, yyyy')}`;
    }
    return 'Pick a range';
  };

  const handleSelect = (range: DateRange | undefined) => {
    setDraft(range);
    if (range?.from && range?.to) {
      onChange(toIso(range.from), toIso(range.to));
      // Small delay so the user sees the range highlight before the
      // popover closes.
      setTimeout(() => setOpen(false), 120);
    }
  };

  const clearRange = (e: React.MouseEvent) => {
    e.stopPropagation();
    const today = toIso(new Date());
    const aWeekAgo = new Date();
    aWeekAgo.setDate(aWeekAgo.getDate() - 6);
    onChange(toIso(aWeekAgo), today);
  };

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
          <span>{display()}</span>
          {fromDate && toDate && (
            <span
              role="button"
              aria-label="Reset range to last 7 days"
              title="Reset to last 7 days"
              onClick={clearRange}
              className="ml-1 p-0.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-700 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </span>
          )}
        </button>
      }
      className="min-w-[320px]"
    >
      <div className="flex items-center gap-2 px-2 pb-2 text-xs text-gray-500 border-b border-gray-100 mb-2">
        <span className="font-medium text-gray-700">
          {draft?.from ? format(draft.from, 'MMM d') : '—'}
        </span>
        <ArrowRight className="w-3 h-3" />
        <span className="font-medium text-gray-700">
          {draft?.to ? format(draft.to, 'MMM d') : '—'}
        </span>
      </div>
      <DayPicker
        mode="range"
        selected={draft}
        defaultMonth={draft?.from || fromDate}
        onSelect={handleSelect}
        disabled={buildDisabledMatcher(minDate, maxDate)}
        classNames={PICKER_CLASS_NAMES}
        showOutsideDays
        numberOfMonths={1}
      />
      <div className="flex justify-between gap-2 px-2 pt-2 border-t border-gray-100 mt-2">
        <RangePreset
          label="Today"
          onClick={() => {
            const t = toIso(new Date());
            onChange(t, t);
            setOpen(false);
          }}
        />
        <RangePreset
          label="7d"
          onClick={() => {
            const now = new Date();
            const earlier = new Date();
            earlier.setDate(now.getDate() - 6);
            onChange(toIso(earlier), toIso(now));
            setOpen(false);
          }}
        />
        <RangePreset
          label="30d"
          onClick={() => {
            const now = new Date();
            const earlier = new Date();
            earlier.setDate(now.getDate() - 29);
            onChange(toIso(earlier), toIso(now));
            setOpen(false);
          }}
        />
        <RangePreset
          label="MTD"
          onClick={() => {
            const now = new Date();
            const earlier = new Date(now.getFullYear(), now.getMonth(), 1);
            onChange(toIso(earlier), toIso(now));
            setOpen(false);
          }}
        />
      </div>
    </PopoverWrap>
  );
}

function RangePreset({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs font-medium text-gray-600 hover:text-blue-700 hover:bg-blue-50 px-2 py-1 rounded transition-colors"
    >
      {label}
    </button>
  );
}
