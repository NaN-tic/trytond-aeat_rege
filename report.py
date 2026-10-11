# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from trytond.pool import PoolMeta
from trytond.transaction import Transaction


class InvoiceReport(metaclass=PoolMeta):
    __name__ = 'account.invoice'

    @classmethod
    def render(cls, report, report_context):
        content = super().render(report, report_context)
        # Extend the rendered standard invoice instead of maintaining a copy of
        # its template. Custom templates can use get_rege_report_data directly.
        if (report.report != 'account_invoice/invoice.fodt'
                or report.report_content_custom):
            return content
        invoice = report_context['invoice']
        language = (invoice.party.lang.code if invoice.party.lang
            else Transaction().language)
        with Transaction().set_context(language=language):
            summary = invoice.get_rege_report_data()
            if not summary:
                return content
            paragraphs = [
                '%s: %s' % (label, cls.format_currency(
                        amount, invoice.party.lang, invoice.currency))
                for label, amount in summary['bases']]
            paragraphs.extend(summary['legal_notice'].splitlines())
            paragraphs.extend('%s: %s' % (description, notice)
                for description, notice in summary['line_notices'])

        namespaces = {
            'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
            'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
            }
        output = BytesIO()
        with ZipFile(BytesIO(content)) as source, ZipFile(output, 'w') as target:
            for entry in source.infolist():
                data = source.read(entry.filename)
                if entry.filename == 'content.xml':
                    root = etree.fromstring(data)
                    body = root.find('office:body/office:text', namespaces)
                    for text in paragraphs:
                        paragraph = etree.SubElement(
                            body, '{%s}p' % namespaces['text'])
                        paragraph.text = text
                    data = etree.tostring(root, encoding='utf-8',
                        xml_declaration=True)
                target.writestr(entry, data)
        return output.getvalue()
