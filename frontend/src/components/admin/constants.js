// Mirrors schemas.PartnerType on the server.
export const PARTNER_TYPES = [
  'SCA', 'PSB', 'RRB', 'NBFC-MFI', 'Cooperative Bank', 'Cooperative Society', 'Small Finance Bank', 'Other/SIDBI',
];

export const ROUTING_STATUSES = ['eligible', 'no_data', 'deprioritized', 'excluded'];

export const APPLICATION_STATUSES = [
  'routed', 'acknowledged_by_partner', 'handed_off_to_pmsuraj', 'sanctioned', 'disbursed', 'rejected',
];

// Mirrors NEXT_STATUS in routers/applications.py; "rejected" is allowed from any open status.
export const NEXT_STATUS = {
  routed: 'acknowledged_by_partner',
  acknowledged_by_partner: 'handed_off_to_pmsuraj',
  handed_off_to_pmsuraj: 'sanctioned',
  sanctioned: 'disbursed',
};
