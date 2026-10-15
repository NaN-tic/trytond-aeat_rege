from decimal import Decimal

from trytond.i18n import gettext
from trytond.exceptions import UserError, UserWarning
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

from .tax import LEGACY_REGE_END_DATE


class Invoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    cost_price_show = fields.Function(
        fields.Boolean('Display Cost Price?'),
        'on_change_with_cost_price_show')
    rege_fiscal_summary = fields.Function(fields.Text('REGE Fiscal Summary',
            states={'invisible': ~Bool(Eval('cost_price_show'))}),
        'on_change_with_rege_fiscal_summary')

    def _get_rege_taxes(self):
        """Compute automatic taxes before suppressing empty accounting rows."""
        return super()._get_taxes()

    @fields.depends('party', 'invoice_date', 'accounting_date',
        methods=['_get_rege_taxes'])
    def _get_taxes(self):
        taxes = self._get_rege_taxes()
        if self._get_rege(advanced=True):
            taxes = {key: value for key, value in taxes.items()
                if value.base or value.amount}
        return taxes

    def get_rege_fiscal_summary_data(self):
        """VAT information independent of the deductible accounting tax rows."""
        if not self._get_rege(advanced=True):
            return
        deductible_taxes = self._get_rege_taxes()
        with Transaction().set_context(_deductible_rate=Decimal(1)):
            full_taxes = self._get_rege_taxes()
        vat = []
        for key, value in full_taxes.items():
            if getattr(value.tax, 'tax_kind', 'vat') != 'vat':
                continue
            deductible = deductible_taxes.get(key)
            vat.append({
                    'tax': value.tax, 'base': value.base,
                    'amount': value.amount,
                    'deductible': deductible.amount if deductible else Decimal(0),
                    })
        for tax in self.taxes or []:
            if tax.manual and tax.tax and getattr(tax.tax, 'tax_kind', 'vat') == 'vat':
                vat.append({'tax': tax.tax, 'base': tax.base,
                        'amount': tax.amount, 'deductible': tax.amount})
        supported = sum((v['amount'] for v in vat), Decimal(0))
        deductible = sum((v['deductible'] for v in vat), Decimal(0))
        commercial = sum(((getattr(line, 'unit_price', None) or Decimal(0))
                * Decimal(str(getattr(line, 'quantity', None) or 0))
                for line in self.lines or []
                if getattr(line, 'type', None) == 'line'), Decimal(0))
        return {
            'commercial_base': self.currency.round(commercial),
            'cost_base': self.get_rege_received_cost_base(),
            'vat': vat, 'supported': supported, 'deductible': deductible,
            'non_deductible': supported - deductible,
            }

    @fields.depends('lines', 'taxes', 'party', 'company', 'currency', 'type',
        'invoice_date', 'accounting_date', 'total_amount',
        methods=['_get_rege_taxes'])
    def on_change_with_rege_fiscal_summary(self, name=None):
        if not self.currency:
            return ''
        data = self.get_rege_fiscal_summary_data()
        if data is None:
            return ''
        lang = Pool().get('ir.lang').get()
        def money(value):
            return lang.currency(value, self.currency)
        rows = [gettext('aeat_rege.msg_summary_bases',
                commercial=money(data['commercial_base']),
                cost=money(data['cost_base']))]
        for value in data['vat']:
            tax = value['tax']
            label = tax.rec_name
            if tax.type == 'percentage':
                label += ' (%s%%)' % lang.format_number(tax.rate * 100, digits=2)
            rows.append(gettext('aeat_rege.msg_summary_tax',
                    tax=label, base=money(value['base']),
                    amount=money(value['amount'])))
        if self.type == 'in':
            rows.append(gettext('aeat_rege.msg_summary_received',
                    supported=money(data['supported']),
                    deductible=money(data['deductible']),
                    non_deductible=money(data['non_deductible'])))
        rows.append(gettext('aeat_rege.msg_summary_total',
                total=money(self.total_amount or Decimal(0))))
        return '\n'.join(rows)

    @fields.depends('company', 'party', 'invoice_date', 'accounting_date')
    def on_change_with_cost_price_show(self, name=None):
        return bool(self._get_rege(advanced=True))

    def _is_rege_invoice(self):
        return bool(self._get_rege())

    def _get_rege(self, advanced=False):
        if (not self.company or not self.party
                or self.party == self.company.party):
            return

        Date = Pool().get('ir.date')
        date = self.invoice_date or self.accounting_date or Date.today()
        party_rege = self.party.get_rege_by_date(date)
        company_rege = self.company.party.get_rege_by_date(date)
        if party_rege and party_rege == company_rege:
            period = party_rege.get_period_by_date(date)
            if period and (not advanced or period.type == 'advanced'):
                return party_rege

    @fields.depends('company', 'party', 'invoice_date', 'accounting_date',
        'type', 'journal', 'state')
    def _set_rege_journal(self):
        if self.state != 'draft' or self.type != 'out':
            return
        rege = self._get_rege(advanced=True)
        if rege:
            self.journal = rege.invoice_journal
        elif self.journal:
            REGE = Pool().get('aeat.rege')
            if REGE.search([('invoice_journal', '=', self.journal.id)], limit=1):
                Journal = Pool().get('account.journal')
                reserved = [r.invoice_journal.id for r in REGE.search([
                            ('invoice_journal', '!=', None)])]
                journals = Journal.search([
                        ('type', '=', 'revenue'), ('id', 'not in', reserved)],
                    limit=1)
                self.journal = journals[0] if journals else None

    @fields.depends(methods=['_set_rege_journal'])
    def on_change_party(self):
        super().on_change_party()
        self._set_rege_journal()

    @fields.depends(methods=['_set_rege_journal'])
    def on_change_invoice_date(self):
        super().on_change_invoice_date()
        self._set_rege_journal()

    @fields.depends(methods=['_set_rege_journal'])
    def on_change_accounting_date(self):
        super().on_change_accounting_date()
        self._set_rege_journal()

    @fields.depends(methods=['_set_rege_journal'])
    def on_change_company(self):
        super().on_change_company()
        self._set_rege_journal()

    def _rege_sequence(self):
        rege = self._get_rege(advanced=True)
        if self.type != 'out' or not rege:
            return
        if not rege.invoice_journal or self.journal != rege.invoice_journal:
            raise UserError(gettext('aeat_rege.msg_invoice_journal',
                    invoice=self.rec_name, rege=rege.rec_name))
        pool = Pool()
        Date = pool.get('ir.date')
        Sequence = pool.get('account.journal.invoice.sequence')
        date = self.invoice_date or self.accounting_date or Date.today()
        candidates = Sequence.search([
                ('journal', '=', self.journal.id),
                ('company', '=', self.company.id),
                ('fiscalyear.start_date', '<=', date),
                ('fiscalyear.end_date', '>=', date),
                ['OR', ('period', '=', None),
                    [('period.start_date', '<=', date),
                     ('period.end_date', '>=', date)]]],
            order=[('period', 'DESC NULLS LAST')])
        sequence = (getattr(candidates[0], self._sequence_field)
            if candidates else None)
        if not sequence:
            raise UserError(gettext('aeat_rege.msg_invoice_sequence',
                    invoice=self.rec_name, company=self.company.rec_name,
                    journal=self.journal.rec_name, date=str(date)))
        fields_ = ['out_invoice_sequence', 'out_credit_note_sequence']
        shared = bool(Sequence.search([
                ('journal', '!=', self.journal.id),
                ['OR', *[(field, '=', sequence.id) for field in fields_]]],
            limit=1))
        StandardSequence = pool.get('account.fiscalyear.invoice_sequence')
        shared |= bool(StandardSequence.search([
                'OR', *[(field, '=', sequence.id) for field in fields_]],
            limit=1))
        if shared:
            raise UserError(gettext('aeat_rege.msg_shared_sequence',
                    sequence=sequence.rec_name))
        return sequence, date

    def _number_sequence(self, pattern=None):
        return self._rege_sequence() or super()._number_sequence(pattern)

    @classmethod
    def _prepare_rege(cls, invoices):
        for invoice in invoices:
            invoice._check_legacy_rege_taxes()
            if invoice.state == 'draft' and not invoice.number:
                invoice._set_rege_journal()
                invoice.save()
            if invoice._get_rege(advanced=True):
                for line in invoice.lines:
                    if line.type == 'line' and line.cost_price is None:
                        raise UserError(gettext('aeat_rege.msg_missing_cost',
                                invoice=invoice.rec_name))
                    if line.rege_exemption_waived:
                        Tax = Pool().get('account.tax')
                        taxes = Tax.compute([tax for tax in line.taxes
                                if getattr(tax, 'tax_kind', 'vat')
                                not in ('irpf', 'surcharge')],
                            Decimal(1), 1, line.tax_date)
                        if not any(t['amount'] > 0 for t in taxes):
                            raise UserError(gettext('aeat_rege.msg_waiver_tax',
                                    invoice=invoice.rec_name))
                invoice._rege_sequence()

    def _check_legacy_rege_taxes(self):
        if self.state not in ('draft', 'validated'):
            return
        taxes_dates = [(tax, line.tax_date)
            for line in self.lines if line.type == 'line'
            for tax in line.taxes]
        taxes_dates.extend((tax.tax, self.tax_date)
            for tax in self.taxes if tax.tax)
        seen = set()
        while taxes_dates:
            tax, tax_date = taxes_dates.pop()
            if (tax.id, tax_date) in seen:
                continue
            seen.add((tax.id, tax_date))
            taxes_dates.extend((child, tax_date) for child in tax.childs)
            if tax.rege_legacy:
                end_date = min(tax.end_date or LEGACY_REGE_END_DATE,
                    LEGACY_REGE_END_DATE)
                if tax_date > end_date:
                    raise UserError(gettext('aeat_rege.msg_retired_tax',
                            invoice=self.rec_name, tax=tax.rec_name,
                            date=str(end_date)))

    @classmethod
    def validate_invoice(cls, invoices):
        cls._prepare_rege(invoices)
        super().validate_invoice(invoices)

    @classmethod
    def set_number(cls, invoices):
        cls._prepare_rege(invoices)
        super().set_number(invoices)

    def get_rege_received_cost_base(self):
        cost = Decimal(0)
        for line in self.lines or []:
            if getattr(line, 'type', None) != 'line':
                continue
            price = getattr(line, 'cost_price', None)
            cost += ((price or Decimal(0))
                * Decimal(str(getattr(line, 'quantity', None) or 0)))
        if self.currency:
            cost = self.currency.round(cost)
        return cost

    def get_rege_general_base(self):
        amount = sum(((line.rege_general_price
                    if line.rege_general_price is not None
                    else line.unit_price or Decimal(0))
                * Decimal(str(line.quantity or 0))
                for line in self.lines if line.type == 'line'), Decimal(0))
        return self.currency.round(amount)

    def get_rege_legal_notice(self):
        if not self._get_rege(advanced=True):
            return ''
        notices = [gettext('aeat_rege.msg_legal_notice_tax')]
        # On-change calls may include new lines with only partial field values.
        if any(getattr(line, 'rege_exemption_waived', False)
                for line in self.lines
                if getattr(line, 'type', None) == 'line'):
            notices.append(gettext('aeat_rege.msg_legal_notice_waiver'))
        return '\n'.join(notices)

    def get_rege_report_data(self):
        """Return fiscal data shared by standard and customer reports."""
        if not self._get_rege(advanced=True):
            return
        line_notices = []
        for line in self.lines:
            if line.type != 'line':
                continue
            description = line.description or (
                line.product.rec_name if line.product else '')
            if line.rege_exemption_waived:
                line_notices.append((description,
                        gettext('aeat_rege.msg_report_waiver')))
                continue
            taxes = list(line.taxes)
            seen = set()
            while taxes:
                tax = taxes.pop(0)
                taxes.extend(tax.childs)
                notice = tax.legal_notice
                if (not notice
                        and getattr(tax, 'sii_exemption_cause', None) == 'E1'):
                    notice = gettext('aeat_rege.msg_report_exemption')
                if notice and notice not in seen:
                    line_notices.append((description, notice))
                    seen.add(notice)
        return {
            'bases': [
                (gettext('aeat_rege.msg_report_general_base'),
                    self.get_rege_general_base()),
                (gettext('aeat_rege.msg_report_cost_base'),
                    self.get_rege_received_cost_base()),
                ],
            'legal_notice': self.get_rege_legal_notice(),
            'line_notices': line_notices,
            }

    @classmethod
    def post(cls, invoices):
        cls._prepare_rege(invoices)
        Warning = Pool().get('res.user.warning')
        zero_cost_invoices = [invoice for invoice in invoices
            if (invoice.type == 'in' and invoice.cost_price_show
                and invoice.get_rege_received_cost_base() == 0)]
        if zero_cost_invoices:
            warning_key = Warning.format(
                'invoice_in_rege_cost_base_zero', zero_cost_invoices)
            if Warning.check(warning_key):
                invoices_names = ', '.join(
                    invoice.rec_name for invoice in zero_cost_invoices[:5])
                if len(zero_cost_invoices) > 5:
                    invoices_names += '...'
                raise UserWarning(warning_key, gettext(
                    'aeat_rege.msg_invoice_in_rege_cost_base_zero',
                    invoices=invoices_names))
        super().post(invoices)

    @fields.depends('company', 'party', 'accounting_date', 'invoice_date', 'type')
    def _on_change_lines_taxes(self):
        super()._on_change_lines_taxes()
        notices = {gettext('aeat_rege.msg_legal_notice_tax'),
            gettext('aeat_rege.msg_legal_notice_waiver')}
        for tax in self.taxes or []:
            tax.legal_notice = '\n'.join(text for text
                in (tax.legal_notice or '').split('\n') if text not in notices)
        if (getattr(self, 'type', None) != 'out'
                or not self._get_rege(advanced=True)):
            return

        legal_notice = self.get_rege_legal_notice()
        for tax in self.taxes or []:
            tax.legal_notice = '\n'.join(filter(None, [
                tax.legal_notice, legal_notice]))
            break


