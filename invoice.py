from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval
from trytond.modules.currency.fields import Monetary
try:
    from trytond.trytond.module.aeat_sii import _SII_INVOICE_KEYS
except:
    _SII_INVOICE_KEYS = []


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

    @classmethod
    def _store_cache(cls, invoices):
        InvoiceTax = Pool().get('account.invoice.tax')

        tax_to_write = []
        for invoice in invoices:
            for tax in invoice.taxes:
                tax_to_write.extend(([tax], {
                    'cost_price_amount_cache': tax._get_cost_price_amount(
                        invoice=invoice),
                    }))

        super()._store_cache(invoices)

        if tax_to_write:
            InvoiceTax.write(*tax_to_write)

    @classmethod
    def draft(cls, invoices):
        InvoiceTax = Pool().get('account.invoice.tax')

        taxes = []
        for invoice in invoices:
            taxes.extend(list(invoice.taxes or []))

        super().draft(invoices)

        if taxes:
            InvoiceTax.write(taxes, {
                'cost_price_amount_cache': None,
                })


class SIIInvoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    def _set_sii_keys(self):
        pool = Pool()
        Date = pool.get('ir.date')

        super()._set_sii_keys()

        if not self.company or not self.party:
            return

        date = self.accounting_date or self.invoice_date or Date.today()
        party_rege = self.party.get_rege_by_date(date)
        company_rege = self.company.party.get_rege_by_date(date)
        if party_rege and company_rege and party_rege == company_rege:
            if self.type == 'out':
                self.sii_issued_key = '06'
            elif self.type == 'in':
                self.sii_received_key = '06'


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
                or not self.invoice):
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
            if self.invoice.type == "in":
                return True
            return self.cost_price is not None

        return True

    def _credit(self):
        line = super()._credit()
        line.cost_price = self.cost_price
        return line


class InvoiceTax(metaclass=PoolMeta):
    __name__ = 'account.invoice.tax'

    cost_price_amount = fields.Function(Monetary('Cost Price Amount',
            digits='currency', currency='currency'),
        'get_cost_price_amount')
    cost_price_amount_cache = Monetary('Cost Price Amount',
        digits='currency', currency='currency', readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._check_modify_exclude |= {'cost_price_amount_cache'}

    @classmethod
    def copy(cls, taxes, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default['cost_price_amount_cache'] = None
        return super().copy(taxes, default=default)

    def get_cost_price_amount(self, name=None):
        if self.cost_price_amount_cache is not None:
            return self.cost_price_amount_cache

        return self._get_cost_price_amount()

    def _get_cost_price_amount(self, invoice=None):
        amount = Decimal('0.0')
        invoice = invoice or self.invoice or getattr(self, '_parent_invoice',
            None)
        currency = invoice.currency if invoice else None
        tax = self.tax
        if not invoice or not currency or not tax:
            return amount

        for line in invoice.lines:
            if (line.type != 'line' or line.cost_price is None
                    or tax not in line.taxes):
                continue
            amount += (
                line.cost_price * Decimal(str(line.quantity)) * tax.rate)
        return currency.round(amount)
