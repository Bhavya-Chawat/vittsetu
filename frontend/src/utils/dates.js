/** Server timestamps are UTC without a zone suffix — parse them as UTC, show local time. */
export function parseServerDate(iso) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function formatDateTime(iso) {
  return parseServerDate(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}
