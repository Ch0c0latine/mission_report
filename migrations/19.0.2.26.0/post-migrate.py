# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Intéressements : le statut des associés n'est proposé qu'aux associés.

Le statut qui a des intéressements sur les prestations des collaborateurs (celui des associés) est réservé au groupe
« Associé » ; les autres statuts restent proposés à tous.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref('mission_report.group_mission_partner', raise_if_not_found=False)
    if not group:
        return
    rules = env['mission.commission.rule'].search([('rate_team', '>', 0), ('group_id', '=', False)])
    rules.write({'group_id': group.id})
