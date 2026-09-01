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
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        related='project_id.partner_id',
        store=True,
        readonly=True,
        help='Client associé à la mission, dérivé du projet.'
    )
    entry_type = fields.Selection(
        [('mission', 'Mission'), ('leave', 'Congé')],
        string='Type de saisie',
        compute='_compute_entry_type',
        inverse='_inverse_entry_type',
        help="Bascule rapide entre une saisie de Mission et une saisie de Congé."
    )
    clear_entry = fields.Boolean(
        string='Tout supprimer',
        store=False,
        help="Vide Mission et Congé : l'enregistrement sera supprimé au clic sur Enregistrer."
    )

    @api.depends('project_id', 'holiday_status_id')
    def _compute_entry_type(self):
        activity_type = self._get_default_activity_leave_type()
        for record in self:
            if record.holiday_status_id and record.holiday_status_id != activity_type:
                record.entry_type = 'leave'
            else:
                record.entry_type = 'mission'

    def _inverse_entry_type(self):
        for record in self:
            if record.entry_type == 'leave':
                record.project_id = False
            else:
                record.holiday_status_id = False

    @api.onchange('clear_entry')
    def _onchange_clear_entry(self):
        if self.clear_entry:
            self.project_id = False
            self.holiday_status_id = False
            self.clear_entry = False

    def write(self, vals):
        vals.pop('clear_entry', None)
        activity_type = self._get_default_activity_leave_type()
        to_delete = self.browse()
        if 'project_id' in vals or 'holiday_status_id' in vals:
            for record in self:
                new_project_id = vals['project_id'] if 'project_id' in vals else record.project_id.id
                new_holiday_id = vals['holiday_status_id'] if 'holiday_status_id' in vals else record.holiday_status_id.id
                is_mission = bool(new_project_id)
                is_leave = bool(new_holiday_id) and new_holiday_id != activity_type.id
                if not is_mission and not is_leave:
                    to_delete |= record
        remaining = self - to_delete
        result = super(HrLeave, remaining).write(vals) if remaining else True
        if to_delete:
            to_delete.unlink()
        return result

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
