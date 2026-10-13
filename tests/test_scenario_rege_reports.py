import datetime
import unittest
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from lxml import etree
from proteus import Model

from trytond.modules.account.tests.tools import create_chart, create_tax, get_accounts
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestREGEReports(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        for html in (False, True):
            with self.subTest(html=html):
                modules = ['aeat_rege']
                if html:
                    modules.append('html_report')
                cfg = activate_modules(modules)
                create_company()
                company = get_company()
                create_chart(company)
                accounts = get_accounts(company)
                Party = Model.get('party.party')
                Journal = Model.get('account.journal')
                REGE = Model.get('aeat.rege')
                Invoice = Model.get('account.invoice')
                customer = Party(name='Group customer')
                customer.save()
                outsider = Party(name='External customer')
                outsider.save()
                journal = Journal(name='REGE sales', type='revenue')
                journal.save()
                group = REGE(name='Group', invoice_journal=journal)
                group.periods.new(type='advanced')
                group.save()
                for party in (company.party, customer):
                    membership = party.rege_memberships.new()
                    membership.rege = group
                    membership.registration_date = datetime.date.today()
                    party.save()
                taxable = create_tax(Decimal('0.21'))
                taxable.save()
                exempt = create_tax(Decimal(0))
                exempt.legal_notice = 'Exempt under article 20.Uno.2.'
                exempt.save()
                cases = [
                    ('exempt', [(exempt, False, Decimal('40'))]),
                    ('waived', [(taxable, True, Decimal('40'))]),
                    ('mixed', [(exempt, False, Decimal('40')),
                        (taxable, True, Decimal('40'))]),
                    ('zero', [(taxable, False, Decimal(0))]),
                    ('ordinary', [(taxable, False, None)]),
                    ]
                for name, lines in cases:
                    invoice = Invoice(party=(outsider
                            if name == 'ordinary' else customer), type='out')
                    invoice.invoice_date = datetime.date.today()
                    invoice.comment = 'Original comment <unchanged>'
                    for tax, waived, cost in lines:
                        line = invoice.lines.new()
                        line.description = 'Waived service' if waived else 'Service'
                        line.account = accounts['revenue']
                        line.quantity = 1
                        line.unit_price = Decimal('100')
                        line.cost_price = cost
                        line.rege_exemption_waived = waived
                        line.taxes.append(Model.get('account.tax')(tax.id))
                    invoice.save()
                    with Transaction().start(cfg.database_name, cfg.user,
                            context=cfg.context):
                        Report = cfg.pool.get('account.invoice', type='report')
                        records = Report._get_records(
                            [invoice.id], 'account.invoice', {})
                        if html:
                            from trytond.modules.html_report.engine import DualRecord
                            records = [DualRecord(cfg.pool.get('account.invoice')(
                                        invoice.id))]
                            rendered = str(Report.last_footer(None, {}, records))
                        else:
                            ModelData = cfg.pool.get('ir.model.data')
                            action = cfg.pool.get('ir.action.report')(
                                ModelData.get_id('account_invoice', 'report_invoice'))
                            context = Report.get_context(records, {}, {})
                            content = Report.render(action, context)
                            with ZipFile(BytesIO(content)) as document:
                                root = etree.fromstring(document.read('content.xml'))
                            rendered = ' '.join(root.itertext())
                            self.assertIn('Original comment <unchanged>', rendered)
                        if name == 'ordinary':
                            self.assertNotIn('REGE cost base', rendered)
                            continue
                        self.assertIn('General VAT base (articles 78 and 79)', rendered)
                        self.assertIn('REGE cost base (article 163 octies)', rendered)
                        if name in ('exempt', 'mixed'):
                            self.assertIn('Exempt under article 20.Uno.2.', rendered)
                        else:
                            self.assertNotIn('Exempt under article 20.Uno.2.', rendered)
                        if name in ('waived', 'mixed'):
                            self.assertIn('Waived service: REGE exemption waived', rendered)
                        else:
                            self.assertNotIn('163 sexies.Five', rendered)
                    invoice.reload()
                    self.assertEqual(invoice.comment, 'Original comment <unchanged>')
                drop_db()
