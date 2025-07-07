from decimal import Decimal
from trytond.model import Check, ModelSQL, ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.exceptions import UserError
from datetime import date
from trytond.i18n import gettext

MIN_DATE = date(year=1970, month=1, day=1)
MAX_DATE = date(year=2970, month=1, day=1)


# TODO: Add helps
class REGE(ModelView, ModelSQL):
    'AEAT REGE (Special Regime for Groups of Entities)'
    __name__ = 'aeat.rege'

    name = fields.Char('Name',
        required=True, translate=True)
    periods = fields.One2Many('aeat.rege.period', 'rege', 'Periods',
        required=True)
    members = fields.One2Many('aeat.rege.member', 'rege', 'Members')
    type = fields.Function(
        fields.Selection([
            (None, ''),
            ('normal', 'Normal'),
            ('advanced', 'Advanced'),
            ], 'Type'),
        'get_type')

    def get_type(self, name):
        if not self.periods:
            return None
        for period in self.periods:
            if period.state == 'open':
                return period.type
        return 'normal'


class REGEPeriod(ModelView, ModelSQL):
    'AEAT REGE Period'
    __name__ = 'aeat.rege.period'

    rege = fields.Many2One('aeat.rege', 'REGE',
        required=True, ondelete='CASCADE')
    type = fields.Selection([
        ('normal', 'Normal'),
        ('advanced', 'Advanced'),
        ], 'Type')
    start_date = fields.Date('Start Date')
    end_date = fields.Date('End Date')
    state = fields.Function(
        fields.Selection([
            ('open', 'Open'),
            ('closed', 'Closed'),
            ], 'State'),
        'get_state')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()

        cls._sql_constraints.append(('date_interval',
            Check(table, table.start_date <= table.end_date),
            'aeat_rege.msg_date_interval'))

    @staticmethod
    def default_type():
        return 'normal'

    @classmethod
    def validate(cls, records):
        super().validate(records)
        for record in records:
            periods = cls.search([ # FIXME: Try to use record.rege.periods (use timeit or something like that)
                ('id', '!=', record.id),
                ('rege', '=', record.rege.id),
            ])

            for period in periods:
                if record.state == 'open' and period.state == record.state:
                    raise UserError(gettext('aeat_rege.msg_unique_date_interval')) # TODO: Put the records affected

    def get_state(self, name):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        start_date = self.start_date or MIN_DATE
        end_date = self.end_date or MAX_DATE

        if start_date <= today <= end_date:
            return 'open'
        return 'closed'

# TODO: Do not allow to delete a membership. Only deactivate it¿?
class REGEMember(ModelView, ModelSQL):
    'Party membership on AEAT REGE'
    __name__ = 'aeat.rege.member'

    rege = fields.Many2One('aeat.rege', 'REGE',
        required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', 'Party',
        required=True, ondelete='CASCADE')
    registration_date = fields.Date('Registration Date',
        required=True)
    exit_date = fields.Date('Exit Date')
    current_member = fields.Function(
        fields.Boolean('Current Member'),
        'get_current_member')

    @staticmethod
    def default_registration_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @classmethod
    def validate(cls, records):
        super().validate(records)
        for record in records:
            members = cls.search([
                ('id', '!=', record.id),
                ('party', '=', record.party.id),
                ('rege', '=', record.rege.id),
            ])
            for member in members:
                if record.current_member and member.current_member:
                    raise UserError(gettext('aeat_rege.msg_active_membership'))  # TODO: Put the records affected

    def get_current_member(self, name):
        pool = Pool()
        Date = pool.get('ir.date')

        today = Date.today()
        return not (self.exit_date and self.exit_date >= today)

class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    reges = fields.One2Many('aeat.rege.registration', 'party', 'REGEs')


# TODO: Add helps
# TODO: account_period | company
# class InvoiceLine(metaclass=PoolMeta):
#     __name__ = 'account.invoice.line'

#     cost_price = fields.Numeric('Cost Price', digits='currency',
#         states={
#             'invisible': ~Bool(Eval('cost_price_show')),
#             'required': Bool(Eval('cost_price_show')),
#             })
#     cost_price_show = fields.Function(
#         fields.Boolean('Show Cost Price?'), 'on_change_with_cost_price_show')

#     @property
#     def taxable_lines(self):
#         taxable_lines = super().taxable_lines

#         if (hasattr(self, 'invoice') and hasattr(self.invoice, 'type')):
#             invoice_type = self.invoice.type
#         if not invoice_type:
#             invoice_type = getattr(self, 'invoice_type', None)

#         if invoice_type == 'out':
#             cost_price = getattr(self, 'cost_price', None) or Decimal(0)
#             taxable_lines[0][1] -= cost_price
#         return taxable_lines

#     @fields.depends('invoice', '_parent_invoice.type', '_parent_invoice.company', 'party', '_parent_party.aeat_rege')
#     def on_change_with_cost_price_show(self, name=None):
#         if not (self.invoice and self.invoice.type == 'out'):
#             return False
#         elif not (self.invoice.company and self.invoice.company.aeat_rege):
#             return False
#         elif not (self.party and self.party.aeat_rege):
#             return False
#         return True

#     @fields.depends('product')
#     def on_change_product(self):
#         if self.product and self.product.cost_price:
#             self.cost_price = self.product.cost_price
