from decimal import Decimal
from trytond.model import Check, Index, ModelSQL, ModelView, Unique, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.exceptions import UserError
from datetime import date
from trytond.i18n import gettext
from trytond.transaction import Transaction
from sql.conditionals import Coalesce

INFINITY_CHAR = '\u221E'  # Unicode character for infinity (∞)


# TODO: Add helps
class REGE(ModelView, ModelSQL):
    'AEAT REGE (Special Regime for Groups of Entities)'
    __name__ = 'aeat.rege'

    name = fields.Char('Name',
        help='Unique name for this Group of Entities.', required=True)
    periods = fields.One2Many('aeat.rege.period', 'rege', 'Periods',
        help=('Periods defining the start and end dates '
            'during which this REGE is active.'),
        order=[('start_date', 'DESC NULLS FIRST')], required=True)
    members = fields.One2Many('aeat.rege.member', 'rege', 'Members',
        help='Parties enrolled as members.',
        order=[('exit_date', 'DESC NULLS FIRST'), ('party', 'ASC')])
    active_members = fields.Function(
        fields.Integer('Active Members',
            help='Number of parties currently registered.'),
        'get_active_members')
    type = fields.Function(
        fields.Selection([
            ('normal', 'Normal'),
            ('advanced', 'Advanced'),
            ], 'Type',
            help='Current taxation method (based on the active period).'),
        'on_change_with_type')
    is_active = fields.Function(
        fields.Boolean('Is Active?'),
        'get_is_active')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()

        cls._sql_constraints.append(('unique_rege_name',
            Unique(table, table.name),
            'aeat_rege.msg_unique_rege_name'))

    def get_rec_name(self, name):
        return f'{self.name}'

    def get_active_members(self, name):
        return sum(1 for m in self.members if m.current_member)

    def get_is_active(self, name):
        return any(period.state == 'open' for period in self.periods)

    @fields.depends('periods')
    def on_change_with_type(self, name=None):
        if not self.periods:
            return
        for period in self.periods:
            if period.state == 'open':
                return period.type
        return 'normal'


# BUG: When I create a period with 01/08 - 31/08, it pop-ups an error
class REGEPeriod(ModelView, ModelSQL):
    'AEAT REGE Period'
    __name__ = 'aeat.rege.period'

    rege = fields.Many2One('aeat.rege', 'REGE',
        help='The REGE to which this period belongs.',
        required=True, ondelete='CASCADE')
    type = fields.Selection([
        ('normal', 'Normal'),
        ('advanced', 'Advanced'),
        ], 'Type', help='Taxation regime applied during this period.',
        required=True)
    start_date = fields.Date('Starting Date',
        help='Lower bound of the period; leave empty for no start limit.',
        domain=[If(
            (Eval('start_date') & Eval('end_date')),
            ('start_date', '<=', Eval('end_date')),
            (),
        )])
    end_date = fields.Date('Ending Date',
        help='Upper bound of the period; leave empty for no end limit.',
        domain=[If(
            (Eval('start_date') & Eval('end_date')),
            ('end_date', '>=', Eval('start_date')),
            (),
        )])
    state = fields.Function(
        fields.Selection([
            ('open', 'Open'),
            ('closed', 'Closed'),
            ('scheduled', 'Scheduled'),
            ], 'State',
            help=("Indicates whether today's date falls within "
                "this period's start and end dates, does not or will do it.")),
        'on_change_with_state')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls.__access__.add('rege')
        cls._order.insert(0, ('start_date', 'DESC NULLS FIRST'))
        cls._sql_indexes.add(
            Index(
                table,
                (table.start_date, Index.Range()),
                (table.end_date, Index.Range())))
        cls._sql_constraints.append(('date_interval',
            Check(table, table.start_date <= table.end_date),
            'aeat_rege.msg_date_interval_period'))

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls.check_date_intervals(records)

    @classmethod
    def check_date_intervals(cls, periods):
        cls.lock()
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
                    ((start <= period_start) & (end >= period_start)) |
                    ((start <= period_end) & (end >= period_end)) |
                    ((start >= period_start) & (end <= period_end)) &
                    (table.id != period.id) &
                    (table.rege == period.rege.id)
                )))
            overlaps = [row[0] for row in cursor.fetchall()]
            if overlaps:
                raise UserError(gettext('aeat_rege.msg_period_overlap',
                    main=period.rec_name,
                    period=', '.join(f'"{cls(x).rec_name}"' for x in overlaps)))

    def get_rec_name(self, name):
        start_date = self.start_date or INFINITY_CHAR
        end_date = self.end_date or INFINITY_CHAR
        return f'{start_date} - {end_date} ({self.type})'

    @fields.depends('start_date', 'end_date')
    def on_change_with_state(self, name=None):
        pool = Pool()
        Date = pool.get('ir.date')
        User = pool.get('res.user')

        transaction = Transaction()
        user = User(transaction.user)

        timezone = None
        if user.employee and user.employee.party:
            timezone = user.employee.party.timezone

        today = Date.today(timezone=timezone)
        start_date = self.start_date or date.min
        end_date = self.end_date or date.max

        if start_date <= today <= end_date:
            return 'open'
        elif start_date > today:
            return 'scheduled'
        return 'closed'

