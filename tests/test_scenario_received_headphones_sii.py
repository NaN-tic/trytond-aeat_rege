import unittest
from datetime import date
from decimal import Decimal

from proteus import Model
from trytond.model.exceptions import RequiredValidationError
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, create_tax, get_accounts)
from trytond.modules.account_invoice.tests.tools import set_fiscalyear_invoice_sequences
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestReceivedHeadphonesSII(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        cfg = activate_modules(['aeat_rege', 'aeat_sii', 'account_es'])
        create_company()
        company = get_company()
        company.party.identifiers.new(type='eu_vat', code='ES01234567L')
        company.party.save()
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, date(2026, 1, 1)))
        fiscalyear.click('create_period')
        create_chart(company)
        accounts = get_accounts(company)
        Party = Model.get('party.party')
        Journal = Model.get('account.journal')
        REGE = Model.get('aeat.rege')
        Tax = Model.get('account.tax')
        Invoice = Model.get('account.invoice')
        supplier = Party(name='Corporate services supplier')
        supplier.identifiers.new(type='eu_vat', code='ESB05439716')
        supplier.save()
        journal = Journal(name='REGE sales', type='revenue')
        journal.save()
        group = REGE(name='VAT group', invoice_journal=journal)
        group.periods.new(type='advanced', start_date=date(2025, 1, 1))
        group.save()
        for party in (company.party, supplier):
            membership = party.rege_memberships.new()
            membership.rege = group
            membership.registration_date = date(2025, 1, 1)
            party.save()
        tax = create_tax(Decimal('0.21'))
        tax.tax_kind = 'vat'
        tax.deducible = True
        tax.sii_received_key = '01'
        tax.sii_operation_key = 'F1'
        tax.sii_book_key = 'R'
        tax.save()
        accounts['expense'].taxes.append(Tax(tax.id))
        accounts['expense'].save()
        certificate = Model.get('certificate')(name='Test certificate')
        certificate.save()
        configuration = Model.get('account.configuration')(1)
        configuration.aeat_certificate_sii = certificate
        configuration.save()
        payment_term = Model.get('account.invoice.payment_term')(name='Direct')
        payment_term.lines.new(type='remainder')
        payment_term.save()

        # The client sends incomplete lines while a new invoice is being edited.
        values = {
                'type': 'in', 'state': 'draft', 'company': company.id,
                'party': supplier.id, 'currency': company.currency.id,
                'invoice_date': None, 'accounting_date': None,
                'sii_received_key': '06', 'taxes': [],
                }
        for partial_line in [
                {'taxes': []}, {'taxes': [tax.id]},
                {'taxes': [tax.id], 'quantity': 1,
                    'unit_price': Decimal('85.96')}]:
            with self.subTest(partial_line=partial_line):
                values['lines'] = [dict(partial_line, id=-1, type='line')]
                changes = Invoice._proxy.on_change_lines(values, cfg.context)
                self.assertEqual(changes['total_amount'], Decimal(0))
                summary = Invoice._proxy.on_change_with_rege_fiscal_summary(
                    dict(values, total_amount=Decimal(0)), cfg.context)
                self.assertIn('REGE cost base', summary)

        # The invoice type comes from the parent, even when invoice_type is
        # absent on the line. A zero deductible rate must not become 100%.
        for rate, amount, vat in [
                (Decimal(1), Decimal('85.96'), Decimal('18.05')),
                (Decimal(0), Decimal('104.01'), Decimal(0))]:
            values['lines'] = [{
                    'id': -1, 'type': 'line', 'taxes': [tax.id],
                    'quantity': 1, 'unit_price': Decimal('85.96'),
                    'cost_price': Decimal('85.96'), 'amount': amount,
                    'taxes_deductible_rate': rate,
                    }]
            changes = Invoice._proxy.on_change_lines(values, cfg.context)
            self.assertEqual(changes['tax_amount'], vat)
            self.assertEqual(changes['total_amount'], Decimal('104.01'))

        invoice = Invoice(type='in', party=supplier, reference='G0007-26',
            invoice_date=date(2026, 2, 28), accounting_date=date(2026, 2, 28),
            payment_term=payment_term)
        for description, price, cost in [
                ('Headphones', Decimal('85.96'), Decimal('85.96')),
                ('Internal management', Decimal('8.60'), Decimal(0))]:
            line = invoice.lines.new()
            line.description = description
            line.account = accounts['expense']
            line.quantity = 1
            line.unit_price = price
            with self.assertRaises(RequiredValidationError):
                invoice.save()
            line.cost_price = cost
            line.taxes_deductible_rate = (Decimal(0)
                if description == 'Headphones' else Decimal(1))
            self.assertEqual([t.id for t in line.taxes], [tax.id])
        invoice.save()
        self.assertEqual(invoice.sii_received_key, '06')
        self.assertFalse(invoice.taxes)
        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.tax_amount, Decimal(0))
        self.assertEqual(invoice.untaxed_amount, Decimal('112.61'))
        self.assertEqual(invoice.total_amount, Decimal('112.61'))
        self.assertEqual([line.amount for line in invoice.lines],
            [Decimal('104.01'), Decimal('8.60')])
        self.assertEqual(sum((line.debit for line in invoice.move.lines), Decimal(0)),
            Decimal('112.61'))
        self.assertEqual(sum((line.credit for line in invoice.move.lines), Decimal(0)),
            Decimal('112.61'))

        with Transaction().start(cfg.database_name, cfg.user, context=cfg.context):
            record = cfg.pool.get('account.invoice')(invoice.id)
            summary = record.get_rege_fiscal_summary_data()
            self.assertEqual(summary['commercial_base'], Decimal('94.56'))
            self.assertEqual(summary['cost_base'], Decimal('85.96'))
            self.assertEqual(summary['supported'], Decimal('18.05'))
            self.assertEqual(summary['deductible'], Decimal(0))
            self.assertEqual(summary['non_deductible'], Decimal('18.05'))
            self.assertIn('18.05', record.rege_fiscal_summary)
            mapper = cfg.pool.get('aeat.sii.recieved.invoice.mapper')()
            request = mapper.build_submit_request(record)
            self.assertEqual(request['IDFactura']['NumSerieFacturaEmisor'], 'G0007-26')
            values = request['FacturaRecibida']
            self.assertEqual(values['TipoFactura'], 'F1')
            self.assertEqual(values['ClaveRegimenEspecialOTrascendencia'], '06')
            self.assertEqual(values['BaseImponibleACoste'], Decimal('85.96'))
            self.assertEqual(values['ImporteTotal'], Decimal('112.61'))
            self.assertEqual(values['CuotaDeducible'], Decimal(0))
            detail, = values['DesgloseFactura']['DesgloseIVA']['DetalleIVA']
            self.assertEqual(detail['BaseImponible'], Decimal('94.56'))
            self.assertEqual(detail['TipoImpositivo'], Decimal('21'))
            self.assertEqual(detail['CuotaSoportada'], Decimal('18.05'))
            self.assertNotIn('E6', str(request))
            self.assertEqual(record.get_rege_general_base(), Decimal('94.56'))
            self.assertEqual(record.get_rege_received_cost_base(), Decimal('85.96'))

        # Exempt bases remain visible, and manually entered rows are preserved.
        exempt = create_tax(Decimal(0))
        exempt.tax_kind = 'vat'
        exempt.save()
        draft = Invoice(type='in', party=supplier,
            invoice_date=date(2026, 2, 28), payment_term=payment_term)
        line = draft.lines.new()
        line.description = 'Exempt operation'
        line.account = accounts['expense']
        line.quantity = 1
        line.unit_price = Decimal('100')
        line.cost_price = Decimal('80')
        while line.taxes:
            line.taxes.pop()
        line.taxes.append(Tax(exempt.id))
        draft.save()
        self.assertEqual(len(draft.taxes), 1)
        self.assertEqual(draft.taxes[0].base, Decimal('80'))
        self.assertEqual(draft.taxes[0].amount, Decimal(0))
        manual = draft.taxes.new()
        manual.manual = True
        manual.description = 'Manual zero row'
        manual.account = accounts['tax']
        manual.tax = Tax(tax.id)
        manual.base = Decimal(0)
        manual.amount = Decimal(0)
        draft.save()
        self.assertEqual(len(draft.taxes), 2)
        draft.lines[0].cost_price = Decimal(0)
        draft.save()
        self.assertEqual(len(draft.taxes), 1)
        self.assertTrue(draft.taxes[0].manual)
