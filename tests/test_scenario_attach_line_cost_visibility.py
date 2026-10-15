import unittest
from datetime import date
from decimal import Decimal

from proteus import Model
from trytond.modules.account.tests.tools import create_chart, get_accounts
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pyson import PYSONDecoder
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestAttachLineCostVisibility(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules('aeat_rege')
        create_company()
        company = get_company()
        create_chart(company)
        accounts = get_accounts(company)
        customer = Model.get('party.party')(name='Group customer')
        customer.save()
        journal = Model.get('account.journal')(name='REGE', type='revenue')
        journal.save()
        group = Model.get('aeat.rege')(name='Group', invoice_journal=journal)
        group.periods.new(type='advanced', start_date=date(2025, 1, 1))
        group.save()
        for party in (company.party, customer):
            member = party.rege_memberships.new()
            member.rege = group
            member.registration_date = date(2025, 1, 1)
            party.save()
        payment_term = Model.get('account.invoice.payment_term')(name='Direct')
        payment_term.lines.new(type='remainder')
        payment_term.save()
        Invoice = Model.get('account.invoice')
        Line = Model.get('account.invoice.line')
        line = Line(type='line', invoice_type='out', party=customer,
            account=accounts['revenue'], description='Existing service',
            quantity=1, unit_price=Decimal('100'))
        line.save()
        self.assertFalse(line.cost_price_show)
        self.assertIsNone(line.cost_price)
        # Sao can retain the standalone function value after attaching a line.
        values = {'type': line.type, 'invoice_state': line.invoice_state,
            'cost_price_show': line.cost_price_show}
        invoice = Invoice(type='out', party=customer,
            invoice_date=date(2026, 2, 1), payment_term=payment_term)
        invoice.lines.append(line)
        self.assertLess(invoice.id, 0)
        self.assertTrue(invoice.cost_price_show)
        values['_parent_invoice'] = {
            'id': invoice.id, 'cost_price_show': invoice.cost_price_show}
        for name in ('cost_price', 'rege_general_price',
                'rege_exemption_waived'):
            states = PYSONDecoder(values).decode(Line._fields[name]['states'])
            self.assertFalse(states['invisible'], name)
            self.assertFalse(states['readonly'], name)
            if name == 'cost_price':
                self.assertTrue(states['required'])
        line.cost_price = Decimal('40')
        invoice.save()
        line = Line(line.id)
        self.assertEqual(line.invoice.id, invoice.id)
        self.assertEqual(line.cost_price, Decimal('40'))
        self.assertEqual(invoice.state, 'draft')
        # A non-REGE parent must also override a stale positive line value.
        values['cost_price_show'] = True
        values['_parent_invoice']['cost_price_show'] = False
        states = PYSONDecoder(values).decode(Line._fields['cost_price']['states'])
        self.assertTrue(states['invisible'])
        self.assertFalse(states['required'])
