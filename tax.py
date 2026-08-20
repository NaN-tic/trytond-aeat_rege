# This file is part aeat_rege module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta


class TaxTemplate(metaclass=PoolMeta):
    __name__ = 'account.tax.template'

    rege_cost_base_exclude = fields.Boolean(
        'Exclude from REGE Cost Base by Default',
        help=('Lines using this tax are excluded from the REGE cost base by '
            'default. Review the value on each invoice line: costs for '
            'materials and third-party services must be included.'))

    def _get_tax_value(self, tax=None):
        values = super()._get_tax_value(tax)
        if (not tax or tax.rege_cost_base_exclude
                != self.rege_cost_base_exclude):
            values['rege_cost_base_exclude'] = self.rege_cost_base_exclude
        return values


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    rege_cost_base_exclude = fields.Boolean(
        'Exclude from REGE Cost Base by Default',
        help=('Lines using this tax are excluded from the REGE cost base by '
            'default. Review the value on each invoice line: costs for '
            'materials and third-party services must be included.'))
