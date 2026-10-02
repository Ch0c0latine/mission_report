# -*- coding: utf-8 -*-
"""Le bouton « Générer les IGD » quitte les rapports d'activité (il est dans les Dépenses).

Sa vue d'extension, encore en base, serait validée contre le modèle qui n'a
plus la méthode : on la supprime avant la mise à jour.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ir_ui_view WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'mission_report' AND model = 'ir.ui.view'
               AND name = 'mission_activity_report_view_form_igd')
    """)
    cr.execute("""
        DELETE FROM ir_act_server WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'mission_report' AND model = 'ir.actions.server'
               AND name = 'action_mission_report_generate_igd')
    """)
