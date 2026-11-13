# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Intéressements : le statut des associés n'est proposé qu'aux associés.

Les associés sont les membres des départements portant le repère « Associés » (fiche du département) : à cocher
sur le département voulu, aucun nom n'est deviné ici. Le statut des associés (celui qui a des intéressements sur
les prestations des collaborateurs, ou qui était réservé au groupe de la 2.26) n'est plus proposé qu'à eux.
"""


def migrate(cr, version):
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'mission_commission_rule' AND column_name = 'group_id'""")
    reserved = "OR group_id IS NOT NULL" if cr.fetchone() else ""
    cr.execute("UPDATE mission_commission_rule SET partners_only = TRUE WHERE rate_team > 0 %s" % reserved)
