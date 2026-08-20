import unittest
import datetime
from decimal import Decimal
from proteus import Model
from trytond.exceptions import UserWarning
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, create_tax, get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    set_fiscalyear_invoice_sequences)

class Test(unittest.TestCase):

    def setUp(self):
        drop_db()

    def tearDown(self):
        drop_db()

    def test(self):
        activate_modules(['aeat_rege', 'account_es'])

        Invoice = Model.get('account.invoice')
        Rege = Model.get('aeat.rege')
        Party = Model.get('party.party')
        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        Tax = Model.get('account.tax')

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        ## Create base for tests
            # Create a company
        create_company()
        company = get_company()

            # Create customer party
        customer = Party(name='Customer')
        customer.save()

            # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, today))
        fiscalyear.click('create_period')

            # Create chart of accounts
        create_chart(company)
        accounts = get_accounts(company)

        # Create tax
        tax = create_tax(Decimal('0.21'))
        tax.legal_notice = 'Existing legal notice'
        tax.save()
        second_tax = create_tax(Decimal('0.10'))
        second_tax.save()
        excluded_cost_tax = create_tax(Decimal('0.00'))
        excluded_cost_tax.rege_cost_base_exclude = True
        excluded_cost_tax.save()

            # Find product uom
        unit, = ProductUom.find([('name', '=', 'Unit')])

            # Create a product template + variant
        template = ProductTemplate(name='Potato', default_uom=unit,
            type='goods', list_price=Decimal('10.00'))
        template.save()
        product, = template.products
        product.cost_price = Decimal('4.00')
        product.save()

            # Create REGE + period
        rege = Rege(name='REGE Group')
        period_advanced = rege.periods.new()
        period_advanced.type = 'advanced'
        period_advanced.start_date = today
        period_advanced.save()
        period_normal = rege.periods.new()
        period_normal.type = 'normal'
        period_normal.end_date = yesterday
        period_normal.save()
        rege.save()

            # Link REGE with both parties
        company_membership = company.party.rege_memberships.new()
        company_membership.rege = rege
        company_membership.save()

        customer_membership = customer.rege_memberships.new()
        customer_membership.rege = rege
        customer_membership.save()

        base_invoice = lambda: Invoice(
            party=customer, company=company, type='out')

        ## CASE 1
        # REGE with Advanced
        invoice = base_invoice()
        invoice.accounting_date = today
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(tax.id))
        line.taxes.append(Tax(second_tax.id))
        line.save()

        self.assertTrue(line.cost_price_show)
        self.assertEqual(line.cost_price, product.cost_price)
        self.assertEqual(line.amount, Decimal('10.00'))
        self.assertEqual(invoice.untaxed_amount, Decimal('10.00'))
        self.assertEqual(invoice.tax_amount, Decimal('3.10'))
        self.assertEqual(invoice.total_amount, Decimal('13.10'))
        legal_notice = ('Special regime for groups of entities, article 163 '
            'octies of VAT Law 37/1992.')
        rege_taxes = [tax for tax in invoice.taxes
            if legal_notice in (tax.legal_notice or '').split('\n')]
        self.assertEqual(len(rege_taxes), 1)
        self.assertEqual(rege_taxes[0].legal_notice, '\n'.join([
                'Existing legal notice', legal_notice]))

        # The tax default may be overridden for each REGE invoice line.
        invoice = base_invoice()
        invoice.accounting_date = today
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(excluded_cost_tax.id))
        line.save()

        line._on_change(['taxes'])
        self.assertTrue(line.rege_cost_base_exclude)
        line.rege_cost_base_exclude = False
        line.save()
        self.assertFalse(line.rege_cost_base_exclude)
        line.rege_cost_base_exclude = True
        line.save()
        self.assertTrue(line.rege_cost_base_exclude)
        with self.assertRaises(UserWarning):
            invoice.click('post')

        # Supplier REGE invoice with a base at cost of zero
        invoice = Invoice(party=customer, company=company, type='in')
        invoice.accounting_date = today
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.cost_price = Decimal(0)
        line.taxes_deductible_rate = Decimal(0)
        line.account = accounts['expense']
        line.taxes.append(Tax(tax.id))
        line.save()

        with self.assertRaises(UserWarning):
            invoice.click('post')

        ## CASE 2
        # REGE with Normal
        invoice = base_invoice()
        invoice.accounting_date = yesterday
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(tax.id))
        line.save()

        self.assertFalse(line.cost_price_show)
        self.assertEqual(invoice.untaxed_amount, Decimal('10.00'))
        self.assertEqual(invoice.tax_amount, Decimal('2.1'))
        self.assertEqual(invoice.total_amount, Decimal('12.1'))

        ## CASE 3
        # Party without REGE
        customer_out = Party(name='Customer Out')
        customer_out.save()

        invoice = base_invoice()
        invoice.party = customer_out
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(tax.id))
        line.save()

        self.assertFalse(line.cost_price_show)
        self.assertEqual(invoice.untaxed_amount, Decimal('10.00'))
        self.assertEqual(invoice.tax_amount, Decimal('2.1'))
        self.assertEqual(invoice.total_amount, Decimal('12.1'))

        ## CASE 6
        # Different REGEs for Party and Company
        rege_out = Rege(name='REGE Out')
        period_out = rege_out.periods.new()
        period_out.type = 'normal'
        period_out.save()
        rege_out.save()

        customer_out_membership = customer_out.rege_memberships.new()
        customer_out_membership.rege = rege_out
        customer_out_membership.save()

        invoice = base_invoice()
        invoice.party = customer_out
        invoice.save()

        line = invoice.lines.new()
        line.type = 'line'
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('10.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(tax.id))
        line.save()

        self.assertFalse(line.cost_price_show)
        self.assertEqual(invoice.untaxed_amount, Decimal('10.00'))
        self.assertEqual(invoice.tax_amount, Decimal('2.1'))
        self.assertEqual(invoice.total_amount, Decimal('12.1'))
