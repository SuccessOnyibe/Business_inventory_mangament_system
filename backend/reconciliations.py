"""Reconciliations: extracted workflows; URLs and transactions are unchanged."""

from datetime import date as BusinessDate, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import get_current_user, require_stock_manager, scoped_branch
from database import db_connection
from reconciliation_helpers import discrepancy_action_state, reconciliation_stale
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Reconciliations'])


class ReconciliationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    business_date: BusinessDate
    actual_cash: Decimal = Field(max_digits=24, decimal_places=2)
    actual_pos: Decimal = Field(max_digits=24, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)


class ReconciliationReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str | None = Field(default=None, max_length=2000)


class DiscrepancyEventCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['investigate', 'resolve', 'reopen']
    explanation: str = Field(min_length=1, max_length=2000)
    resolution_action: str | None = Field(default=None, max_length=2000)
    responsible_user_id: int = Field(strict=True, gt=0, le=2147483647)

    @model_validator(mode='after')
    def require_explanation(self):
        self.explanation = self.explanation.strip()
        if not self.explanation:
            raise ValueError('Explain the investigation or decision')
        if self.action == 'resolve':
            if not self.resolution_action or not self.resolution_action.strip():
                raise ValueError('Describe the resolution action taken')
            self.resolution_action = self.resolution_action.strip()
        elif self.resolution_action is not None:
            raise ValueError('Resolution action applies only to resolving a discrepancy')
        return self


RECONCILIATION_COLUMNS = ('id', 'branch_id', 'business_date', 'revision', 'expected_cash',
    'expected_pos', 'actual_cash', 'actual_pos', 'cash_difference', 'pos_difference',
    'sales_count', 'last_sale_id', 'notes', 'submitted_by', 'submitted_at',
    'reviewed_by', 'reviewed_at', 'review_notes', 'gross_cash', 'gross_pos',
    'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
    'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id')


RECONCILIATION_SELECT = ', '.join(RECONCILIATION_COLUMNS)


def reconciliation_response(row):
    result = dict(zip(RECONCILIATION_COLUMNS, row))
    for key in ('expected_cash', 'expected_pos', 'actual_cash', 'actual_pos', 'cash_difference', 'pos_difference',
                'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect'):
        result[key] = format(result[key], '.2f')
    for key in ('business_date', 'submitted_at', 'reviewed_at'):
        if result[key] is not None:
            result[key] = result[key].isoformat()
    result['status'] = 'reviewed' if result['reviewed_at'] else 'submitted'
    result['currency'] = 'NGN'
    return result


