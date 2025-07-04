import unittest
from datetime import datetime
from decimal import Decimal
from proteus import Model
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.modules.company.tools import create_company, get_company
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, create_tax, create_tax_code, get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    set_fiscalyear_invoice_sequences)

class Test(unittest.TestCase):

    def setUp(self):
        drop_db()

    def tearDown(self):
        drop_db()

    def test(self):
        activate_modules(['aeat_rege'])

        Employee = Model.get('company.employee')
        Company = Model.get('company.company')
        InvoiceLine = Model.get('account.invoice.line')
        Party = Model.get('party.party')
        User = Model.get('res.user')
        TaxCode = Model.get('account.tax.code')
        Product = Model.get('product.product')
        ProductTemplate = Model.get('product.template')
        ProductUom = Model.get('product.uom')

        today = datetime.date.today()

        # Create a company
        create_company()
        company = get_company()
        company.aeat_rege = True
        company.save()

        # Assign a user to the company

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, today))
        fiscalyear.click('create_period')
        period = fiscalyear.periods[0]
        period_ids = [p.id for p in fiscalyear.periods]

        # Create chart of accounts
        create_chart(company)
        accounts = get_accounts(company)

        # Create tax
        tax = create_tax(Decimal('21.00'))
        tax.name = 'IVA 21%'
        tax.save()

        # Find product uom
        unit, = ProductUom.find([('name', '=', 'Unit')])

        # Create a product
        template = ProductTemplate(name='Chair', default_uom=unit, type='goods', list_price=Decimal('100.00'))
        template.save()
        product, = template.products

        ## CASE 1
        # Company with REGE and Supplier with REGE

        ## CASE 2
        # Company with REGE and Supplier without REGE

        ## CASE 3
        # Company without REGE and Supplier with REGE
