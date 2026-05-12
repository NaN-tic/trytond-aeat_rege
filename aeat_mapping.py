# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from operator import attrgetter

from trytond.pool import PoolMeta


class IssuedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.issued.invoice.mapper'

    def build_issued_invoice(self, invoice):
        ret = super().build_issued_invoice(invoice)
        currency = invoice.currency
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = currency.round(sum(
                    [l.cost_price * Decimal(str(l.quantity))
                        for l in invoice.lines]))
        return ret

    def get_tax_amount(self, tax):
        val = super().get_tax_amount(tax)
        invoice = tax.invoice
        if invoice and invoice.cost_price_show:
            val = attrgetter('cost_price_amount')(tax)
        return val


class RecievedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.recieved.invoice.mapper'

    def build_received_invoice(self, invoice):
        ret = super().build_received_invoice(invoice)
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = invoice.company_untaxed_amount
        return ret
