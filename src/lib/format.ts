import type { Artist, Num, Offering } from './types';

export function toNum(value: Num | string): number | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'bigint') return Number(value);
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function fmtInt(value: Num): string {
  const number = toNum(value);
  return number === null ? '—' : new Intl.NumberFormat('en-US').format(number);
}

export function fmtCompact(value: Num): string {
  const number = toNum(value);
  if (number === null) return '—';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(number);
}

export function fmtUsd(value: Num): string {
  const number = toNum(value);
  if (number === null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: number < 10 ? 2 : 0,
    minimumFractionDigits: 0
  }).format(number);
}

export function fmtOriginal(amount: Num, currency: string | null | undefined): string {
  const number = toNum(amount);
  if (number === null) return '—';
  const code = (currency || 'USD').toUpperCase();
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: code,
      maximumFractionDigits: code === 'JPY' || code === 'KRW' ? 0 : 2,
      minimumFractionDigits: 0
    }).format(number);
  } catch {
    return `${code} ${fmtInt(number)}`;
  }
}

export function fmtDate(value: Num, fallback = '—'): string {
  const seconds = toNum(value);
  if (seconds === null) return fallback;
  return new Date(seconds * 1000).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

export function priceRange(artist: Artist): string {
  const min = toNum(artist.price_min_usd);
  const max = toNum(artist.price_max_usd);
  if (min === null && max === null) return '—';
  if (min !== null && max !== null && max - min > 0.5) {
    return `${fmtUsd(min)} – ${fmtUsd(max)}`;
  }
  return fmtUsd(min ?? max);
}

export function jpyRange(artist: Artist): string {
  const min = toNum(artist.price_min_jpy);
  const max = toNum(artist.price_max_jpy);
  if (min === null && max === null) return '';
  if (min !== null && max !== null && max !== min) {
    return `${fmtOriginal(min, 'JPY')} – ${fmtOriginal(max, 'JPY')}`;
  }
  return fmtOriginal(min ?? max, 'JPY');
}

export function offeringPrice(offering: Offering): string {
  const min = toNum(offering.price_min);
  const max = toNum(offering.price_max);
  const original = min === null && max === null
    ? '—'
    : min !== null && max !== null && min !== max
      ? `${fmtOriginal(min, offering.currency)} – ${fmtOriginal(max, offering.currency)}`
      : fmtOriginal(min ?? max, offering.currency);
  const usd = toNum(offering.price_min_usd) ?? toNum(offering.price_usd);
  return usd === null ? original : `${original} · ${fmtUsd(usd)}`;
}

export function siteLabel(site: string | null | undefined): string {
  if (!site) return 'Unknown';
  return site.toLowerCase() === 'skeb' ? 'Skeb' : site.toLowerCase() === 'crepe' ? 'CREPE' : site;
}

export function urlHost(url: string | null | undefined): string {
  if (!url) return '';
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}
