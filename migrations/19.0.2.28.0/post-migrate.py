# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Intéressements : les associés sont les membres du département « Associé », sans groupe à tenir à la main.

Le département nommé « Associé » (ou « Associés ») reçoit le repère « Associés » : ses membres, et ceux de ses
sous-départements, voient le statut des associés et la colonne d'intéressement associé. Le nom ne sert qu'ici, une
fois : ensuite c'est le repère du département qui compte, à cocher sur la fiche du département.
Le statut des associés (celui qui a des intéressements sur les prestations des collaborateurs, ou qui était réservé au
groupe de la 2.26) n'est plus proposé qu'à eux.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    departments = env['hr.department'].with_context(active_test=False).search(
        ['|', ('name', '=ilike', 'Associé'), ('name', '=ilike', 'Associés')])
    departments.write({'mission_partner': True})
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'mission_commission_rule' AND column_name = 'group_id'""")
    reserved = "OR group_id IS NOT NULL" if cr.fetchone() else ""
    cr.execute("UPDATE mission_commission_rule SET partners_only = TRUE WHERE rate_team > 0 %s" % reserved)
