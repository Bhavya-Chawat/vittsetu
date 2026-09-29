/** Server timestamps are UTC without a zone suffix — parse them as UTC, show local time. */
export function parseServerDate(iso) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

/** lang: the UI language code ('en' | 'hi'); Indian locale conventions either way. */
export function formatDateTime(iso, lang = 'en') {
  return parseServerDate(iso).toLocaleString(lang === 'hi' ? 'hi-IN' : 'en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}