class SIIInvoice(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    def _set_sii_keys(self):
        super()._set_sii_keys()

        if self._get_rege(advanced=True):
            if self.type == 'out':
                self.sii_issued_key = '06'
            elif self.type == 'in':
                self.sii_received_key = '06'


class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    # Existing lines may retain their standalone visibility when attached to
    # an unsaved invoice. Prefer the current parent invoice's REGE status.
    _cost_price_visible = (Eval('type') == 'line') & If(
        Bool(Eval('_parent_invoice', {})),
        Bool(Eval('_parent_invoice', {}).get('cost_price_show', False)),
        Bool(Eval('cost_price_show')))

    cost_price = fields.Numeric('Cost Price', digits='currency',
        help=('Available only if the "Company" and "Party" '
            'share the same REGE of type "Advanced"; used for '
            'VAT-bearing attributable unit cost, excluding margin and costs '
            'without deductible Spanish VAT. Enter zero explicitly when '
            'justified; a missing cost is not zero.'),
        states={
            'required': _cost_price_visible,
            'invisible': ~_cost_price_visible,
            'readonly': Eval('invoice_state') != 'draft',
            })
    cost_price_show = fields.Function(
        fields.Boolean('Display Cost Price?'),
        'on_change_with_cost_price_show')
    rege_general_price = fields.Numeric('General VAT Unit Value',
        digits='currency',
        help=('Valuation under articles 78 and 79, for reporting and deduction '
            'ratios. Leave empty to use the commercial unit price.'),
        states={
            'invisible': ~_cost_price_visible,
            'readonly': Eval('invoice_state') != 'draft',
            })
    rege_exemption_waived = fields.Boolean('REGE Exemption Waived',
        help=('Waiver under article 163 sexies.Five for this operation. '
            'Select the applicable VAT tax on the line.'),
        states={
            'invisible': ~_cost_price_visible,
            'readonly': Eval('invoice_state') != 'draft',
            })

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        table = cls.__table_handler__(module_name)
        if table.column_exist('rege_cost_base_exclude'):
            # Preserve the effective fiscal cost, including posted lines and
            # excluded lines that had a nonzero stored cost. Do not recalculate
            # invoices, accounting moves or previously submitted SII records.
            sql_table = cls.__table__()
            cursor = Transaction().connection.cursor()
            cursor.execute(*sql_table.update(
                    [sql_table.cost_price], [Decimal(0)],
                    where=sql_table.rege_cost_base_exclude == True))
            table.drop_column('rege_cost_base_exclude')

    @fields.depends('company', 'cost_price', 'invoice', 'invoice_party',
        'invoice_state', 'invoice_type', 'type',
        '_parent_invoice.accounting_date', '_parent_invoice.invoice_date',
        '_parent_invoice.company', '_parent_invoice.party')
    def on_change_with_cost_price_show(self, name=None):
        return bool(self.type == 'line' and self.invoice
            and self.invoice._get_rege(advanced=True))

    @property
    def taxable_lines(self):
        if not self.on_change_with_cost_price_show():
            return super().taxable_lines
        # During invoice on-change calls, new lines may only contain a subset
        # of their fields. Use the same provisional defaults as account_invoice.
        invoice_type = (getattr(self.invoice, 'type', None)
            or getattr(self, 'invoice_type', None))
        rate = Transaction().context.get('_deductible_rate')
        if rate is None:
            rate = getattr(self, 'taxes_deductible_rate', None)
        if invoice_type != 'in' or rate is None:
            rate = Decimal(1)
        unit_price = getattr(self, 'unit_price', None) or Decimal(0)
        quantity = getattr(self, 'quantity', None) or 0
        price = getattr(self, 'cost_price', None) or Decimal(0)
        if Transaction().context.get('_rege_general_base'):
            general_price = getattr(self, 'rege_general_price', None)
            price = general_price if general_price is not None else unit_price
        taxes = getattr(self, 'taxes', None) or []
        vat = [t for t in taxes
            if getattr(t, 'tax_kind', 'vat') not in ('irpf', 'surcharge')]
        other = [t for t in taxes if t not in vat]
        result = []
        if rate:
            result.append((vat, price * rate, quantity, self.tax_date))
        if other:
            result.append((other, unit_price, quantity, self.tax_date))
        return result

    @fields.depends('cost_price',
        'rege_general_price', 'rege_exemption_waived',
        'company', 'invoice', '_parent_invoice.party',
        '_parent_invoice.company', '_parent_invoice.invoice_date',
        '_parent_invoice.accounting_date', '_parent_invoice.type',
        'type', 'quantity', 'taxes', 'unit_price', 'taxes_deductible_rate',
        'invoice_type')
    def _get_taxes(self):
        return super()._get_taxes()

    def _credit(self):
        line = super()._credit()
        line.cost_price = self.cost_price
        line.rege_general_price = self.rege_general_price
        line.rege_exemption_waived = self.rege_exemption_waived
        return line


class InvoiceTax(metaclass=PoolMeta):
    __name__ = 'account.invoice.tax'

    cost_price = fields.Function(fields.Numeric('Cost Price',
            digits='currency'),
        'on_change_with_cost_price')
    cost_price_show = fields.Function(
        fields.Boolean('Display Cost Price?'),
        'on_change_with_cost_price_show')

    def _get_cost_price_lines(self):
        if not self.invoice or not self.tax:
            return []
        return [line for line in self.invoice.lines
            if line.type == 'line' and self.tax in line.taxes]

    @fields.depends('invoice', '_parent_invoice.cost_price_show')
    def on_change_with_cost_price_show(self, name=None):
        if self.invoice:
            return self.invoice.cost_price_show
        return False

    @fields.depends('invoice', 'tax', '_parent_invoice.lines',
        '_parent_invoice.currency')
    def on_change_with_cost_price(self, name=None):
        if not self.invoice or not self.tax or not self.cost_price_show:
            return

        cost_price = Decimal(0)
        for line in self._get_cost_price_lines():
            cost_price += ((line.cost_price or Decimal(0))
                * Decimal(str(line.quantity or 0)))
        if self.invoice.currency:
            return self.invoice.currency.round(cost_price)
        return cost_price
