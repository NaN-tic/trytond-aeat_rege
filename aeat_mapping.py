# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction


class REGEMapperMixin:

    def get_tax_base(self, tax):
        invoice = tax.invoice
        if not invoice._get_rege(advanced=True) or tax.manual:
            return super().get_tax_base(tax)
        base = Decimal(0)
        for line in invoice.lines:
            if line.type != 'line' or tax._key not in line._get_taxes():
                continue
            with Transaction().set_context(_rege_general_base=True):
                for value in line._get_taxes().values():
                    if value.tax == tax.tax:
                        base += value.base
        return self._company_amount(invoice, base)

    tax_base = get_tax_base

    def _not_deductible_taxes(self, invoice):
        result = super()._not_deductible_taxes(invoice)
        if invoice._get_rege(advanced=True):
            with Transaction().set_context(_rege_general_base=True):
                general = super()._not_deductible_taxes(invoice)
            for rate, values in result.items():
                values['base'] = self._company_amount(
                    invoice, general[rate]['base'])
                values['amount'] = self._company_amount(
                    invoice, values['amount'])
        return result

    def _company_amount(self, invoice, amount):
        Currency = Pool().get('currency.currency')
        with Transaction().set_context(date=invoice.currency_date):
            return Currency.compute(
                invoice.currency, amount, invoice.company.currency)

    def total_amount(self, invoice):
        if invoice._get_rege(advanced=True):
            withholding = sum((tax.amount for tax in invoice.taxes
                    if tax.tax and tax.tax.tax_kind == 'irpf'), Decimal(0))
            return self._company_amount(
                invoice, invoice.total_amount - withholding)
        return super().total_amount(invoice)


class IssuedInvoiceMapper(REGEMapperMixin, metaclass=PoolMeta):
    __name__ = 'aeat.sii.issued.invoice.mapper'

    def build_issued_invoice(self, invoice):
        result = super().build_issued_invoice(invoice)
        if invoice._get_rege(advanced=True):
            result['BaseImponibleACoste'] = self._company_amount(
                invoice, invoice.get_rege_received_cost_base())
        return result


class RecievedInvoiceMapper(REGEMapperMixin, metaclass=PoolMeta):
    __name__ = 'aeat.sii.recieved.invoice.mapper'

    def build_received_invoice(self, invoice):
        result = super().build_received_invoice(invoice)
        if invoice._get_rege(advanced=True):
            result['BaseImponibleACoste'] = self._company_amount(
                invoice, invoice.get_rege_received_cost_base())
        return result
