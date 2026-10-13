import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO

from lxml import etree
from openpyxl import load_workbook
from proteus import Model
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, create_tax, get_accounts)
from trytond.modules.account_invoice.tests.tools import set_fiscalyear_invoice_sequences
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestTaxesByInvoice(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        cfg = activate_modules(['account_reports', 'aeat_rege', 'account_es'])
        create_company()
        company = get_company()
        fiscalyear = set_fiscalyear_invoice_sequences(create_fiscalyear(
                company, (date(2026, 1, 1), date(2026, 12, 31))))
        fiscalyear.click('create_period')
        create_chart(company)
        accounts = get_accounts(company)
        tax = create_tax(Decimal('0.21'))
        tax.tax_kind = 'vat'
        tax.save()
        accounts['expense'].taxes.append(tax)
        accounts['expense'].save()
        supplier = Model.get('party.party')(name='Group supplier')
        supplier.save()
        journal = Model.get('account.journal')(name='REGE', type='revenue')
        journal.save()
        group = Model.get('aeat.rege')(name='Group', invoice_journal=journal)
        group.periods.new(type='advanced', start_date=date(2025, 1, 1))
        group.save()
        for party in (company.party, supplier):
            member = party.rege_memberships.new()
            member.rege = group
            member.registration_date = date(2025, 1, 1)
            party.save()
        payment_term = Model.get('account.invoice.payment_term')(name='Direct')
        payment_term.lines.new(type='remainder')
        payment_term.save()
        Invoice = Model.get('account.invoice')
        invoices = []
        for day, quantity, deduction in [
                (1, 1, Decimal(0)), (2, -1, Decimal(0)),
                (3, 1, Decimal('0.25'))]:
            invoice = Invoice(type='in', party=supplier, payment_term=payment_term,
                invoice_date=date(2026, 2, day), accounting_date=date(2026, 2, day),
                reference='REGE-%s' % day)
            for description, price, cost, rate in [
                    ('Equipment', Decimal('80'), Decimal('80'), deduction),
                    ('Group management', Decimal('8'), Decimal(0), Decimal(1))]:
                line = invoice.lines.new()
                line.description = description
                line.account = accounts['expense']
                line.quantity = quantity
                line.unit_price = price
                line.cost_price = cost
                line.taxes_deductible_rate = rate
            invoice.save()
            invoice.click('post')
            self.assertEqual(invoice.state, 'posted')
            self.assertEqual(invoice.total_amount, Decimal('104.80') * quantity)
            invoices.append(invoice)

        configuration = Model.get('account.configuration')(1)
        configuration.tax_rounding = 'document'
        configuration.save()
        rounded = Invoice(type='in', party=supplier, payment_term=payment_term,
            invoice_date=date(2026, 2, 4), accounting_date=date(2026, 2, 4),
            reference='Document rounding')
        for index in range(2):
            line = rounded.lines.new()
            line.description = 'Small cost %s' % index
            line.account = accounts['expense']
            line.quantity = 1
            line.unit_price = Decimal('0.03')
            line.cost_price = Decimal('0.03')
        rounded.save()
        rounded.click('post')
        self.assertEqual(rounded.total_amount, Decimal('0.07'))

        data = dict(company=company.id, fiscalyear=fiscalyear.id, periods=[],
            parties=[supplier.id], excluded_parties=[], totals_only=False,
            partner_type='suppliers', tax_type='all', taxes=[tax.id],
            output_format='html')
        with Transaction().start(cfg.database_name, cfg.user, context=cfg.context):
            Report = cfg.pool.get('account_reports.taxes_by_invoice', type='report')
            Xlsx = cfg.pool.get('account_reports.taxes_by_invoice_xlsx', type='report')
            for day, sign in [(1, 1), (2, -1), (3, 1)]:
                for grouping in ('invoice', 'base_tax_code'):
                    with self.subTest(day=day, grouping=grouping):
                        values = dict(data, grouping=grouping,
                            start_date=date(2026, 2, day), end_date=date(2026, 2, day))
                        records, parameters = Report.prepare(values)
                        rows = [row.raw for group in records.values() for row in group]
                        self.assertEqual(len(rows), 2)
                        self.assertEqual(sorted((r.company_base, r.company_amount)
                                for r in rows), sorted([
                                    (Decimal('80') * sign, Decimal('16.80') * sign),
                                    (Decimal('8') * sign, Decimal(0))]))
                        self.assertEqual(parameters['totals'], {
                                'total_untaxed': Decimal('88') * sign,
                                'total_tax': Decimal('16.80') * sign,
                                'total': Decimal('104.80') * sign,
                                'cost_base': Decimal('80') * sign})
                        details = parameters['rege_details'].values()
                        self.assertEqual(sorted(d['cost_base'] for d in details),
                            sorted([Decimal(0), Decimal('80') * sign]))
                        html = str(Report.body(None, {
                                    'records': records, 'parameters': parameters,
                                    'output_format': 'pdf'}, []))
                        self.assertIn('Group management', html)
                        self.assertIn('REGE Cost Base', html)
                        document = etree.HTML(html)
                        for row in document.xpath('//tr[td and not(td/@colspan)]'):
                            self.assertEqual(len(row.findall('td')), 13)
                        workbook = load_workbook(BytesIO(
                                Xlsx.get_content([], values)), data_only=True)
                        rows = list(workbook.active.values)
                        management, = [row for row in rows
                            if len(row) > 12 and row[12] == 'Group management']
                        self.assertEqual(management[6], 8 * sign)
                        self.assertEqual(management[8], 0)
                        self.assertEqual(management[11], 0)
                        summary_parameters = dict(parameters, totals_only=True)
                        html = str(Report.body(None, {
                                    'records': records,
                                    'parameters': summary_parameters,
                                    'output_format': 'pdf'}, []))
                        self.assertNotIn('Group management', html)
                        self.assertIn('REGE Cost Base', html)
            values = dict(data, grouping='invoice', start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 2), tax_type='refunded')
            records, parameters = Report.prepare(values)
            self.assertEqual(parameters['totals']['total'], Decimal('-104.80'))
            records, parameters = Report.prepare(dict(values, tax_type='invoiced'))
            self.assertEqual(parameters['totals']['total'], Decimal('104.80'))
            records, _ = Report.prepare(dict(values, excluded_parties=[supplier.id]))
            self.assertFalse(records)
            records, parameters = Report.prepare(dict(values,
                    tax_type='all', start_date=date(2026, 2, 4),
                    end_date=date(2026, 2, 4)))
            self.assertEqual(parameters['totals']['total'], Decimal('0.07'))
            self.assertEqual(parameters['totals']['total_tax'], Decimal('0.01'))
            self.assertEqual(parameters['totals']['cost_base'], Decimal('0.06'))
            records, _ = Report.prepare(dict(values,
                    start_date=date(2026, 3, 1), end_date=date(2026, 3, 31)))
            self.assertFalse(records)
            # Report preparation must not persist any synthetic fiscal rows.
            self.assertFalse(cfg.pool.get('account.invoice.tax').search([
                        ('invoice', 'in', [i.id for i in invoices[:2]])]))
