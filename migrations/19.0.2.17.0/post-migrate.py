# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Intéressements : les règles de la société (version B) remplacent le statut unique de la 2.16.

Le statut créé par la 2.16 (20 % / 10 % / 5 %) devient « Associé » avec ses taux, et le statut des chargés
d'affaires, apporteurs et cooptations est ajouté. Les fiches gardent leur statut.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Rule = env['mission.commission.rule']
    for company in env['res.company'].search([]):
        rules = Rule.search([('company_id', '=', company.id)], order='sequence, id')
        untouched = rules.filtered(lambda r: not (r.rate_sourcing or r.rate_candidate or r.rate_client or r.rate_team))
        if len(rules) == 1 and untouched:
            first, second = company._default_commission_rules()
            rules.write({key: value for key, value in first.items() if key != 'company_id'})
            Rule.create(second)
