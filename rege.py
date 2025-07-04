from decimal import Decimal
from trytond.model import ModelSQL, fields, MultiValueMixin
from trytond.modules.company.model import CompanyValueMixin
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval


# TODO: Add helps
# TODO: What happens if a Party is on a Company that has REGE enabled, but the Party itself is not registered in REGE?
class Company(metaclass=PoolMeta):
    __name__ = 'company.company'

    aeat_rege = fields.Boolean('Registered in REGE')


class Party(MultiValueMixin, metaclass=PoolMeta):
    __name__ = 'party.party'

    aeat_rege = fields.MultiValue(fields.Boolean('Registered in REGE'))
    aeat_reges = fields.One2Many(
        'party.party.rege', 'party', 'AEAT REGEs')

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'aeat_rege'}:
            return pool.get('party.party.rege')
        return super().multivalue_model(field)


class PartyRege(ModelSQL, CompanyValueMixin):
    'Party-Company REGE Relation'
    __name__ = 'party.party.rege'

    party = fields.Many2One('party.party', 'Party', ondelete='CASCADE',
        context={ 'company': Eval('company', -1) },
        depends={'company'})
    aeat_rege = fields.Boolean('Registered in REGE')


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    cost_price = fields.Numeric('Cost Price', digits='currency',
        states={
            'invisible': ~Bool(Eval('cost_price_show')),
            'required': Bool(Eval('cost_price_show')),
            })
    cost_price_show = fields.Function(
        fields.Boolean('Show Cost Price?'), 'on_change_with_cost_price_show')

    @property
    def taxable_lines(self):
        taxable_lines = super().taxable_lines

        if (hasattr(self, 'invoice') and hasattr(self.invoice, 'type')):
            invoice_type = self.invoice.type
        if not invoice_type:
            invoice_type = getattr(self, 'invoice_type', None)

        if invoice_type == 'out':
            cost_price = getattr(self, 'cost_price', None) or Decimal(0)
            taxable_lines[0][1] -= cost_price
        return taxable_lines

    @fields.depends('invoice', '_parent_invoice.type', '_parent_invoice.company', 'party', '_parent_party.aeat_rege')
    def on_change_with_cost_price_show(self, name=None):
        if not (self.invoice and self.invoice.type == 'out'):
            return False
        elif not (self.invoice.company and self.invoice.company.aeat_rege):
            return False
        elif not (self.party and self.party.aeat_rege):
            return False
        return True

    @fields.depends('product')
    def on_change_product(self):
        if self.product and self.product.cost_price:
            self.cost_price = self.product.cost_price
