# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    project_id = fields.Many2one(
        'project.project',
        string='Mission',
        ondelete='restrict',
        help='Projet ou mission associé à la saisie d\'activité.'
    )

    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Congé',
        required=False,
    )

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.holiday_status_id = False

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        if self.holiday_status_id:
            self.project_id = False

    @api.constrains('project_id', 'holiday_status_id')
    def _check_mission_or_leave_exclusivity(self):
        for record in self:
            has_project = bool(record.project_id)
            has_holiday = bool(record.holiday_status_id)
            if (has_project and has_holiday) or (not has_project and not has_holiday):
                raise ValidationError(
                    "Vous devez sélectionner soit une Mission (projet), soit un Congé, mais pas les deux ni aucun des deux."
                )
