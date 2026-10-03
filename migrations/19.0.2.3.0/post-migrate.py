# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Le type « Activité » passe en heures.

Un type en heures permet, sur une mission facturée à l'heure, la demi-journée et les
heures personnalisées, comptées exactement (un type au jour arrondit à la journée).
L'enregistrement est en noupdate : la mise à jour ne le modifie pas, d'où ce script.
Il vise aussi un type « Activité » créé à défaut de l'enregistrement du module, celui
que portent les missions.

Par SQL : les saisies existantes gardent leurs valeurs calculées (dates, durées), elles
restent des journées entières de missions au jour.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE hr_leave_type SET request_unit = 'hour'
         WHERE request_unit != 'hour' AND requires_allocation = false
           AND (id IN (SELECT res_id FROM ir_model_data
                        WHERE module = 'mission_report' AND name = 'hr_leave_type_activite')
                OR id IN (SELECT DISTINCT holiday_status_id FROM hr_leave WHERE project_id IS NOT NULL))
    """)
