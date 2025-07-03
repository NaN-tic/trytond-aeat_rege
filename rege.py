from trytond.model import ModelSQL, fields
from trytond.modules.company.model import CompanyValueMixin
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval


# TODO: Add helps
class Company(metaclass=PoolMeta):
    __name__ = 'company.company'

    aeat_rege = fields.Boolean('Registered in REGE',
        help='If checked, AEAT REGE is enabled for this company.') # TODO: Redo help


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    aeat_rege = fields.MultiValue(fields.Boolean('Registered in REGE'))
    aeat_rege_group = fields.One2Many(
        'party.party.rege_group', 'party', 'REGE Group')

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'aeat_rege'}:
            return pool.get('party.party.rege_group')
        return super().multivalue_model(field)


class PartyRegeGroup(ModelSQL, CompanyValueMixin):
    'Party REGE Group'
    __name__ = 'party.party.rege_group'

    party = fields.Many2One('party.party', 'Party', ondelete='CASCADE',
        context={ 'company': Eval('company', -1) },
        depends={'company'})
    aeat_rege = fields.Boolean('Registered in REGE')


class AccountInvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    cost_price = fields.Numeric('Cost Price', digits='currency',
        states={
            'invisible': Bool(Eval('company.aeat_rege')) & Bool(Eval('party.aeat_rege')) # Eval('type') == 'out' &
            }) # FIXME: Company?

    @property
    def taxable_lines(self):
        taxable_lines = []
        for line in self.lines:
            pass
        return taxable_lines

    @fields.depends('product')
    def on_change_with_product(self):
        if not self.product: # or self.cost_price: FIXME:
            return
        return self.product.cost_price
