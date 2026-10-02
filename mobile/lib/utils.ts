/**
 * Formats a number as money, e.g. formatCurrency(5900) -> "$5,900.00".
 * Always two decimal places, US formatting, USD unless another ISO 4217
 * currency code is passed. Intl.NumberFormat throws a RangeError for an
 * invalid currency code, so that falls back to a plain "$" amount.
 */
export function formatCurrency(value: number, currency: string = 'USD'): string {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `$${value.toFixed(2)}`;
  }
}

/** Fantasy points with one decimal: 21.09 -> "21.1"; missing -> "-". */
export function formatPoints(value: number | null | undefined): string {
  return value == null ? '-' : value.toFixed(1);
}

/** A signed number: 3 -> "+3.0", -2.5 -> "-2.5", 0 -> "0.0". */
export function formatSigned(value: number | null | undefined, decimals = 1): string {
  if (value == null) return '-';
  const text = value.toFixed(decimals);
  return value > 0 ? `+${text}` : text;
}

/** A betting line: 0 -> "PK", 3.5 -> "+3.5", -3.5 -> "-3.5". */
export function formatLine(value: number): string {
  return value === 0 ? 'PK' : `${value > 0 ? '+' : ''}${value}`;
}

/** "SUN_MORNING" -> "Sun Morning". */
export function formatDayPart(dayPart: string): string {
  return dayPart
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

/** An ISO timestamp in Eastern time, e.g. "Sun, 10/4, 1:00 PM ET". */
export function formatEt(iso: string | null): string {
  if (!iso) return '-';
  return (
    new Date(iso).toLocaleString('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }) + ' ET'
  );
}

/** Money with a sign for profit/loss: 12.5 -> "+$12.50", -3 -> "-$3.00". */
export function formatSignedCurrency(value: number, currency: string = 'USD'): string {
  if (value === 0) return formatCurrency(0, currency);
  return `${value > 0 ? '+' : '-'}${formatCurrency(Math.abs(value), currency)}`;
}

/** A 0-1 ratio as a percent: 0.4567 -> "45.7%"; missing -> "-". */
export function formatPercent(value: number | null | undefined, decimals = 1): string {
  return value == null ? '-' : `${(value * 100).toFixed(decimals)}%`;
}
