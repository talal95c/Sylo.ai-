function number(value: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

/** "85000.00", "EUR" -> "EUR 85,000"; token symbols go after the number: "85,000 tEURC". */
export function formatAmount(value: string | number, currency: string): string {
  const parsed = typeof value === "number" ? value : Number(value);
  const text = Number.isFinite(parsed) ? number(parsed) : String(value);
  return /^[A-Z]{3}$/.test(currency) ? `${currency} ${text}` : `${text} ${currency}`;
}

export function formatEur(value: number): string {
  return `€${number(value)}`;
}

/** 0xab12…cd34 */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "";
  return hash.length > 12 ? `${hash.slice(0, 6)}…${hash.slice(-4)}` : hash;
}

/** "Savanna Shea Exports Ltd" -> "Savanna Shea Exports" */
export function displayName(legalName: string): string {
  return legalName.replace(/\s+(SAS|SA|SARL|Ltd|Limited|GmbH|LLC|Inc\.?)$/i, "");
}

export function formatClock(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts.slice(11, 19);
  return date.toLocaleTimeString("en-GB", { hour12: false });
}
