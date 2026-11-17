"""Reports: extracted workflows; URLs and transactions are unchanged."""

from datetime import date as BusinessDate, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from auth import require_stock_manager
from database import db_connection
from reconciliation_helpers import discrepancy_action_state, reconciliation_stale

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Reports'])


def financial_report_data(start_date, end_date, branch_id):
    lagos = ZoneInfo('Africa/Lagos')
    if end_date < start_date or (end_date - start_date).days >= 366 or end_date > datetime.now(lagos).date():
        raise HTTPException(status_code=422, detail='Choose a non-future date range of at most 366 days')
    start = datetime.combine(start_date, time.min, tzinfo=lagos)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=lagos)
    keys = ('id', 'reviewed_at', 'cash_difference', 'pos_difference', 'sales_count', 'last_sale_id',
        'expected_cash', 'expected_pos', 'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
        'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id')
    snapshot_select = ', '.join(f'latest.{key} AS snapshot_{key}' for key in keys)
    # One statement gives sales, refunds, counts and decisions one coherent database view.
    sql = f'''WITH bounds AS (SELECT %s::date first_day, %s::date last_day,
        %s::timestamptz start_at, %s::timestamptz end_at, %s::integer branch_filter),
    purchases AS (
        SELECT id, branch_id, total_amount, payment_method, created_at FROM sales WHERE order_id IS NULL
        UNION ALL SELECT (SELECT MAX(id) FROM sales WHERE order_id = o.id), branch_id,
            total_amount, payment_method, created_at FROM sale_orders o),
    gross AS (SELECT p.branch_id, (p.created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        COUNT(*) sales_count, MAX(id) last_sale_id,
        SUM(total_amount) FILTER (WHERE payment_method = 'cash') gross_cash,
        SUM(total_amount) FILTER (WHERE payment_method = 'pos') gross_pos,
        SUM(total_amount) FILTER (WHERE payment_method = 'credit') gross_credit,
        COUNT(*) FILTER (WHERE payment_method IS NULL) unclassified_count,
        SUM(total_amount) FILTER (WHERE payment_method IS NULL) unclassified_amount
        FROM purchases p CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1, 2),
    refunds AS (SELECT c.branch_id, (c.created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        COUNT(*) refund_count, MAX(id) last_correction_id,
        SUM(refund_total) FILTER (WHERE refund_method = 'cash') refund_cash,
        SUM(refund_total) FILTER (WHERE refund_method = 'pos') refund_pos, SUM(debt_reduction) debt_reduced
        FROM sale_corrections c CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1, 2),
    collections AS (SELECT branch_id, (created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        SUM(amount) FILTER (WHERE payment_method = 'cash') repaid_cash,
        SUM(amount) FILTER (WHERE payment_method = 'pos') repaid_pos, COUNT(*) repayment_count, MAX(id) last_repayment_id
        FROM credit_repayments CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1,2),
    drawer AS (SELECT m.branch_id, m.business_date, SUM(cash_in) cash_in, SUM(cash_out) cash_out,
        SUM(expected_cash_effect) cash_movement_effect, COUNT(*) movement_count, MAX(id) last_movement_id
        FROM cash_movements m CROSS JOIN bounds WHERE business_date BETWEEN first_day AND last_day GROUP BY 1,2),
    latest AS (SELECT DISTINCT ON (r.branch_id, r.business_date) r.* FROM daily_reconciliations r CROSS JOIN bounds
        WHERE business_date BETWEEN first_day AND last_day ORDER BY r.branch_id, r.business_date, revision DESC),
    decisions AS (SELECT DISTINCT ON (reconciliation_id) reconciliation_id, action, responsible_name
        FROM discrepancy_events ORDER BY reconciliation_id, id DESC),
    calendar AS (SELECT b.id branch_id, b.name branch_name, d::date business_date FROM branches b CROSS JOIN bounds
        CROSS JOIN LATERAL generate_series(first_day::timestamp, last_day::timestamp, INTERVAL '1 day') d
        WHERE branch_filter IS NULL OR b.id = branch_filter)
    SELECT calendar.*, COALESCE(gross.gross_credit,0) gross_credit, COALESCE(refunds.debt_reduced,0) debt_reduced,
        COALESCE(collections.repaid_cash,0) repaid_cash, COALESCE(collections.repaid_pos,0) repaid_pos,
        COALESCE(collections.repayment_count,0) repayment_count, collections.last_repayment_id,
        COALESCE(gross.sales_count, 0) sales_count, gross.last_sale_id,
        COALESCE(gross.gross_cash, 0) gross_cash, COALESCE(gross.gross_pos, 0) gross_pos,
        COALESCE(gross.unclassified_count, 0) unclassified_count, COALESCE(gross.unclassified_amount, 0) unclassified_amount,
        COALESCE(refunds.refund_cash, 0) refund_cash, COALESCE(refunds.refund_pos, 0) refund_pos,
        COALESCE(refunds.refund_count, 0) refund_count, refunds.last_correction_id,
        COALESCE(drawer.cash_in, 0) cash_in, COALESCE(drawer.cash_out, 0) cash_out,
        COALESCE(drawer.cash_movement_effect, 0) cash_movement_effect,
        COALESCE(drawer.movement_count, 0) movement_count, drawer.last_movement_id,
        {snapshot_select}, decisions.action last_action, decisions.responsible_name
    FROM calendar LEFT JOIN collections USING (branch_id, business_date) LEFT JOIN gross USING (branch_id, business_date)
    LEFT JOIN refunds USING (branch_id, business_date) LEFT JOIN drawer USING (branch_id, business_date)
    LEFT JOIN latest USING (branch_id, business_date)
    LEFT JOIN decisions ON decisions.reconciliation_id = latest.id
    ORDER BY calendar.business_date, calendar.branch_id LIMIT 5001;'''
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (start_date, end_date, start, end, branch_id))
            names = [column.name for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    if branch_id is not None and not rows:
        raise HTTPException(status_code=404, detail='Branch not found')
    if len(rows) > 5000:
        raise HTTPException(status_code=422, detail='Report is too large; choose fewer dates or one branch')
    return format_financial_report(rows, keys, start_date, end_date, branch_id, lagos)


def format_financial_report(rows, snapshot_keys, start_date, end_date, branch_id, lagos):
    result = []
    money_keys = ('gross_credit', 'debt_reduced', 'repaid_cash', 'repaid_pos', 'gross_cash', 'gross_pos', 'unclassified_amount', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect')
    compare_money = ('expected_cash', 'expected_pos', 'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect')
    for row in rows:
        current = {key: format(row[key], '.2f') for key in money_keys}
        current.update(sales_count=row['sales_count'], refund_count=row['refund_count'],
                       unclassified_count=row['unclassified_count'], last_sale_id=row['last_sale_id'],
                       last_correction_id=row['last_correction_id'],
                       movement_count=row['movement_count'], last_movement_id=row['last_movement_id'],
                       repayment_count=row['repayment_count'], last_repayment_id=row['last_repayment_id'],
                       expected_cash=format(row['gross_cash'] - row['refund_cash'] + row['cash_movement_effect'] + row['repaid_cash'], '.2f'),
                       expected_pos=format(row['gross_pos'] - row['refund_pos'] + row['repaid_pos'], '.2f'))
        snapshot = {key: row[f'snapshot_{key}'] for key in snapshot_keys}
        exists = snapshot['id'] is not None
        if exists:
            for key in compare_money:
                snapshot[key] = format(snapshot[key], '.2f')
        stale = exists and reconciliation_stale(snapshot, current)
        balanced = exists and snapshot['cash_difference'] == 0 and snapshot['pos_difference'] == 0
        resolution = ('out_of_date' if stale else discrepancy_action_state(row['last_action']) if row['last_action']
                      else 'balanced' if balanced else 'open' if exists else 'not_counted')
        active = bool(row['sales_count'] or row['refund_count'] or row['movement_count'] or row['repayment_count'] or exists)
        status = ('out_of_date' if stale else 'reviewed' if exists and snapshot['reviewed_at'] else 'submitted' if exists
                  else 'no_submission' if active else 'no_activity')
        result.append(dict(branch_id=row['branch_id'], branch_name=row['branch_name'], business_date=row['business_date'].isoformat(),
            **current, net_sales=format(row['gross_cash'] + row['gross_pos'] + row['unclassified_amount']
                + row['gross_credit'] - row['debt_reduced'] - row['refund_cash'] - row['refund_pos'], '.2f'), reconciliation_id=snapshot['id'],
            reconciliation_status=status, resolution_state=resolution, responsible_name=row['responsible_name'],
            cash_difference=format(snapshot['cash_difference'], '.2f') if exists else None,
            pos_difference=format(snapshot['pos_difference'], '.2f') if exists else None,
            unresolved=bool(exists and not balanced and resolution != 'resolved')))
    totals = {key: format(sum((Decimal(row[key]) for row in result), Decimal('0')), '.2f')
              for key in (*money_keys, 'expected_cash', 'expected_pos', 'net_sales')}
    totals.update(gross_sales=format(Decimal(totals['gross_cash']) + Decimal(totals['gross_pos'])
                                    + Decimal(totals['unclassified_amount']) + Decimal(totals['gross_credit']), '.2f'),
                  sales_count=sum(row['sales_count'] for row in result), refund_count=sum(row['refund_count'] for row in result),
                  unresolved_days=sum(row['unresolved'] for row in result),
                  unreconciled_days=sum(row['reconciliation_status'] in ('no_submission', 'out_of_date') for row in result),
                  awaiting_review_days=sum(row['reconciliation_status'] == 'submitted' for row in result))
    return dict(start_date=start_date.isoformat(), end_date=end_date.isoformat(), branch_id=branch_id,
                generated_at=datetime.now(lagos).isoformat(), timezone='Africa/Lagos', currency='NGN', totals=totals, rows=result)


@router.get('/reports/financial')
def financial_report(start_date: BusinessDate = Query(), end_date: BusinessDate = Query(),
                      branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                      user: dict = Depends(require_stock_manager)):
    return financial_report_data(start_date, end_date, branch_id)


@router.get('/reports/financial.csv')
def export_financial_report(start_date: BusinessDate = Query(), end_date: BusinessDate = Query(),
                             branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                             user: dict = Depends(require_stock_manager)):
    report = financial_report_data(start_date, end_date, branch_id)
    columns = ('gross_credit', 'debt_reduced', 'repaid_cash', 'repaid_pos', 'business_date', 'branch_id', 'branch_name', 'sales_count', 'gross_cash', 'gross_pos',
        'unclassified_count', 'unclassified_amount', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out',
        'cash_movement_effect', 'expected_cash', 'expected_pos', 'net_sales',
        'reconciliation_status', 'cash_difference', 'pos_difference', 'resolution_state', 'responsible_name')
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow((*columns, 'generated_at_lagos'))
    for row in report['rows']:
        values = []
        for key in columns:
            value = row[key] if row[key] is not None else ''
            # Escape formulas in text, preserving signed Decimal financial amounts.
            if key in ('branch_name', 'responsible_name') and str(value).lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + str(value)
            values.append(value)
        writer.writerow((*values, report['generated_at']))
    return Response('\ufeff' + buffer.getvalue(), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="FAS-financial-{start_date}-{end_date}.csv"', 'Cache-Control': 'no-store'})
