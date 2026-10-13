from decimal import Decimal
from io import BytesIO

from trytond.i18n import gettext
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction


class TaxesByInvoice(metaclass=PoolMeta):
    __name__ = 'account_reports.taxes_by_invoice'

    @classmethod
    def prepare(cls, data):
        from trytond.modules.html_report.engine import DualRecord

        records, parameters = super().prepare(data)
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        InvoiceTax = pool.get('account.invoice.tax')
        Currency = pool.get('currency.currency')
        Period = pool.get('account.period')
        Tax = pool.get('account.tax')

        domain = [('type', '=', 'line'), ('invoice.move', '!=', None),
            ('invoice.type', '=', 'out' if data['partner_type'] == 'customers' else 'in')]
        if data.get('company'):
            domain.append(('invoice.company', '=', data['company']))
        for name, operator in [('start_date', '>='), ('end_date', '<=')]:
            if data.get(name):
                domain.append(('invoice.move.date', operator, data[name]))
        if not data.get('start_date') and not data.get('end_date'):
            periods = data.get('periods') or [p.id for p in Period.search([
                        ('fiscalyear', '=', data['fiscalyear'])])]
            domain.append(('invoice.move.period', 'in', periods))
        for name, operator in [('parties', 'in'), ('excluded_parties', 'not in')]:
            if data.get(name):
                domain.append(('invoice.party', operator, data[name]))
        if data.get('taxes'):
            domain.append(('taxes', 'in', data['taxes']))
        if data['tax_type'] == 'invoiced':
            domain.append(['OR',
                    [('quantity', '>=', 0), ('unit_price', '>=', 0)],
                    [('quantity', '<=', 0), ('unit_price', '<=', 0)]])
        elif data['tax_type'] == 'refunded':
            domain.append(['OR',
                    [('quantity', '>', 0), ('unit_price', '<', 0)],
                    [('quantity', '<', 0), ('unit_price', '>', 0)]])
        lines = InvoiceLine.search(domain, order=[('invoice', 'ASC'), ('id', 'ASC')])
        invoices = {line.invoice.id: line.invoice for line in lines}
        invoices = {id_: invoice for id_, invoice in invoices.items()
            if invoice._get_rege(advanced=True)}
        if not invoices:
            return records, parameters

        # Replace only automatic VAT and the base report's synthetic
        # non-deductible rows. Manual adjustments and other taxes are retained.
        for key, rows in list(records.items()):
            rows = [row for row in rows
                if row.invoice.raw.id not in invoices or not (
                    (row.raw.id or -1) < 0 or (
                        not row.raw.manual and row.tax
                        and row.tax.raw.tax_kind == 'vat'))]
            if rows:
                records[key] = rows
            else:
                del records[key]
        line_taxes = {id_: cls._rege_line_taxes(invoice)
            for id_, invoice in invoices.items()}
        deductible_taxes = {id_: cls._rege_line_taxes(invoice, deductible=True)
            for id_, invoice in invoices.items()}
        fiscal_groups = {}
        group_id = min([0] + [row.tax.raw.id or 0 for rows in records.values()
                for row in rows if row.tax]) - 1
        row_id = min([0] + [row.raw.id or 0 for rows in records.values()
                for row in rows]) - 1
        details = {}
        for line in lines:
            if line.invoice.id not in invoices:
                continue
            invoice = line.invoice
            for tax_key, value in line_taxes[invoice.id].get(line.id, {}).items():
                tax = value.tax
                if (tax.tax_kind != 'vat'
                        or (data.get('taxes') and tax.id not in data['taxes'])):
                    continue
                base = invoice.currency.round(
                    Decimal(str(line.quantity or 0)) * (line.unit_price or Decimal(0)))
                with Transaction().set_context(date=invoice.currency_date):
                    company_base = Currency.compute(invoice.currency,
                        base, invoice.company.currency)
                    company_amount = Currency.compute(invoice.currency,
                        value.amount, invoice.company.currency)
                    cost_base = Currency.compute(invoice.currency,
                        value.base, invoice.company.currency)
                rate = (line.taxes_deductible_rate if invoice.type == 'in'
                    and line.taxes_deductible_rate is not None else Decimal(1))
                parts = []
                if not value.base and not value.amount and tax.rate:
                    parts.append(('zero', base, value.amount,
                            company_base, company_amount, cost_base))
                elif rate == 0 or rate == 1:
                    parts.append(('deductible' if rate else 'non_deductible',
                            base, value.amount, company_base, company_amount, cost_base))
                else:
                    deducted = deductible_taxes[invoice.id].get(line.id, {}).get(tax_key)
                    deducted_amount = deducted.amount if deducted else Decimal(0)
                    deducted_cost = deducted.base if deducted else Decimal(0)
                    deducted_base = invoice.currency.round(base * rate)
                    with Transaction().set_context(date=invoice.currency_date):
                        deducted_company_base = Currency.compute(invoice.currency,
                            deducted_base, invoice.company.currency)
                        deducted_company_amount = Currency.compute(invoice.currency,
                            deducted_amount, invoice.company.currency)
                        deducted_company_cost = Currency.compute(invoice.currency,
                            deducted_cost, invoice.company.currency)
                    parts.append(('deductible', deducted_base, deducted_amount,
                            deducted_company_base, deducted_company_amount,
                            deducted_company_cost))
                    # Use the remainder so rounding cannot duplicate or lose
                    # commercial bases, fiscal bases or VAT between groups.
                    parts.append(('non_deductible', base - deducted_base,
                            value.amount - deducted_amount,
                            company_base - deducted_company_base,
                            company_amount - deducted_company_amount,
                            cost_base - deducted_company_cost))
                for kind, part_base, amount, c_base, c_amount, c_cost in parts:
                    report_tax = tax
                    if kind != 'deductible':
                        group_key = (kind, tax.rate, invoice.company.id,
                            tax.id if tax.type != 'percentage' else None)
                        if group_key not in fiscal_groups:
                            percentage = (format((tax.rate * 100).normalize(), 'f')
                                if tax.rate is not None else None)
                            if kind == 'zero':
                                label = gettext('aeat_rege.msg_report_zero_cost_tax',
                                    rate=percentage)
                            else:
                                label = gettext('account_reports.msg_not_deductible_tax')
                                if percentage is not None:
                                    label += ' (%s%%)' % percentage
                            existing = next((key for key in records
                                    if isinstance(key, Tax) and (key.id or -1) < 0
                                    and key.name == label and key.rate == tax.rate
                                    and key.company == invoice.company), None)
                            if existing is not None:
                                fiscal_groups[group_key] = existing
                            else:
                                fiscal_groups[group_key] = Tax(group_id, name=label,
                                    rate=tax.rate, type=tax.type, company=invoice.company)
                                group_id -= 1
                        report_tax = fiscal_groups[group_key]
                    fiscal_line = InvoiceTax(row_id, invoice=invoice, tax=report_tax,
                        account=value.account, base=part_base, amount=amount,
                        currency=invoice.currency, company_base=c_base,
                        company_amount=c_amount, company_base_cache=c_base,
                        company_amount_cache=c_amount)
                    row_id -= 1
                    key = (invoice.move.period
                        if data['grouping'] == 'invoice' else report_tax)
                    records.setdefault(key, []).append(DualRecord(fiscal_line))
                    details[(invoice.id, fiscal_line.id, report_tax.id)] = {
                        'cost_base': c_cost, 'deduction_kind': kind,
                        'description': line.description or (
                            line.product.rec_name if line.product else ''),
                        }

        totals = dict.fromkeys(
            ['total_untaxed', 'total_tax', 'total', 'cost_base'], Decimal(0))
        tax_totals = {}
        for key, rows in records.items():
            rows.sort(key=lambda row: (
                row.invoice.raw.invoice_date or row.invoice.move.raw.date,
                row.invoice.raw.id))
            subtotal = dict.fromkeys(totals, Decimal(0))
            for row in rows:
                invoice = row.invoice.raw
                if (invoice.state == 'cancelled' and (not invoice.cancel_move
                        or not isinstance(invoice.cancel_move.origin, Invoice))):
                    continue
                subtotal['total_untaxed'] += row.raw.company_base
                subtotal['total_tax'] += row.raw.company_amount
                subtotal['total'] += row.raw.company_base + row.raw.company_amount
                detail = cls._rege_detail(row, details)
                subtotal['cost_base'] += detail.get('cost_base', Decimal(0))
            tax_totals[key] = subtotal
            for name, value in subtotal.items():
                totals[name] += value
        parameters.update(rege_details=details, totals=totals, tax_totals=tax_totals,
            rege_only=bool(details) and all(cls._rege_detail(row, details)
                for rows in records.values() for row in rows))
        return records, parameters

    @classmethod
    def _rege_line_taxes(cls, invoice, deductible=False):
        """Allocate fiscal taxes using the invoice's rounding policy."""
        with Transaction().set_context(_deductible_rate=None if deductible else 1):
            invoice_taxes = invoice._get_rege_taxes()
            line_taxes = {line.id: line._get_taxes()
                for line in invoice.lines if line.type == 'line'}
        for key, total in invoice_taxes.items():
            values = [taxes[key] for taxes in line_taxes.values() if key in taxes]
            if values:
                values[-1].amount += total.amount - sum(v.amount for v in values)
                values[-1].base += total.base - sum(v.base for v in values)
        return line_taxes

    @staticmethod
    def _rege_detail(line, details):
        return details.get((line.invoice.raw.id, line.raw.id,
                line.tax.raw.id if line.tax else None), {})

    @staticmethod
    def _base_label(parameters):
        return gettext('aeat_rege.msg_report_commercial_base'
            if parameters.get('rege_only') else 'aeat_rege.msg_report_mixed_base')

    @classmethod
    def _tax_label(cls, line, details):
        if not line.tax:
            return ' --- '
        tax = line.tax.raw
        detail = cls._rege_detail(line, details)
        if detail.get('deduction_kind') == 'zero':
            return gettext('aeat_rege.msg_report_zero_cost_tax',
                rate=format((tax.rate * 100).normalize(), 'f'))
        return tax.name

    @classmethod
    def show_detail(cls, data):
        from dominate.tags import table
        from dominate.util import raw
        from lxml import etree
        from trytond.modules.html_report.engine import render

        nodes = super().show_detail(data)
        parameters = data['parameters']
        details = parameters.get('rege_details')
        if not details:
            return nodes
        groups = iter(data['records'].items())
        result = []
        for node in nodes:
            if not isinstance(node, table):
                result.append(node)
                continue
            key, lines = next(groups)
            digits = key.company.currency.digits
            element = etree.HTML(str(node)).find('body/table')
            header = element.find('thead/tr')
            header[6].text = cls._base_label(parameters)
            etree.SubElement(header, 'th').text = gettext('aeat_rege.msg_report_cost_column')
            etree.SubElement(header, 'th').text = gettext('aeat_rege.msg_report_operation')
            rows = element.findall('tr')
            rows[0][0].set('colspan', '13')
            index = 1
            if not parameters['totals_only']:
                for line in lines:
                    row = rows[index]
                    index += 1
                    row[7].text = cls._tax_label(line, details)
                    while len(row) < 11:
                        etree.SubElement(row, 'td')
                    detail = cls._rege_detail(line, details)
                    etree.SubElement(row, 'td', style='text-align: right;').text = (
                        str(render(detail['cost_base'], digits=digits)) if detail else '')
                    etree.SubElement(row, 'td').text = detail.get('description', '')
            if parameters['tax_totals'].get(key):
                etree.SubElement(rows[index], 'td').text = str(render(
                    parameters['tax_totals'][key]['cost_base'], digits=digits))
                etree.SubElement(rows[index], 'td')
                index += 1
            if index < len(rows):
                etree.SubElement(rows[index], 'td').text = str(render(
                    parameters['totals']['cost_base'], digits=digits))
                etree.SubElement(rows[index], 'td')
            result.append(raw(etree.tostring(element, encoding='unicode', method='html')))
        return result


