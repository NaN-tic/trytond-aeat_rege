from trytond.model import Check, Index, ModelSQL, ModelView, Unique, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.exceptions import UserError
from datetime import date
from trytond.i18n import gettext
from trytond.transaction import Transaction
from sql.conditionals import Coalesce

INFINITY_CHAR = '\u221E'  # Unicode character for infinity (∞)


class REGE(ModelView, ModelSQL):
    'AEAT REGE (Special Regime for Groups of Entities)'
    __name__ = 'aeat.rege'

    name = fields.Char('Name',
        help='A unique name identifying the group of entities.', required=True)
    periods = fields.One2Many('aeat.rege.period', 'rege', 'Periods',
        help='The date intervals during which the REGE was active.',
        required=True)
    members = fields.One2Many('aeat.rege.member', 'rege', 'Members',
        help='History of party memberships.')
    active_member_count = fields.Function(
        fields.Integer('Active Members',
            help='Total number of parties currently registered.'),
        'get_active_member_count')
    current_type = fields.Function(
        fields.Selection([
            ('normal', 'Normal'),
            ('advanced', 'Advanced'),
            ], 'Current Type',
            help='Tax regime of the currently open period.',
            states={ 'invisible': ~Bool(Eval('is_active')) }),
        'on_change_with_current_type')
    is_active = fields.Function(
        fields.Boolean('Active Today?'),
        'on_change_with_is_active')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()

        cls._sql_constraints.append(('unique_rege_name',
            Unique(table, table.name),
            'aeat_rege.msg_unique_rege_name'))

    def get_active_member_count(self, name):
        return sum(1 for m in self.members if m.is_active) or None

    @fields.depends('periods')
    def on_change_with_current_type(self, name=None):
        for period in self.periods:
            if period.state == 'open':
                return period.type

    @fields.depends('periods')
    def on_change_with_is_active(self, name=None):
        return any(period.state == 'open' for period in self.periods)

    def get_period_by_date(self, target_date=None):
        pool = Pool()
        Date = pool.get('ir.date')

        if not target_date:
            target_date = Date.today()

        for period in self.periods:
            if period.contains_date(target_date):
                return period


class REGEPeriod(ModelView, ModelSQL):
    'AEAT REGE Period'
    __name__ = 'aeat.rege.period'

    rege = fields.Many2One('aeat.rege', 'REGE',
        help='REGE to which this period belongs.',
        required=True, ondelete='CASCADE')
    type = fields.Selection([
        ('normal', 'Normal'),
        ('advanced', 'Advanced'),
        ], 'Type', help='Tax regime applied during the period.',
        required=True)
    start_date = fields.Date('Starting Date',
        help='Start date of the period; leave empty for no lower limit.',
        domain=[If(
            (Eval('start_date') & Eval('end_date')),
            ('start_date', '<', Eval('end_date')),
            (),
        )])
    end_date = fields.Date('Ending Date',
        help='End date of the period; leave empty for no upper limit.',
        domain=[If(
            (Eval('start_date') & Eval('end_date')),
            ('end_date', '>', Eval('start_date')),
            (),
        )])
    state = fields.Function(
        fields.Selection([
            ('open', 'Open'),
            ('closed', 'Closed'),
            ('scheduled', 'Scheduled'),
            ], 'Current State',
            help=('Indicates if today is within this period, '
                'after it or before it.')),
        'on_change_with_state')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls.__access__.add('rege')
        cls._order = [('start_date', 'DESC NULLS FIRST'),
            ('end_date', 'DESC NULLS FIRST')] + cls._order
        cls._sql_indexes.add(
            Index(
                table,
                (table.start_date, Index.Range()),
                (table.end_date, Index.Range())))
        cls._sql_constraints.append(('date_interval',
            Check(table, table.start_date < table.end_date),
            'aeat_rege.msg_date_interval_period'))

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls.check_date_intervals(records)

    def get_rec_name(self, name):
        start_date = str(self.start_date or INFINITY_CHAR).replace('-', '/')
        end_date = str(self.end_date or INFINITY_CHAR).replace('-', '/')
        type = (self.type or '').capitalize()
        return f'{start_date} - {end_date} ({type})'

    @fields.depends('start_date', 'end_date')
    def on_change_with_state(self, name=None):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        if self.contains_date(today):
            return 'open'
        elif (self.start_date or date.min) > today:
            return 'scheduled'
        return 'closed'

    @classmethod
    def check_date_intervals(cls, periods):
        table = cls.__table__()
        transaction = Transaction()
        cursor = transaction.connection.cursor()

        for period in periods:
            start = Coalesce(table.start_date, date.min)
            end = Coalesce(table.end_date, date.max)
            period_start = Coalesce(period.start_date, date.min)
            period_end = Coalesce(period.end_date, date.max)

            cursor.execute(*table.select(table.id,
                where=(
                    (table.id != period.id) &
                    (table.rege == period.rege.id) &
                    (((start <= period_start) & (end >= period_start)) |
                    ((start <= period_end) & (end >= period_end)) |
                    ((start >= period_start) & (end <= period_end)))
                )))
            overlaps = [row[0] for row in cursor.fetchall()]
            if overlaps:
                overlaps = [f'\n- "{cls(x).rec_name}"' for x in overlaps]
                overlaps[-1] += '\n'
                raise UserError(gettext('aeat_rege.msg_period_overlap',
                    main=period.rec_name,
                    period=''.join(overlaps)))

    def contains_date(self, target_date):
        start_date = self.start_date or date.min
        end_date = self.end_date or date.max
        return start_date <= target_date <= end_date


