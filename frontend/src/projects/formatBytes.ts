/** A project archive's size, at whatever magnitude it happens to be.
 *
 * Deliberately not StorageUsageBadge's formatGB: that one always says GB
 * because it is reading against a quota measured in GB, and a project
 * holding a couple of PySCF single points would render as "0.00 GB", which
 * reads as empty rather than as small. This picks the unit instead.
 *
 * Decimal units (1000^3), matching formatGB and the way the two quota
 * modules advertise their own caps, so the numbers in the two panels are
 * comparable rather than differing by 7% for no visible reason.
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}
