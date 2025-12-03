from trytond.model import fields
from trytond.pool import Pool, PoolMeta


class Party(metaclass=PoolMeta):
    __name__ = 'party.party'

    rege_memberships = fields.One2Many(
        'aeat.rege.member', 'party', 'REGE Memberships')

    def get_rege_by_date(self, date=None):
        pool = Pool()
        REGEMember = pool.get('aeat.rege.member')

        membership = REGEMember.get_by_date(self, date)
        if membership:
            return membership.rege
