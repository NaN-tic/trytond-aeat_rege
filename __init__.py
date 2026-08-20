# This file is part aeat_rege module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import aeat_mapping, invoice, papyrus, party, rege, tax

def register():
    Pool.register(
        rege.REGE,
        rege.REGEPeriod,
        rege.REGEMember,
        party.Party,
        invoice.Invoice,
        invoice.InvoiceLine,
        invoice.InvoiceTax,
        tax.TaxTemplate,
        tax.Tax,
        module='aeat_rege', type_='model')
    Pool.register(
        papyrus.Document,
        depends=['papyrus_model'],
        module='aeat_rege', type_='model')
    Pool.register(
        invoice.SIIInvoice,
        aeat_mapping.IssuedInvoiceMapper,
        aeat_mapping.RecievedInvoiceMapper,
        depends=['aeat_sii'],
        module='aeat_rege', type_='model')
    Pool.register(
        module='aeat_rege', type_='wizard')
    Pool.register(
        module='aeat_rege', type_='report')
