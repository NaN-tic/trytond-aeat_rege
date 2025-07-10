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
        help='Unique name for this Group of Entities.', required=True)
    periods = fields.One2Many('aeat.rege.period', 'rege', 'Periods',
        help=('Periods defining the start and end dates '
            'during which this REGE is active.'),
        required=True)
    members = fields.One2Many('aeat.rege.member', 'rege', 'Members',
        help='Parties enrolled as members.')
    active_member_count = fields.Function(
        fields.Integer('Active Members',
            help='Number of parties currently registered.'),
        'get_active_member_count')
    current_type = fields.Function(
        fields.Selection([
            ('normal', 'Normal'),
            ('advanced', 'Advanced'),
            ], 'Current Type',
            help="Current taxation method (based on the 'open' period).",
            states={ 'invisible': ~Bool(Eval('is_active')) }),
        'on_change_with_current_type')
    is_active = fields.Function(
        fields.Boolean('Is Currently Active?'),
        'on_change_with_is_active')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()

        cls._sql_constraints.append(('unique_rege_name',
            Unique(table, table.name),
            'aeat_rege.msg_unique_rege_name'))

    def get_active_member_count(self, name):
        return sum(1 for m in self.members if m.active) or None

    @fields.depends('periods')
    def on_change_with_is_active(self, name=None):
        return any(period.state == 'open' for period in self.periods)

    @fields.depends('periods')
    def on_change_with_current_type(self, name=None):
        if not self.periods:
            return
        for period in self.periods:
            if period.state == 'open':
                return period.type
        return 'normal'

    @classmethod
    def search_is_active(cls, name, clause):
        table = cls.__table__()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        operand = table.periods.state == 'open'
        query = table.select(table.id, where=(Operator(operand, value)))
        return [('id', 'in', query)]

    def get_period_by_date(self, target_date):
        for period in self.periods:
            if period.contains_date(target_date):
                return period


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
            ('start_date', '<', Eval('end_date')),
            (),
        )])
    end_date = fields.Date('Ending Date',
        help='Upper bound of the period; leave empty for no end limit.',
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
            Check(table, table.start_date < table.end_date),
            'aeat_rege.msg_date_interval_period'))

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls.check_date_intervals(records)

    def get_rec_name(self, name):
        start_date = self.start_date or INFINITY_CHAR
        end_date = self.end_date or INFINITY_CHAR
        return f'{start_date} - {end_date} ({self.type})'

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
                    (table.id != period.id) &
                    (table.rege == period.rege.id) &
                    (((start <= period_start) & (end >= period_start)) |
                    ((start <= period_end) & (end >= period_end)) |
                    ((start >= period_start) & (end <= period_end)))
                )))
            overlaps = [row[0] for row in cursor.fetchall()]
            if overlaps:
                raise UserError(gettext('aeat_rege.msg_period_overlap',
                    main=period.rec_name,
                    period=', '.join(f'"{cls(x).rec_name}"' for x in overlaps)))

    def contains_date(self, target_date):
        start_date = self.start_date or date.min
        end_date = self.end_date or date.max
        return start_date <= target_date <= end_date

# TODO: Proponer realizar una herencia de 'ir.date' para que incluya el 'timezone' por defecto.
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
            ('exit_date', '>', Eval('registration_date')),
            (),
        )])
    active = fields.Function(
        fields.Boolean('Is Membership Active?',
            help="Indicates whether the party's membership in this REGE is currently active."),
        'on_change_with_active', searcher='search_active')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls.__access__.add('rege')
        cls._order = [
            ('exit_date', 'DESC NULLS FIRST'), ('party', 'ASC')] + cls._order
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
        cls.check_memberships(records)

    @classmethod
    def check_memberships(cls, records):
        for record in records:
            if not record.active:
                continue
            memberships = cls.search([
                ('id', '!=', record.id),
                ('party', '=', record.party.id),
            ])
            if memberships:
                raise UserError(gettext('aeat_rege.msg_active_membership',
                    party=record.party.rec_name, rege=record.rege.rec_name))

    @fields.depends('exit_date')
    def on_change_with_active(self, name=None):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        if not self.exit_date:
            return True
        if today <= self.exit_date:
            return True
        return False

    @classmethod
    def search_active(cls, name, clause):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        table = cls.__table__()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        operand = today <= Coalesce(table.exit_date, date.max)
        query = table.select(table.id, where=(Operator(operand, value)))
        return [('id', 'in', query)]


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    rege_memberships = fields.One2Many(
        'aeat.rege.member', 'party', 'REGE Memberships')
    shares_rege = fields.Function(
        fields.Boolean('Shares REGE with current Company',
            help=('Indicates if this party and the current company '
                'shares membership in the same AEAT REGE.')),
        'on_change_with_shares_rege')

    @fields.depends('rege_memberships')
    def on_change_with_shares_rege(self, name=None):
        pool = Pool()
        Company = pool.get('company.company')

        transaction = Transaction()
        context = transaction.context

        if 'company' not in context:
            return False
        company = Company(context['company'])
        if not (company.party and company.party.rege_memberships):
            return False

        company_reges = {
            member.rege.id
            for member in company.party.rege_memberships
            if member.rege and member.active}
        party_reges = {
            member.rege.id
            for member in self.rege_memberships
            if member.rege and member.active}

        return len(company_reges.difference(party_reges)) != len(company_reges)

    def get_rege(self):
        pool = Pool()
        Company = pool.get('company.company')

        transaction = Transaction()
        if 'company' not in transaction.context:
            return

        company = Company(transaction.context['company'])
        for member in company.party.rege_memberships:
            if member.active:
                company_rege = member.rege
                break
        else:
            return

        for member in self.rege_memberships:
            if member.active and member.rege.id == company_rege.id:
                return member.rege


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
            taxable_lines[0][1] -= getattr(self, 'cost_price') # TODO: Put 'on_change' and 'default' on 'cost_price'¿?
        return taxable_lines

    @fields.depends('product', '_parent_product.cost_price')
    def on_change_with_cost_price(self):
        if self.product and self.product.cost_price:
            return self.product.cost_price

    @fields.depends('type', 'invoice', '_parent_invoice.type',
        '_parent_invoice.company', '_parent_invoice.party',
        '_parent_invoice.invoice_date')
    def on_change_with_cost_price_show(self, name=None):
        if not (self.invoice and self.invoice.party and self.invoice.company
                and self.invoice.type == 'out' and self.type == 'line'):
            return False

        rege = self.invoice.party.get_rege()
        if rege != self.invoice.company.party.get_rege():
            return False

        target_date = self.invoice.invoice_date # TODO:
        if not target_date:
            return False

        period = rege.get_period_by_date(target_date)
        if not (period and period.type == 'advanced'):
            return False
        return True
