# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Congé',
        required=False,
        default=False,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Mission',
        required=False,
        ondelete='restrict',
        help='Projet associé à la saisie de rapport de mission.'
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        related='project_id.partner_id',
        store=True,
        readonly=True,
        help='Client associé à la mission, dérivé du projet.'
    )
    is_leave_entry = fields.Boolean(
        string='Congé',
        compute='_compute_is_leave_entry',
        inverse='_inverse_is_leave_entry',
        help="Décoché : saisie de Mission (par défaut). Coché : saisie de Congé."
    )

    @api.depends('project_id', 'holiday_status_id')
    def _compute_is_leave_entry(self):
        activity_type = self._get_default_activity_leave_type()
        for record in self:
            record.is_leave_entry = bool(record.holiday_status_id) and record.holiday_status_id != activity_type

    def _inverse_is_leave_entry(self):
        activity_type = self._get_default_activity_leave_type()
        for record in self:
            if record.is_leave_entry:
                record.project_id = False
                if not record.holiday_status_id or record.holiday_status_id == activity_type:
                    default_leave_type = self.env['hr.leave.type'].search([], limit=1)
                    record.holiday_status_id = default_leave_type.id if default_leave_type else False
            else:
                record.holiday_status_id = False
                if not record.project_id:
                    default_project = self.env['project.project'].search([], limit=1)
                    record.project_id = default_project.id if default_project else False

    def action_delete_entry(self):
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def _get_default_activity_leave_type(self):
        leave_type = self.env['hr.leave.type'].with_context(active_test=False).search(
            [('name', '=', 'Activité')], limit=1)
        if not leave_type:
            leave_type = self.env['hr.leave.type'].create({
                'name': 'Activité',
                'requires_allocation': 'no',
                'active': False,
            })
        return leave_type

    @api.model_create_multi
    def create(self, vals_list):
        activity_type = self._get_default_activity_leave_type()
        for vals in vals_list:
            if vals.get('project_id') and not vals.get('holiday_status_id'):
                vals['holiday_status_id'] = activity_type.id
        return super().create(vals_list)

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.holiday_status_id = False

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        activity_type = self._get_default_activity_leave_type()
        if self.holiday_status_id and self.holiday_status_id != activity_type:
            self.project_id = False

    @api.constrains('project_id', 'holiday_status_id')
    def _check_mission_or_leave_exclusive(self):
        activity_type = self._get_default_activity_leave_type()
        for record in self:
            is_mission = bool(record.project_id)
            is_leave = bool(record.holiday_status_id) and record.holiday_status_id != activity_type
            if is_mission == is_leave:
                raise ValidationError(
                    _("Une saisie doit posséder soit une Mission soit un Congé, mais pas les deux ni aucun des deux.")
                )
