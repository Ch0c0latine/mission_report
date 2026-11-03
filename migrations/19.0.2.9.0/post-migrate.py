# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""The leave type of the missions is named in English, translated into French.

The module is written in English since 19.0.2.9.0. The record of the type is in noupdate: an
existing database keeps the name "Activité" in its base language, which the code no longer
looks for by itself. The name is set to "Activity", with its French translation.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE hr_leave_type
           SET name = COALESCE(name, '{}'::jsonb) || jsonb_build_object('en_US', 'Activity', 'fr_FR', 'Activité')
         WHERE id IN (SELECT res_id FROM ir_model_data
                       WHERE module = 'mission_report' AND name = 'hr_leave_type_activite'
                         AND model = 'hr.leave.type')
    """)
