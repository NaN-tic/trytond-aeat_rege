# -*- coding: utf-8 -*-
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta


class IssuedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.issued.invoice.mapper'

    def build_issued_invoice(self, invoice):
        ret = super().build_issued_invoice(invoice)
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = sum(
                [l.cost_price * l.quantity for l in invoice.lines])
        return ret


class RecievedInvoiceMapper(metaclass=PoolMeta):
    __name__ = 'aeat.sii.recieved.invoice.mapper'

    def build_received_invoice(self, invoice):
        ret = super().build_received_invoice(invoice)
        if invoice and invoice.cost_price_show:
            ret['BaseImponibleACoste'] = invoice.company_untaxed_amount
        return ret