class REGEMember(ModelView, ModelSQL):
    'Party membership on AEAT REGE'
    __name__ = 'aeat.rege.member'

    rege = fields.Many2One('aeat.rege', 'REGE',
        help='REGE to which the party is registered.',
        required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', 'Party',
        help='The entity or person registered.',
        required=True, ondelete='CASCADE')
    registration_date = fields.Date('Registration Date',
        help='Date on which membership begins.',
        required=True)
    exit_date = fields.Date('Exit Date',
        help='Date on which membership ends; leave empty if still active.',
        domain=[If(
            (Eval('registration_date') & Eval('exit_date')),
            ('exit_date', '>', Eval('registration_date')),
            (),
        )])
    is_active = fields.Function(
        fields.Boolean('Active Today?',
            help='Indicates if the membership is active today.'),
        'on_change_with_is_active', searcher='search_is_active')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls.__access__.add('rege')
        cls._order = [
            ('exit_date', 'DESC NULLS FIRST'), ('party', 'ASC')] + cls._order
        cls._sql_indexes.add(
            Index(
                table,
                (table.registration_date, Index.Range()),
                (table.exit_date, Index.Range())))
        cls._sql_constraints.append(('date_interval',
            Check(table, table.exit_date > table.registration_date),
            'aeat_rege.msg_date_interval_registration'))

    @staticmethod
    def default_registration_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls.check_date_intervals(records)

    @classmethod
    def check_date_intervals(cls, records):
        table = cls.__table__()
        transaction = Transaction()
        cursor = transaction.connection.cursor()

        for record in records:
            start = table.registration_date
            end = Coalesce(table.exit_date, date.max)
            record_start = record.registration_date
            record_end = Coalesce(record.exit_date, date.max)

            cursor.execute(*table.select(table.id,
                where=(
                    (table.id != record.id) &
                    (table.party == record.party.id) &
                    (((start <= record_start) & (end >= record_start)) |
                    ((start <= record_end) & (end >= record_end)) |
                    ((start >= record_start) & (end <= record_end)))
                )))
            overlaps = [row[0] for row in cursor.fetchall()]
            if overlaps:
                overlaps = [f'\n- "{cls(x).rec_name}"' for x in overlaps]
                overlaps[-1] += '\n'
                raise UserError(gettext('aeat_rege.msg_membership_overlap',
                    main=record.rec_name,
                    member=''.join(overlaps)))

    @fields.depends('registration_date', 'exit_date')
    def on_change_with_is_active(self, name=None):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        exit_date = self.exit_date or date.max
        if self.registration_date <= today <= exit_date:
            return True
        return False

    @classmethod
    def search_is_active(cls, name, clause):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        table = cls.__table__()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        exit_date = Coalesce(table.exit_date, date.max)
        operand = table.registration_date <= today <= exit_date
        query = table.select(table.id, where=(Operator(operand, value)))
        return [('id', 'in', query)]

    @classmethod
    def get_by_date(cls, party, target_date=None):
        pool = Pool()
        Date = pool.get('ir.date')

        if not target_date:
            target_date = Date.today()

        memberships = cls.search([
            ('party', '=', party.id),
            ('registration_date', '<=', target_date),
            ['OR',
                ('exit_date', '=', None),
                ('exit_date', '>=', target_date)
            ]])
        if not memberships:
            return
        return memberships[0]


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    rege_memberships = fields.One2Many(
        'aeat.rege.member', 'party', 'REGE Memberships')

    def get_rege_by_date(self, target_date=None):
        pool = Pool()
        REGEMember = pool.get('aeat.rege.member')

        membership = REGEMember.get_by_date(self, target_date)
        if membership:
            return membership.rege


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    cost_price = fields.Numeric('Cost Price', digits='currency',
        help=('Available only if the "Company" and "Party" '
            'share the same REGE of type "Advanced"; used for '
            'tax calculations and defaults to the product\'s cost price.'),
        states={
            'required': Bool(Eval('cost_price_show')),
            'invisible': ~Bool(Eval('cost_price_show')),
            'readonly': Eval('invoice_state') != 'draft',
            })
    cost_price_show = fields.Function(
        fields.Boolean('Display Cost Price?'),
        'on_change_with_cost_price_show')

    @property
    def taxable_lines(self):
        taxable_lines = super().taxable_lines

        cost_price = getattr(self, 'cost_price', None) or 0
        cost_price_show = getattr(self, 'cost_price_show', False)

        if cost_price_show:
            line = list(taxable_lines[0])
            line[1] -= cost_price
            taxable_lines[0] = tuple(line)
        return taxable_lines

    @fields.depends('product', '_parent_product.cost_price')
    def on_change_with_cost_price(self):
        if self.product:
            return self.product.cost_price

    @fields.depends('company', 'cost_price', 'invoice', 'invoice_party',
        'invoice_state', 'invoice_type', 'type',
        '_parent_invoice.accounting_date', '_parent_invoice.create_date',
        '_parent_invoice.invoice_date')
    def on_change_with_cost_price_show(self, name=None):
        if not (self.type == 'line' and self.invoice_type == 'out'
                and self.invoice):
            return False

        if not (self.company and self.invoice_party):
            return False

        target_date = (self.invoice.accounting_date or self.invoice.invoice_date
            or self.invoice.create_date.date())

        party_rege = self.invoice_party.get_rege_by_date(target_date)
        company_rege = self.company.party.get_rege_by_date(target_date)
        if not party_rege or not company_rege or party_rege != company_rege:
            return False

        period = party_rege.get_period_by_date(target_date)
        if not (period and period.type == 'advanced'):
            return False

        if self.invoice_state != 'draft':
            return self.cost_price > 0
        else:
            return True
