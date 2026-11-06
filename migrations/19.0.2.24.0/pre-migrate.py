# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Calcul de marge : une fiche par commande.

Les commandes qui avaient plusieurs fiches ne gardent que la plus récente : les autres fiches restent, sans
commande, pour que la contrainte « une fiche par commande » puisse être posée.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE mission_margin m SET order_id = NULL
        WHERE m.order_id IS NOT NULL
          AND m.id <> (SELECT MAX(o.id) FROM mission_margin o WHERE o.order_id = m.order_id)""")
