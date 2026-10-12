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

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        table = cls.__table_handler__(module_name)
        if table.column_exist('rege_cost_base_exclude'):
            table.drop_column('rege_cost_base_exclude')


class Tax(metaclass=PoolMeta):
    __name__ = 'account.tax'

    rege_legacy = fields.Boolean('Legacy REGE Exemption Tax', readonly=True,
        help='Historical REGE zero-rate tax retired on 30 September 2026.')

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        handler = cls.__table_handler__(module_name)
        if handler.column_exist('rege_cost_base_exclude'):
            handler.drop_column('rege_cost_base_exclude')
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
