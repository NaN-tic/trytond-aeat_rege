import unittest
import datetime
from decimal import Decimal
from proteus import Model, Wizard
from trytond.exceptions import UserError, UserWarning
from trytond.transaction import Transaction
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
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['aeat_rege', 'aeat_sii', 'account_es'])

        AccountConfiguration = Model.get('account.configuration')
        Certificate = Model.get('certificate')
        Invoice = Model.get('account.invoice')
        Journal = Model.get('account.journal')
        Sequence = Model.get('ir.sequence.strict')
        Rege = Model.get('aeat.rege')
        Party = Model.get('party.party')
        ProductCategory = Model.get('product.category')
        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        Tax = Model.get('account.tax')

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        ## Create base for tests
            # Create a company
        create_company()
        company = get_company()
        tax_identifier = company.party.identifiers.new()
        tax_identifier.type = 'eu_vat'
        tax_identifier.code = 'ES01234567L'
        company.party.save()

            # Enable SII
        certificate = Certificate()
        certificate.name = 'Dummy'
        certificate.save()
        account_config = AccountConfiguration(1)
        account_config.aeat_certificate_sii = certificate
        account_config.save()

            # Create customer party
        customer = Party(name='Customer')
        tax_identifier = customer.identifiers.new()
        tax_identifier.type = 'eu_vat'
        tax_identifier.code = 'ES01234567L'
        customer.save()

            # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, today))
        fiscalyear.click('create_period')
        journal = Journal(name='REGE', type='revenue')
        journal.save()
        standard = fiscalyear.invoice_sequences[0].out_invoice_sequence
        sequence, = Sequence.duplicate([standard], {'prefix': 'REGE/'})
        credit_sequence, = Sequence.duplicate([standard], {'prefix': 'R-REGE/'})
        journal_sequence = fiscalyear.journal_sequences.new()
        journal_sequence.journal = journal
        journal_sequence.company = company
        journal_sequence.out_invoice_sequence = sequence
        journal_sequence.out_credit_note_sequence = credit_sequence
        fiscalyear.save()
        journal_sequence, = fiscalyear.journal_sequences

            # Create chart of accounts
        create_chart(company)
        accounts = get_accounts(company)

        # Create tax
        tax = create_tax(Decimal('0.21'))
        tax.tax_kind = 'vat'
        tax.deducible = True
        tax.legal_notice = 'Existing legal notice'
        tax.save()
        second_tax = create_tax(Decimal('0.10'))
        second_tax.tax_kind = 'vat'
        second_tax.save()
        excluded_cost_tax = create_tax(Decimal('0.00'))
        excluded_cost_tax.save()

            # Create account category
        account_category = ProductCategory(name='Account Category')
        account_category.accounting = True
        account_category.account_expense = accounts['expense']
        account_category.account_revenue = accounts['revenue']
        account_category.customer_taxes.append(tax)
        account_category.save()

            # Find product uom
        unit, = ProductUom.find([('name', '=', 'Unit')])

            # Create a product template + variant
        template = ProductTemplate(name='Potato', default_uom=unit,
            type='goods', list_price=Decimal('10.00'))
        template.account_category = account_category
        template.save()
        product, = template.products
        product.cost_price = Decimal('4.00')
        product.save()

            # Create REGE + period
        rege = Rege(name='REGE Group')
        rege.invoice_journal = journal
        period_advanced = rege.periods.new()
        period_advanced.type = 'advanced'
        period_advanced.start_date = today
        period_advanced.save()
        period_basic = rege.periods.new()
        period_basic.type = 'normal'
        period_basic.end_date = yesterday
        period_basic.save()
        rege.save()

            # Link REGE with both parties
        company_membership = company.party.rege_memberships.new()
        company_membership.rege = rege
        company_membership.registration_date = yesterday
        company_membership.save()

        customer_membership = customer.rege_memberships.new()
        customer_membership.rege = rege
        customer_membership.registration_date = yesterday
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
        line.cost_price = Decimal('4.00')
        line.account = accounts['revenue']
        line.taxes.append(Tax(tax.id))
        line.taxes.append(Tax(second_tax.id))
        line.save()

        self.assertTrue(line.cost_price_show)
        self.assertEqual(line.cost_price, product.cost_price)
        self.assertEqual(line.amount, Decimal('10.00'))
        self.assertEqual(invoice.untaxed_amount, Decimal('10.00'))
        self.assertEqual(invoice.tax_amount, Decimal('1.24'))
        self.assertEqual(invoice.total_amount, Decimal('11.24'))
        self.assertEqual(invoice.sii_issued_key, '06')
        legal_notice = ('Special regime for groups of entities, article 163 '
            'octies of VAT Law 37/1992.')
        rege_taxes = [tax for tax in invoice.taxes
            if legal_notice in (tax.legal_notice or '').split('\n')]
        self.assertEqual(len(rege_taxes), 1)
        self.assertEqual(rege_taxes[0].legal_notice, '\n'.join([
                'Existing legal notice', legal_notice]))

        invoice.sii_issued_key = '01'
        invoice.save()
        invoice.reload()
        reset_sii_keys = Wizard('aeat.sii.reset.keys', models=[invoice])
        reset_sii_keys.execute('reset')
        invoice.reload()
        self.assertEqual(invoice.sii_issued_key, '06')

        with self.assertRaises(UserWarning):
            try:
                invoice.click('validate_invoice')
            except UserWarning as warning:
                _, (key, *_) = warning.args
                raise
        Warning = Model.get('res.user.warning')
        Warning.skip(key, True, config.context)
        invoice.click('validate_invoice')
        self.assertEqual(invoice.state, 'validated')
        tax_line, = [tax_line for tax_line in invoice.taxes
            if tax_line.tax.id == tax.id]
        self.assertEqual(tax_line.cost_price_show, True)
        self.assertEqual(tax_line.cost_price, Decimal('4.00'))

        # Presentation lines must not change the fiscal treatment.
        invoice.click('draft')
        self.assertEqual(invoice.state, 'draft')
        invoice.lines.new(type='comment', description='REGE detail')
        invoice.save()
        self.assertTrue(invoice.cost_price_show)
        self.assertEqual(invoice.tax_amount, Decimal('1.24'))
        self.assertEqual(invoice.journal, journal)

        payment_term = Model.get('account.invoice.payment_term')(name='Direct')
        payment_term.lines.new(type='remainder')
        payment_term.save()
        invoice.payment_term = payment_term
        invoice.save()
        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertTrue(invoice.number.startswith('REGE/'))
        self.assertEqual(invoice.total_amount, Decimal('11.24'))
        self.assertEqual(sum((l.debit - l.credit for l in invoice.move.lines
                    if l.account.id == accounts['receivable'].id), Decimal(0)),
            Decimal('11.24'))

        cfg = config
        with Transaction().start(cfg.database_name, cfg.user,
                context=cfg.context):
            backend_invoice = cfg.pool.get('account.invoice')(invoice.id)
            mapper = cfg.pool.get('aeat.sii.issued.invoice.mapper')()
            self.assertEqual(mapper.total_amount(backend_invoice),
                Decimal('11.24'))
            for invoice_tax in backend_invoice.taxes:
                values = mapper.build_taxes(invoice_tax)
                self.assertEqual(values['BaseImponible'], Decimal('10.00'))
                self.assertEqual(values['CuotaRepercutida'], invoice_tax.amount)
            self.assertEqual(backend_invoice.get_rege_received_cost_base(),
                Decimal('4.00'))

        credit = Wizard('account.invoice.credit', models=[invoice])
        credit.execute('credit')
        credit_invoice, = Invoice.find([('id', '!=', invoice.id)])
        with self.assertRaises(UserWarning) as caught:
            credit_invoice.click('post')
        _, (key, *_) = caught.exception.args
        Warning.skip(key, True, config.context)
        credit_invoice.click('post')
        self.assertTrue(credit_invoice.number.startswith('R-REGE/'))
        self.assertEqual(credit_invoice.total_amount, Decimal('-11.24'))

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
        with self.assertRaisesRegex(UserError, 'Cost Price'):
            line.save()
        line.cost_price = Decimal(0)
        line.save()
        with self.assertRaises(UserWarning) as caught:
            invoice.click('post')
        _, (key, *_) = caught.exception.args
        Warning.skip(key, True, config.context)
        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.tax_amount, Decimal(0))

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
        # REGE with Basic
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
        self.assertNotEqual(invoice.sii_issued_key, '06')

        # Missing costs must block saving drafts, before numbering.
        invoice = base_invoice()
        invoice.invoice_date = today
        invoice.payment_term = payment_term
        line = invoice.lines.new()
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('100')
        self.assertIsNone(line.cost_price)
        with self.assertRaisesRegex(UserError, 'Cost Price'):
            invoice.save()
        self.assertFalse(invoice.number)
        invoice.lines[0].cost_price = Decimal('40')
        invoice.save()
        journal_sequence.out_invoice_sequence = standard
        journal_sequence.save()
        with self.assertRaisesRegex(UserError, 'ordinary invoices'):
            invoice.click('validate_invoice')
        journal_sequence.out_invoice_sequence = sequence
        journal_sequence.save()
        journal_sequence.out_credit_note_sequence = None
        journal_sequence.save()
        invoice.lines[0].quantity = -1
        invoice.save()
        with self.assertRaisesRegex(UserError, 'No dedicated sequence'):
            invoice.click('post')
        invoice.reload()
        self.assertFalse(invoice.number)
        journal_sequence.out_credit_note_sequence = credit_sequence
        journal_sequence.save()

        # Deductibility affects input VAT, never the supplier's cost base.
        received = Invoice(party=customer, company=company, type='in')
        received.invoice_date = today
        received.payment_term = payment_term
        line = received.lines.new()
        line.product = product
        line.quantity = 1
        line.unit_price = Decimal('100')
        line.cost_price = Decimal('40')
        line.taxes.append(Tax(tax.id))
        line.taxes_deductible_rate = Decimal('0.25')
        received.save()
        self.assertEqual(received.tax_amount, Decimal('2.10'))
        self.assertEqual(received.untaxed_amount, Decimal('106.30'))
        self.assertEqual(received.total_amount, Decimal('108.40'))
        received.lines[0].taxes_deductible_rate = Decimal('0')
        received.save()
        self.assertEqual(received.tax_amount, Decimal('0'))
        self.assertEqual(received.total_amount, Decimal('108.40'))
        received.lines[0].taxes_deductible_rate = Decimal('1')
        received.save()
        self.assertEqual(received.tax_amount, Decimal('8.40'))
        self.assertEqual(received.total_amount, Decimal('108.40'))
        received.lines[0].taxes_deductible_rate = Decimal('0.25')
        received.save()
        with Transaction().start(cfg.database_name, cfg.user,
                context=cfg.context):
            backend_received = cfg.pool.get('account.invoice')(received.id)
            mapper = cfg.pool.get('aeat.sii.recieved.invoice.mapper')()
            self.assertEqual(backend_received.get_rege_received_cost_base(),
                Decimal('40'))
            self.assertEqual(mapper.total_amount(backend_received),
                Decimal('108.40'))
            self.assertEqual(mapper._deductible_amount(backend_received),
                Decimal('2.10'))
            detail = mapper.build_taxes(
                backend_received, backend_received.taxes[0])
            non_deductible, = mapper._not_deductible_taxes(
                backend_received).values()
            self.assertEqual(detail['BaseImponible'] + non_deductible['base'],
                Decimal('100'))
            self.assertEqual(detail['CuotaSoportada'] + non_deductible['amount'],
                Decimal('8.40'))

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

        # A membership without a valid regime period must not set SII key 06.
        future = today + datetime.timedelta(days=10)
        rege.reload()
        advanced, = [p for p in rege.periods if p.type == 'advanced']
        advanced.end_date = today + datetime.timedelta(days=1)
        rege.save()
        invoice = base_invoice()
        invoice.invoice_date = future
        invoice.save()
        self.assertFalse(invoice.cost_price_show)
        self.assertNotEqual(invoice.sii_issued_key, '06')

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
