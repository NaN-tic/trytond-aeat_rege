from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.i18n import gettext


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    cost_price_show = fields.Function(
        fields.Boolean('Display Cost Price?'),
        'on_change_with_cost_price_show')

    @fields.depends('lines')
    def on_change_with_cost_price_show(self, name=None):
        if not self.lines:
            return False
        return all([x.cost_price_show for x in self.lines])


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

        if cost_price_show and taxable_lines:
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
        '_parent_invoice.accounting_date', '_parent_invoice.invoice_date')
    def on_change_with_cost_price_show(self, name=None):
        Date = Pool().get('ir.date')

        if (not self.company or not self.invoice_party or self.type != 'line'
                or self.invoice_type == 'in' or not self.invoice):
            return False

        date = (self.invoice.accounting_date or self.invoice.invoice_date
            or Date.today())

        party_rege = self.invoice_party.get_rege_by_date(date)
        company_rege = self.company.party.get_rege_by_date(date)
        if not party_rege or not company_rege or party_rege != company_rege:
            return False

        period = party_rege.get_period_by_date(date)
        if not period or period.type != 'advanced':
            return False

        if self.invoice_state != 'draft':
            return self.cost_price is not None

        return True

    def _credit(self):
        line = super()._credit()
        line.cost_price = self.cost_price
        return line
