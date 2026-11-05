# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Calcul de marge : le montant mensuel convenu n'est plus lié aux IGD.

Les colonnes du montant mensuel et de son motif gardent leurs valeurs sous leur nouveau nom.
"""


def _rename(cr, table, old, new):
    cr.execute("""SELECT column_name FROM information_schema.columns
                  WHERE table_name = %s AND column_name IN (%s, %s)""", (table, old, new))
    columns = {row[0] for row in cr.fetchall()}
    if old in columns and new not in columns:
        cr.execute('ALTER TABLE "%s" RENAME COLUMN "%s" TO "%s"' % (table, old, new))


def migrate(cr, version):
    _rename(cr, 'mission_margin', 'igd_monthly_amount', 'fixed_monthly_amount')
    _rename(cr, 'mission_margin', 'igd_monthly_reason', 'fixed_monthly_reason')
