# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Congé',
        required=False,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Mission',
        required=False,
        ondelete='restrict',
        help='Projet associé à la saisie de rapport de mission.'
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
    def _check_mission_or_leave_exclusive(self):
        for record in self:
            if bool(record.project_id) == bool(record.holiday_status_id):
                raise ValidationError(
                    _("Une saisie doit posséder soit une Mission soit un Congé, mais pas les deux ni aucun des deux.")
                )
