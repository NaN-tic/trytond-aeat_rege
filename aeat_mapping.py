# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta
from decimal import Decimal


class IssuedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.issued.invoice.mapper'

    def build_issued_invoice(self, invoice):
        ret = super().build_issued_invoice(invoice)
        currency = invoice.currency
        if invoice and invoice.cost_price_show:
            cost = Decimal('0.0')
            amount = Decimal('0.0')
            for line in invoice.lines:
                line_cost = currency.round(
                    line.cost_price * Decimal(str(line.quantity)))
                cost += line_cost
                for tax in line.taxes:
                    amount += currency.round(line_cost * tax.rate)
            ret['BaseImponibleACoste'] = cost
            ret['CuotaRepercutida'] = amount
        return ret


class RecievedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.recieved.invoice.mapper'

    def build_received_invoice(self, invoice):
        ret = super().build_received_invoice(invoice)
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = invoice.company_untaxed_amount
        return ret
