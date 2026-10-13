# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta


class REGEReportMixin:

    @classmethod
    def show_rege_summary(cls, record):
        from dominate.tags import div, p
        from trytond.modules.html_report.engine import render as html_render

        container = div(cls='rege-summary')
        summary = record.raw.get_rege_report_data()
        if not summary:
            return container
        with container:
            for label, amount in summary['bases']:
                p(label, ': ', html_render(amount,
                        digits=record.currency.raw.digits))
            for notice in summary['legal_notice'].splitlines():
                p(notice)
            for description, notice in summary['line_notices']:
                p(description, ': ', notice, cls='rege-line-tax-notice')
        return container


class InvoiceReport(REGEReportMixin, metaclass=PoolMeta):
    __name__ = 'account.invoice'

    @classmethod
    def last_footer(cls, action, data, records):
        footer = super().last_footer(action, data, records)
        record, = records
        if record.raw._get_rege(advanced=True):
            for section in footer.children:
                if getattr(section, 'attributes', {}).get('id') == 'last-footer':
                    section.add(cls.show_rege_summary(record))
                    break
        return footer