def daily_sales_totals(cursor, branch_id, business_date):
    lagos = ZoneInfo('Africa/Lagos')
    if business_date > datetime.now(lagos).date():
        raise HTTPException(status_code=422, detail='Cannot reconcile a future date')
    # A business day is midnight-to-midnight in Lagos, not the database server's zone.
    start = datetime.combine(business_date, time.min, tzinfo=lagos)
    end = start + timedelta(days=1)
    cursor.execute(
        '''WITH purchases AS (
               SELECT id, branch_id, total_amount, payment_method, created_at FROM sales WHERE order_id IS NULL
               UNION ALL
               SELECT (SELECT MAX(id) FROM sales WHERE order_id = o.id), branch_id,
                      total_amount, payment_method, created_at FROM sale_orders o
           ) SELECT COUNT(*), COALESCE(SUM(total_amount) FILTER (WHERE payment_method = 'cash'), 0),
                  COALESCE(SUM(total_amount) FILTER (WHERE payment_method = 'pos'), 0),
                  COUNT(*) FILTER (WHERE payment_method IS NULL),
                  COALESCE(SUM(total_amount) FILTER (WHERE payment_method IS NULL), 0), MAX(id)
           FROM purchases WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''',
        (branch_id, start, end)
    )
    row = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(refund_total) FILTER (WHERE refund_method = 'cash'), 0),
        COALESCE(SUM(refund_total) FILTER (WHERE refund_method = 'pos'), 0), COUNT(*), MAX(id)
        FROM sale_corrections WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''', (branch_id, start, end))
    refunds = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(cash_in), 0), COALESCE(SUM(cash_out), 0),
        COALESCE(SUM(expected_cash_effect), 0), COUNT(*), MAX(id) FROM cash_movements
        WHERE branch_id = %s AND business_date = %s;''', (branch_id, business_date))
    cash = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(amount) FILTER (WHERE payment_method = 'cash'),0),
        COALESCE(SUM(amount) FILTER (WHERE payment_method = 'pos'),0), COUNT(*), MAX(id)
        FROM credit_repayments WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''', (branch_id,start,end))
    repayments = cursor.fetchone()
    return dict(repaid_cash=format(repayments[0], '.2f'), repaid_pos=format(repayments[1], '.2f'),
                repayment_count=repayments[2], last_repayment_id=repayments[3], sales_count=row[0], expected_cash=format(row[1] - refunds[0] + cash[2] + repayments[0], '.2f'), expected_pos=format(row[2] - refunds[1] + repayments[1], '.2f'),
                gross_cash=format(row[1], '.2f'), gross_pos=format(row[2], '.2f'),
                refund_cash=format(refunds[0], '.2f'), refund_pos=format(refunds[1], '.2f'),
                refund_count=refunds[2], last_correction_id=refunds[3],
                cash_in=format(cash[0], '.2f'), cash_out=format(cash[1], '.2f'), cash_movement_effect=format(cash[2], '.2f'),
                movement_count=cash[3], last_movement_id=cash[4],
                unclassified_count=row[3], unclassified_amount=format(row[4], '.2f'), last_sale_id=row[5])


@router.get('/reconciliations/summary')
def reconciliation_summary(branch_id: int = Query(gt=0, le=2147483647),
                           business_date: BusinessDate = Query(),
                           user: dict = Depends(get_current_user)):
    scoped_branch(user, branch_id)
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                # Sales and submissions lock this same branch row, keeping the summary coherent.
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR SHARE;', (branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                totals = daily_sales_totals(cursor, branch_id, business_date)
                cursor.execute(f'''SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations
                    WHERE branch_id = %s AND business_date = %s ORDER BY revision DESC LIMIT 1;''',
                    (branch_id, business_date))
                row = cursor.fetchone()
                latest = reconciliation_response(row) if row else None
                if latest:
                    latest.update(discrepancy_state(cursor, latest))
    return {'branch_id': branch_id, 'business_date': business_date.isoformat(), **totals,
            'latest_submission': latest, 'is_stale': reconciliation_stale(latest, totals) if latest else False}


@router.post('/reconciliations', status_code=201)
def submit_reconciliation(submission: ReconciliationCreate, idempotency_key: UUID = Header(),
                          user: dict = Depends(get_current_user)):
    scoped_branch(user, submission.branch_id)
    payload = submission.model_dump(mode='json')
    for key in ('actual_cash', 'actual_pos'):
        payload[key] = format(getattr(submission, key), '.2f')
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'reconciliation', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (submission.branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                totals = daily_sales_totals(cursor, submission.branch_id, submission.business_date)
                if totals['unclassified_count']:
                    raise HTTPException(status_code=409, detail='Sales with unknown payment methods prevent reconciliation')
                cursor.execute('''SELECT COALESCE(MAX(revision), 0) + 1 FROM daily_reconciliations
                                  WHERE branch_id = %s AND business_date = %s;''',
                               (submission.branch_id, submission.business_date))
                revision = cursor.fetchone()[0]
                # Corrections append revisions. They never overwrite earlier counts or reviews.
                cursor.execute(f'''INSERT INTO daily_reconciliations
                    (branch_id, business_date, revision, expected_cash, expected_pos, actual_cash,
                     actual_pos, sales_count, last_sale_id, notes, submitted_by, gross_cash, gross_pos,
                     refund_cash, refund_pos, refund_count, last_correction_id,
                     cash_in, cash_out, cash_movement_effect, movement_count, last_movement_id, repayment_count, last_repayment_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {RECONCILIATION_SELECT};''',
                    (submission.branch_id, submission.business_date, revision, totals['expected_cash'],
                     totals['expected_pos'], submission.actual_cash, submission.actual_pos,
                     totals['sales_count'], totals['last_sale_id'], submission.notes, user['id'], totals['gross_cash'],
                     totals['gross_pos'], totals['refund_cash'], totals['refund_pos'], totals['refund_count'], totals['last_correction_id'],
                     totals['cash_in'], totals['cash_out'], totals['cash_movement_effect'], totals['movement_count'], totals['last_movement_id'], totals['repayment_count'], totals['last_repayment_id']))
                result = reconciliation_response(cursor.fetchone())
                finish_stock_request(cursor, idempotency_key, result)
    return result


@router.get('/reconciliations')
def list_reconciliations(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                        limit: int = Query(default=100, ge=1, le=500),
                        offset: int = Query(default=0, ge=0, le=2147483647),
                        user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {RECONCILIATION_SELECT},
            NOT EXISTS (SELECT 1 FROM daily_reconciliations newer WHERE newer.branch_id = r.branch_id
                AND newer.business_date = r.business_date AND newer.revision > r.revision)
            FROM daily_reconciliations r WHERE (%s::integer IS NULL OR branch_id = %s)
            ORDER BY id DESC LIMIT %s OFFSET %s;''', (branch_id, branch_id, limit, offset)).fetchall()
        result = [{**reconciliation_response(row), 'is_latest': row[-1]} for row in rows]
        with connection.cursor() as cursor:
            cursor.execute('''SELECT DISTINCT ON (reconciliation_id) reconciliation_id, action,
                responsible_user_id, responsible_name FROM discrepancy_events
                WHERE reconciliation_id = ANY(%s) ORDER BY reconciliation_id, id DESC;''', ([row['id'] for row in result],))
            events = {row[0]: row[1:] for row in cursor.fetchall()}
        for row in result:
            event = events.get(row['id'])
            row.update(resolution_state=discrepancy_action_state(event[0]) if event else
                'balanced' if Decimal(row['cash_difference']) == 0 and Decimal(row['pos_difference']) == 0 else 'open',
                responsible_user_id=event[1] if event else None, responsible_name=event[2] if event else None)
    return result


