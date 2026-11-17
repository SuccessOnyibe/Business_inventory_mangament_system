"""Reconciliation helpers: extracted workflows; URLs and transactions are unchanged."""


def reconciliation_stale(record, totals):
    return totals['unclassified_count'] > 0 or any(record[key] != totals[key] for key in
        ('sales_count', 'last_sale_id', 'expected_cash', 'expected_pos', 'gross_cash', 'gross_pos',
         'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
         'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id'))


def discrepancy_action_state(action):
    return {'investigate': 'investigating', 'resolve': 'resolved', 'reopen': 'open'}[action]
