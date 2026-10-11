import unittest
from datetime import date
from decimal import Decimal

from proteus import Model, Wizard
from trytond.exceptions import UserError, UserWarning
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, create_tax, get_accounts)
from trytond.modules.account_invoice.tests.tools import set_fiscalyear_invoice_sequences
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestRetireLegacyTaxes(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        cfg = activate_modules(['aeat_rege', 'account_es'])
        create_company()
        company = get_company()
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company, (date(2026, 1, 1), date(2026, 12, 31))))
        fiscalyear.click('create_period')
        create_chart(company)
        accounts = get_accounts(company)
        Tax = Model.get('account.tax')
        Template = Model.get('account.tax.template')
        AccountTemplate = Model.get('account.account.template')
        Invoice = Model.get('account.invoice')
        Party = Model.get('party.party')
        PaymentTerm = Model.get('account.invoice.payment_term')
        Module = Model.get('ir.module')
        Warning = Model.get('res.user.warning')
        root, = AccountTemplate.find([('parent', '=', None)], limit=1)
        tax_account_template_id = accounts['tax'].template.id
        taxes = []
        templates = []
        # Recreate the old XML records and business taxes in the test database,
        # then run the real module upgrade and XML cleanup.
        for suffix in ('purchase', 'sale'):
            with Transaction().start(cfg.database_name, 0,
                    context=cfg.context) as transaction:
                BackendTemplate = cfg.pool.get('account.tax.template')
                template = BackendTemplate(name='Legacy REGE ' + suffix,
                    description='Legacy REGE ' + suffix,
                    account=root.id, type='percentage', rate=Decimal(0),
                    invoice_account=tax_account_template_id,
                    credit_note_account=tax_account_template_id)
                template.save()
                cfg.pool.get('ir.model.data').create([{
                            'module': 'aeat_rege', 'model': 'account.tax.template',
                            'fs_id': 'iva_ex_rege_' + suffix,
                            'db_id': template.id, 'noupdate': False}])
                template_id = template.id
                transaction.commit()
            template = Template(template_id)
            tax = create_tax(Decimal(0))
            tax.template = template
            tax.legal_notice = 'Original legacy notice'
            tax.rege_cost_base_exclude = True
            if suffix == 'sale':
                tax.end_date = date(2026, 8, 31)
            tax.save()
            taxes.append(tax)
            templates.append(template)

        # Preserve existing business tax-code lines when deleting their templates.
        Code = Model.get('account.tax.code')
        CodeLine = Model.get('account.tax.code.line')
        with Transaction().start(cfg.database_name, 0,
                context=cfg.context) as transaction:
            code_template = cfg.pool.get('account.tax.code.template')(
                name='Legacy base', account=root.id)
            code_template.save()
            code_template_id = code_template.id
            transaction.commit()
        code = Code(name='Legacy base', company=company)
        code.save()
        code_line_ids = []
        for tax, template, suffix in zip(taxes, templates, ('purchase', 'sale')):
            for kind in ('invoice', 'credit'):
                with Transaction().start(cfg.database_name, 0,
                        context=cfg.context) as transaction:
                    line_template = cfg.pool.get('account.tax.code.line.template')(
                        code=code_template_id, tax=template.id,
                        operator='+', type=kind, amount='base')
                    line_template.save()
                    cfg.pool.get('ir.model.data').create([{
                                'module': 'aeat_rege',
                                'model': 'account.tax.code.line.template',
                                'fs_id': 'iva_ex_rege_%s-base_rep_ex-%s-base'
                                % (suffix, kind),
                                'db_id': line_template.id, 'noupdate': False}])
                    line_template_id = line_template.id
                    transaction.commit()
                line = CodeLine(code=code, tax=tax, operator='+', type=kind,
                    amount='base', template=Model.get(
                        'account.tax.code.line.template')(line_template_id))
                line.save()
                code_line_ids.append(line.id)

        ordinary = create_tax(Decimal(0))
        ordinary.save()
        supplier = Party(name='Supplier')
        supplier.save()
        payment_term = PaymentTerm(name='Direct')
        payment_term.lines.new(type='remainder')
        payment_term.save()
        historical = Invoice(type='in', party=supplier,
            invoice_date=date(2026, 9, 30), reference='Legacy invoice',
            payment_term=payment_term)
        line = historical.lines.new()
        line.description = 'Legacy service'
        line.account = accounts['expense']
        line.quantity = 1
        line.unit_price = Decimal('8.60')
        line.taxes.append(Tax(taxes[0].id))
        historical.save()
        try:
            historical.click('post')
        except UserWarning as warning:
            _, (key, *_) = warning.args
            Warning.skip(key, True, cfg.context)
            historical.click('post')
        self.assertEqual(historical.state, 'posted')
        move_id = historical.move.id

        basic = Model.get('aeat.rege')(name='Basic group')
        basic.periods.new(type='normal')
        basic.save()
        for language in ('ca', 'es'):
            lang, = Model.get('ir.lang').find([('code', '=', language)])
            lang.active = True
            lang.save()
            lang.click('load_translations')

        for _ in range(2):
            module, = Module.find([('name', '=', 'aeat_rege')])
            module.click('upgrade')
            Wizard('ir.module.activate_upgrade').execute('upgrade')
            for tax in taxes:
                tax.reload()
                self.assertTrue(tax.rege_legacy)
                self.assertIsNone(tax.template)
                self.assertEqual(tax.rate, Decimal(0))
                self.assertEqual(tax.legal_notice, 'Original legacy notice')
            self.assertEqual(taxes[0].end_date, date(2026, 9, 30))
            self.assertEqual(taxes[1].end_date, date(2026, 8, 31))
            self.assertFalse(Template.find([('id', 'in', [t.id for t in templates])]))
            with Transaction().start(cfg.database_name, 0, context=cfg.context):
                self.assertFalse(cfg.pool.get('ir.model.data').search([
                            ('module', '=', 'aeat_rege'),
                            ('model', 'in', ['account.tax.template',
                                'account.tax.code.line.template'])]))
            for id_ in code_line_ids:
                self.assertIsNone(CodeLine(id_).template)
                self.assertIn(CodeLine(id_).tax.id, [t.id for t in taxes])
            historical.reload()
            self.assertEqual(historical.state, 'posted')
            self.assertEqual(historical.total_amount, Decimal('8.60'))
            self.assertEqual(historical.move.id, move_id)
            ordinary.reload()
            self.assertFalse(ordinary.rege_legacy)
            self.assertIsNone(ordinary.end_date)

        for language, label in [('en', 'Basic'), ('ca', 'Bàsic'), ('es', 'Básico')]:
            with Transaction().start(cfg.database_name, cfg.user,
                    context=dict(cfg.context, language=language)):
                if language != 'en':
                    Translation = cfg.pool.get('ir.translation')
                    self.assertEqual(Translation.get_source(
                            'aeat.rege.period,type', 'selection', language, 'Basic'),
                        label, [(t.lang, t.src, t.value, t.fuzzy)
                            for t in Translation.search([
                                ('name', '=', 'aeat.rege.period,type')])])
                group = cfg.pool.get('aeat.rege')(basic.id)
                self.assertEqual(group.periods[0].type, 'normal')
                self.assertIn('(%s)' % label, group.periods[0].rec_name)
                selection = cfg.pool.get('aeat.rege').fields_get(['current_type'])
                self.assertEqual(dict(selection['current_type']['selection'])[
                        'normal'], label)

        # The upgrade rebuilds the Pool; refresh Proteus proxies before editing.
        Model.reset()
        Invoice = Model.get('account.invoice')
        Tax = Model.get('account.tax')
        supplier = Model.get('party.party')(supplier.id)
        payment_term = Model.get('account.invoice.payment_term')(payment_term.id)
        accounts = get_accounts(company)
        for invoice_type in ('in', 'out'):
            invoice = Invoice(type=invoice_type, party=supplier,
                invoice_date=date(2026, 10, 1), payment_term=payment_term)
            line = invoice.lines.new()
            line.description = 'Expired legacy tax'
            line.account = accounts['expense' if invoice_type == 'in' else 'revenue']
            line.quantity = 1
            line.unit_price = Decimal('8.60')
            line.taxes.append(Tax(taxes[0].id))
            invoice.save()
            for action in ('validate_invoice', 'post'):
                with self.assertRaisesRegex(UserError, 'expired on 2026-09-30'):
                    invoice.click(action)
                invoice.reload()
                self.assertEqual(invoice.state, 'draft')
                self.assertFalse(invoice.number)
            invoice.invoice_date = date(2026, 9, 30)
            invoice.save()
            with Transaction().start(cfg.database_name, cfg.user, context=cfg.context):
                cfg.pool.get('account.invoice')(invoice.id)._check_legacy_rege_taxes()
