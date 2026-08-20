# This file is part aeat_rege module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool, PoolMeta


class Document(metaclass=PoolMeta):
    __name__ = 'papyrus.document'

    def create_invoice_lines_from_papyrus_lines(self, invoice):
        existing_lines = {
            id(line) for line in invoice.papyrus_lines if line.invoice_line}

        super().create_invoice_lines_from_papyrus_lines(invoice)

        InvoiceLine = Pool().get('account.invoice.line')
        to_write = []
        for papyrus_line in invoice.papyrus_lines:
            if id(papyrus_line) in existing_lines:
                continue
            line = papyrus_line.invoice_line
            if not line or not line.cost_price_show:
                continue
            cost_price = papyrus_line.cost_price
            if cost_price is None:
                cost_price = line.unit_price
            to_write.extend(([line], {'cost_price': cost_price}))
        if to_write:
            InvoiceLine.write(*to_write)
