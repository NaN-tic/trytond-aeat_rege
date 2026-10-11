# This file is part aeat_rege module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from datetime import date

from sql import Null
from sql.conditionals import Case

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction


LEGACY_REGE_END_DATE = date(2026, 9, 30)
LEGACY_REGE_TEMPLATES = ('iva_ex_rege_purchase', 'iva_ex_rege_sale')


class TaxTemplate(metaclass=PoolMeta):
    __name__ = 'account.tax.template'

    rege_cost_base_exclude = fields.Boolean(
        'Exclude from REGE Cost Base by Default',
        help=('Lines using this tax are excluded from the REGE cost base by '
            'default. Review the value on each invoice line: costs for '
            'VAT-bearing materials and third-party services must be included.'))

    def _get_tax_value(self, tax=None):
        values = super()._get_tax_value(tax)
        if (not tax or tax.rege_cost_base_exclude
                != self.rege_cost_base_exclude):
            values['rege_cost_base_exclude'] = self.rege_cost_base_exclude
        return values


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    rege_legacy = fields.Boolean('Legacy REGE Exemption Tax', readonly=True,
        help='Historical REGE zero-rate tax retired on 30 September 2026.')
    rege_cost_base_exclude = fields.Boolean(
        'Exclude from REGE Cost Base by Default',
        help=('Lines using this tax are excluded from the REGE cost base by '
            'default. Review the value on each invoice line: costs for '
            'VAT-bearing materials and third-party services must be included.'))

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        # Detach business taxes before the XML importer removes the obsolete
        # templates. Keep their rates, notices and historical tax-code links.
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        table = cls.__table__()
        data = ModelData.__table__()
        templates = data.select(data.db_id, where=(
                (data.module == 'aeat_rege')
                & (data.model == 'account.tax.template')
                & data.fs_id.in_(LEGACY_REGE_TEMPLATES)))
        cursor = Transaction().connection.cursor()
        cursor.execute(*table.update(
                [table.template, table.rege_legacy, table.end_date],
                [Null, True, Case((table.end_date < LEGACY_REGE_END_DATE,
                            table.end_date), else_=LEGACY_REGE_END_DATE)],
                where=table.template.in_(templates)))