class TaxesByInvoiceXlsx(metaclass=PoolMeta):
    __name__ = 'account_reports.taxes_by_invoice_xlsx'

    @classmethod
    def get_content(cls, ids, data):
        # The base XLSX report calls its concrete Python class. Use the Pool
        # so that the optional REGE preparation also applies to spreadsheets.
        Report = Pool().get('account_reports.taxes_by_invoice', type='report')
        with Transaction().set_context(active_test=False):
            records, parameters = Report.prepare(data)
        if not records:
            parameters['records_found'] = False
            records['no_records'] = ''
        with Transaction().set_context(**cls._xlsx_context()):
            return cls._build_workbook(records, parameters)

    @classmethod
    def _build_workbook(cls, records, parameters):
        content = super()._build_workbook(records, parameters)
        details = parameters.get('rege_details')
        if not details:
            return content
        from openpyxl import load_workbook
        from trytond.modules.account_reports.xlsx import save_workbook
        from trytond.modules.xgettext import _

        Report = Pool().get('account_reports.taxes_by_invoice', type='report')
        workbook = load_workbook(BytesIO(content))
        sheet = workbook.active
        headers = [row[0].row for row in sheet.iter_rows()
            if row[0].value == _('Move Date') and row[10].value == _('Total Invoice')]
        groups = list(records.items())
        for group_index, (header, (key, lines)) in enumerate(zip(headers, groups)):
            digits = key.company.currency.digits
            sheet.cell(header, 7, Report._base_label(parameters))
            sheet.cell(header, 12, gettext('aeat_rege.msg_report_cost_column'))
            sheet.cell(header, 13, gettext('aeat_rege.msg_report_operation'))
            index = header + 2
            if not parameters['totals_only']:
                for line in lines:
                    detail = Report._rege_detail(line, details)
                    sheet.cell(index, 8, Report._tax_label(line, details))
                    if detail:
                        sheet.cell(index, 12, float(detail['cost_base']))
                        sheet.cell(index, 13, detail['description'])
                    index += 1
            if parameters['tax_totals'].get(key):
                sheet.cell(index, 12, float(parameters['tax_totals'][key]['cost_base']))
                index += 1
            if parameters['grouping'] and group_index == len(groups) - 1:
                sheet.cell(index, 12, float(parameters['totals']['cost_base']))
            for row in range(header + 2, index + 1):
                sheet.cell(row, 12).number_format = '0.' + '0' * digits
        return save_workbook(workbook)
