# -*- coding: utf-8 -*-
"""Refait le classeur vierge des modèles de compte rendu livrés.

La 19.0.1.2.0 ne distinguait pas un classeur fabriqué par le module d'un
classeur déposé par l'utilisateur : ses modèles livrés gardaient leur premier
classeur, en anglais et à l'ancienne mise en page. Seules les bases passées
par cette version sont concernées ; aucun utilisateur n'avait encore pu y
déposer de classeur.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if version != '19.0.1.2.0':
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in ('mission_report.activity_report_template_internal',
                  'mission_report.activity_report_template_client'):
        template = env.ref(xmlid, raise_if_not_found=False)
        if template:
            template.with_context(mission_report_blank_file=True).write({'file_generated': True})
    env['mission.activity.report.template']._fill_blank_files()
