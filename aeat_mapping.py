# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal

from trytond.pool import Pool, PoolMeta


class IssuedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.issued.invoice.mapper'

    def build_issued_invoice(self, invoice):
        ret = super().build_issued_invoice(invoice)

        currency = invoice.currency
        if invoice and invoice.cost_price_show:
            cost = Decimal('0.0')
            for line in invoice.lines:
                if line.rege_cost_base_exclude:
                    continue
                cost += currency.round(
                    line.cost_price * Decimal(str(line.quantity)))
            if invoice.currency:
                cost = invoice.currency.round(cost)
            ret['BaseImponibleACoste'] = cost
        return ret

    def build_taxes(self, tax):
        pool = Pool()
        Tax = pool.get('account.tax')

        res = super().build_taxes(tax)

        if tax.cost_price_show and 'CuotaRepercutida' in res:
            tax_date = tax.invoice.tax_date
            value, = Tax.compute([tax.tax], tax.cost_price, 1, tax_date)
            amount = 0
            if (value['tax'] == tax.tax
                    and value['base'] == tax.cost_price):
                amount = value['amount']
                if tax.invoice.currency:
                    amount = tax.invoice.currency.round(amount)
            res['CuotaRepercutida'] = amount
        return res


class RecievedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.recieved.invoice.mapper'

    def build_received_invoice(self, invoice):
        ret = super().build_received_invoice(invoice)
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = invoice.get_rege_received_cost_base()
        return ret