# TODO: Do not allow to delete a membership. Only deactivate it¿?
class REGEMember(ModelView, ModelSQL):
    'Party membership on AEAT REGE'
    __name__ = 'aeat.rege.member'

    rege = fields.Many2One('aeat.rege', 'REGE',
        help='The AEAT REGE in which the party enrolls.',
        required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', 'Party',
        help='The entity or person enrolling in this REGE.',
        required=True, ondelete='CASCADE')
    registration_date = fields.Date('Registration Date',
        help="Date when the party's membership in this REGE begins.",
        required=True)
    exit_date = fields.Date('Exit Date',
        help="Date when the party's membership ends; leave empty if still active.",
        domain=[If(
            (Eval('registration_date') & Eval('exit_date')),
            ('exit_date', '>=', Eval('registration_date')),
            (),
        )])
    current_member = fields.Function(
        fields.Boolean('Current Member',
            help="Indicates whether the party's membership in this REGE is currently active."),
        'on_change_with_current_member', searcher='search_current_member')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._order.insert(0, ('exit_date', 'DESC NULLS FIRST'))
        cls._order.insert(1, ('party', 'ASC'))
        cls._sql_constraints.append(('date_interval',
            Check(table, table.registration_date <= table.exit_date),
            'aeat_rege.msg_date_interval_registration'))

    @staticmethod
    def default_registration_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls.check_duplicate_membership(records)

    @classmethod
    def check_duplicate_membership(cls, records):
        for record in records:
            members = cls.search([
                ('id', '!=', record.id),
                ('party', '=', record.party.id),
                ('rege', '=', record.rege.id),
            ])
            for member in members:
                if record.current_member and member.current_member:
                    raise UserError(gettext('aeat_rege.msg_active_membership',
                        party=record.party.rec_name, rege=record.rege.rec_name))

    # TODO: If exit_date is 01/01 and today is 01/01, it should return True or False?
    @fields.depends('exit_date')
    def on_change_with_current_member(self, name=None):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        return not (self.exit_date and self.exit_date <= today)

    @classmethod
    def search_current_member(cls, name, clause):
        table = cls.__table__()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        operand = table.exit_date <= table.registration_date
        query = table.select(table.id, where=(Operator(operand, value)))
        return [('id', 'in', query)]


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    reges = fields.One2Many('aeat.rege.member', 'party', 'REGE Memberships')
    shares_rege = fields.Function(
        fields.Boolean('Shares REGE with current Company',
            help=('Indicates if this party and the current company '
                'share membership in the same AEAT REGE.')),
        'on_change_with_shares_rege')

    @fields.depends('reges')
    def on_change_with_shares_rege(self, name=None):
        pool = Pool()
        Company = pool.get('company.company')

        transaction = Transaction()
        context = transaction.context

        if 'company' not in context:
            return False
        company = Company(context['company'])
        if not (company.party and company.party.reges):
            return False

        company_reges = {
            member.rege.id
            for member in company.party.reges
            if member.rege and member.current_member}
        party_reges = {
            member.rege.id
            for member in self.reges
            if member.rege and member.current_member}

        return len(company_reges.difference(party_reges)) != len(company_reges)


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    cost_price = fields.Numeric('Cost Price', digits='currency',
        states={
            'invisible': ~Bool(Eval('cost_price_show')),
            'required': Bool(Eval('cost_price_show')),
            })
    cost_price_show = fields.Function(
        fields.Boolean('Show Cost Price?'),
        'on_change_with_cost_price_show')

    @property
    def taxable_lines(self):
        taxable_lines = super().taxable_lines
        if getattr(self, 'cost_price_show', False):
            taxable_lines[0][1] -= getattr(self, 'cost_price')
        return taxable_lines

    @fields.depends('cost_price')
    def on_change_cost_price(self):
        if not self.cost_price:
            self.cost_price = Decimal(0)

    @fields.depends('product', '_parent_product.cost_price')
    def on_change_with_cost_price(self):
        if self.product and self.product.cost_price:
            return self.product.cost_price

    @fields.depends('invoice', '_parent_invoice.type',
        '_parent_invoice.company', 'party', '_parent_party.reges')
    def on_change_with_cost_price_show(self, name=None):
        if not (self.invoice and self.invoice.type == 'out'):
            return False

        company_reges = {
            member.rege.id
            for member in self.invoice.company.party.reges
            if member.rege and member.current_member}
        if not company_reges or not self.party.reges:
            return False

        for member in self.party.reges:
            if member.current_member and member.rege.id in company_reges:
                return True
        return False
