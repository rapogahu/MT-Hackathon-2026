const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseIsoDate(value: string): Date {
  if (!ISO_DATE.test(value)) throw new Error(`Некорректная ISO-дата: ${value}`);
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new Error(`Некорректная календарная дата: ${value}`);
  }
  return date;
}

export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDays(value: string, days: number): string {
  const date = parseIsoDate(value);
  date.setUTCDate(date.getUTCDate() + days);
  return toIsoDate(date);
}

export function enumerateDates(from: string, to: string): string[] {
  if (from > to) return [];
  const dates: string[] = [];
  for (let value = from; value <= to; value = addDays(value, 1)) dates.push(value);
  return dates;
}

export function monthBounds(month: string): { from: string; to: string } {
  if (!/^\d{4}-\d{2}$/.test(month)) throw new Error(`Некорректный месяц: ${month}`);
  const [year, monthNumber] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, monthNumber, 0, 12));
  return { from: `${month}-01`, to: toIsoDate(last) };
}

export function clampRange(
  from: string,
  to: string,
  minimum: string,
  maximum: string,
): { from: string; to: string } {
  return { from: from < minimum ? minimum : from, to: to > maximum ? maximum : to };
}

export function daysInclusive(from: string, to: string): number {
  return enumerateDates(from, to).length;
}