@router.post('/reconciliations/{reconciliation_id}/review')
def review_reconciliation(review: ReconciliationReview,
                          reconciliation_id: int = Path(gt=0, le=2147483647),
                          user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Reconciliation not found')
                # Lock order matches submissions/sales: branch first, then the record.
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (branch[0],))
                cursor.execute(f'SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations WHERE id = %s FOR UPDATE;',
                               (reconciliation_id,))
                record = reconciliation_response(cursor.fetchone())
                if record['status'] == 'reviewed':
                    return record  # A repeated review cannot replace the first reviewer or timestamp.
                cursor.execute('SELECT MAX(revision) FROM daily_reconciliations WHERE branch_id = %s AND business_date = %s;',
                               (record['branch_id'], record['business_date']))
                latest_revision = cursor.fetchone()[0]
                totals = daily_sales_totals(cursor, record['branch_id'], BusinessDate.fromisoformat(record['business_date']))
                if record['revision'] != latest_revision or reconciliation_stale(record, totals):
                    raise HTTPException(status_code=409, detail='Submission is out of date; submit updated counts before review')
                cursor.execute(f'''UPDATE daily_reconciliations SET reviewed_by = %s,
                    reviewed_at = clock_timestamp(), review_notes = %s WHERE id = %s
                    RETURNING {RECONCILIATION_SELECT};''', (user['id'], review.notes, reconciliation_id))
                result = reconciliation_response(cursor.fetchone())
    return result


def discrepancy_state(cursor, record):
    cursor.execute('''SELECT action, responsible_user_id, responsible_name FROM discrepancy_events
        WHERE reconciliation_id = %s ORDER BY id DESC LIMIT 1;''', (record['id'],))
    event = cursor.fetchone()
    balanced = Decimal(record['cash_difference']) == 0 and Decimal(record['pos_difference']) == 0
    return dict(resolution_state=discrepancy_action_state(event[0]) if event else 'balanced' if balanced else 'open',
                responsible_user_id=event[1] if event else None, responsible_name=event[2] if event else None)


EVENT_SELECT = '''e.id, e.reconciliation_id, e.action, e.explanation, e.resolution_action,
    e.responsible_user_id, e.responsible_name, e.created_by, e.created_by_name, e.created_at,
    r.branch_id, r.business_date'''


