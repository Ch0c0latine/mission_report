# -*- coding: utf-8 -*-
"""Facturation au jour ou à l'heure : les affaires existantes restent au jour.

Les colonnes de l'unité sont créées ici, remplies « au jour », avant que la mise à jour
ne les crée avec la valeur par défaut : aucune affaire existante ne change de sens,
quelle que soit la société courante.
"""


def _add(cr, table, column):
    cr.execute("ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s varchar" % (table, column))
    cr.execute("UPDATE %s SET %s = 'day' WHERE %s IS NULL" % (table, column, column))


def migrate(cr, version):
    _add(cr, 'res_company', 'mission_billing_unit_default')
    _add(cr, 'sale_order', 'mission_billing_unit')
