# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models


class HrLeaveReportCalendar(models.Model):
    _inherit = 'hr.leave.report.calendar'

    # Le calendrier colore chaque saisie selon son type : le champ doit être lisible par tous
    # ceux qui ouvrent la vue d'ensemble (Odoo le réserve aux officiers congés, d'où une erreur
    # d'accès pour un simple responsable). Le nom du type figure déjà dans le titre de la saisie.
    holiday_status_id = fields.Many2one(groups='base.group_user')

    @api.depends('employee_id.name', 'leave_id')
    def _compute_name(self):
        """« Camille Exemple · Mission Exemple : 22 jours » pour une mission,
        « Camille Exemple · Congés payés : 2 jours » pour un congé."""
        super()._compute_name()
        for entry in self:
            leave = entry.sudo().leave_id
            if not leave:
                continue
            what = leave.project_id.name if leave.project_id else leave.holiday_status_id.name
            entry.name = "%s · %s : %s" % (entry.employee_id.name, what or '', leave.duration_display or '')