def event_response(row):
    result = dict(zip(('id', 'reconciliation_id', 'action', 'explanation', 'resolution_action',
        'responsible_user_id', 'responsible_name', 'created_by', 'created_by_name', 'created_at', 'branch_id', 'business_date'), row))
    result['created_at'] = result['created_at'].isoformat()
    result['business_date'] = result['business_date'].isoformat()
    result['resolution_state'] = discrepancy_action_state(result['action'])
    return result


@router.get('/reconciliations/{reconciliation_id}/assignees')
def discrepancy_assignees(reconciliation_id: int = Path(gt=0, le=2147483647), user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        branch = connection.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,)).fetchone()
        if branch is None:
            raise HTTPException(status_code=404, detail='Reconciliation not found')
        rows = connection.execute('''SELECT id, username, role FROM users WHERE is_active = TRUE
            AND (role <> 'salesperson' OR branch_id = %s) ORDER BY username;''', (branch[0],)).fetchall()
    return [dict(id=row[0], username=row[1], role=row[2]) for row in rows]


@router.post('/reconciliations/{reconciliation_id}/discrepancy-events', status_code=201)
def create_discrepancy_event(request: DiscrepancyEventCreate, reconciliation_id: int = Path(gt=0, le=2147483647),
                             idempotency_key: UUID = Header(), user: dict = Depends(require_stock_manager)):
    payload = {'reconciliation_id': reconciliation_id, **request.model_dump(mode='json')}
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'discrepancy_event', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Reconciliation not found')
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (branch[0],))
                cursor.execute(f'SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations WHERE id = %s FOR UPDATE;', (reconciliation_id,))
                record = reconciliation_response(cursor.fetchone())
                cursor.execute('SELECT MAX(revision) FROM daily_reconciliations WHERE branch_id = %s AND business_date = %s;',
                               (record['branch_id'], record['business_date']))
                if cursor.fetchone()[0] != record['revision'] or reconciliation_stale(record,
                        daily_sales_totals(cursor, branch[0], BusinessDate.fromisoformat(record['business_date']))):
                    raise HTTPException(status_code=409, detail='Count is superseded or out of date; submit current counts first')
                current = discrepancy_state(cursor, record)['resolution_state']
                if current == 'balanced':
                    raise HTTPException(status_code=409, detail='This count has no discrepancy')
                if (request.action == 'reopen') != (current == 'resolved'):
                    raise HTTPException(status_code=409, detail='Reopen a resolved discrepancy before adding another decision')
                if request.action == 'resolve' and record['reviewed_at'] is None:
                    raise HTTPException(status_code=409, detail='Review the count before resolving its discrepancy')
                cursor.execute('SELECT username, role, branch_id, is_active FROM users WHERE id = %s;', (request.responsible_user_id,))
                responsible = cursor.fetchone()
                if responsible is None:
                    raise HTTPException(status_code=404, detail='Responsible user not found')
                if not responsible[3] or (responsible[1] == 'salesperson' and responsible[2] != branch[0]):
                    raise HTTPException(status_code=422, detail='Assign an active member of this branch or a Manager/Admin')
                # This records a decision; no submitted amount, sale, or payment is altered.
                cursor.execute('''INSERT INTO discrepancy_events (reconciliation_id, action, explanation,
                    resolution_action, responsible_user_id, responsible_name, created_by, created_by_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, (SELECT username FROM users WHERE id = %s)) RETURNING id;''',
                    (reconciliation_id, request.action, request.explanation, request.resolution_action,
                     request.responsible_user_id, responsible[0], user['id'], user['id']))
                event_id = cursor.fetchone()[0]
                cursor.execute(f'''SELECT {EVENT_SELECT} FROM discrepancy_events e
                    JOIN daily_reconciliations r ON r.id = e.reconciliation_id WHERE e.id = %s;''', (event_id,))
                result = event_response(cursor.fetchone())
                finish_stock_request(cursor, idempotency_key, result)
    return result


@router.get('/discrepancy-events')
def list_discrepancy_events(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                            limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=2147483647),
                            user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {EVENT_SELECT} FROM discrepancy_events e
            JOIN daily_reconciliations r ON r.id = e.reconciliation_id
            WHERE (%s::integer IS NULL OR r.branch_id = %s) ORDER BY e.id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [event_response(row) for row in rows]
