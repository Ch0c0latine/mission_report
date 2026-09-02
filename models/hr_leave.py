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
    available_project_ids = fields.Many2many(
        'project.project',
        compute='_compute_available_project_ids',
        help="Projets ayant au moins une tâche assignée à l'employé de cette saisie."
    )
    entry_type = fields.Selection(
        [('mission', 'Mission'), ('leave', 'Congé')],
        string='Type de saisie',
        compute='_compute_entry_type',
        readonly=False,
        help="Bascule entre une saisie de Mission (par défaut) et une saisie de Congé."
    )

    @api.depends('employee_id')
    def _compute_available_project_ids(self):
        for record in self:
            user = record.employee_id.user_id
            if user:
                tasks = self.env['project.task'].search([('user_ids', 'in', user.id)])
                record.available_project_ids = tasks.project_id
            else:
                record.available_project_ids = self.env['project.project']

    @api.depends('project_id', 'holiday_status_id')
    def _compute_entry_type(self):
        for record in self:
            if record.holiday_status_id and not self._is_activity_leave_type(record.holiday_status_id):
                record.entry_type = 'leave'
            else:
                record.entry_type = 'mission'

    @api.onchange('entry_type')
    def _onchange_entry_type(self):
        if self.entry_type == 'leave':
            self.project_id = False
            if not self.holiday_status_id or self._is_activity_leave_type(self.holiday_status_id):
                self.holiday_status_id = self.env['hr.leave.type'].search([], limit=1)
        else:
            self.holiday_status_id = False
            if not self.project_id:
                self.project_id = self.available_project_ids[:1]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'holiday_status_id' in res:
            res['holiday_status_id'] = False
        return res

    def action_delete_entry(self):
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def _get_default_activity_leave_type(self):
        # This record is normally installed as stable, already-committed data
        # (data/hr_leave_type_data.xml) - creating it lazily inside hr.leave's
        # own create() proved unreliable (Odoo's allocation check behaved
        # inconsistently for a type created in the same transaction as the
        # leave referencing it). The search/create below is only a fallback
        # for databases that installed this module before that data file
        # existed. Never write to an existing type: Odoo forbids changing a
        # leave type's allocation policy once any leave uses it.
        leave_type = self.env.ref('mission_report.hr_leave_type_activite', raise_if_not_found=False)
        if leave_type:
            return leave_type
        leave_type = self.env['hr.leave.type'].with_context(active_test=False).search(
            [('name', '=', 'Activité'), ('requires_allocation', '=', 'no')], limit=1)
        if not leave_type:
            leave_type = self.env['hr.leave.type'].create({
                'name': 'Activité',
                'requires_allocation': 'no',
                'leave_validation_type': 'no_validation',
                'active': False,
            })
        return leave_type

    def _is_activity_leave_type(self, leave_type):
        return bool(leave_type) and leave_type.name == 'Activité'

    @api.model_create_multi
    def create(self, vals_list):
        activity_type = self._get_default_activity_leave_type()
        for vals in vals_list:
            if vals.get('project_id') and not vals.get('holiday_status_id'):
                vals['holiday_status_id'] = activity_type.id
        return super().create(vals_list)

    def write(self, vals):
        # Self-heal records still pointing at a stale/misconfigured Activité type
        # (e.g. created before _get_default_activity_leave_type started avoiding
        # writes to existing types) *before* the real write, so Odoo's own
        # validation logic (which runs on every save, not just when
        # holiday_status_id itself changes) doesn't see the stale value.
        if 'holiday_status_id' not in vals:
            activity_type = self._get_default_activity_leave_type()
            for record in self:
                project_id = vals.get('project_id', record.project_id.id)
                if project_id and record.holiday_status_id != activity_type:
                    super(HrLeave, record).write({'holiday_status_id': activity_type.id})
        return super().write(vals)

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.holiday_status_id = False

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        if self.holiday_status_id and not self._is_activity_leave_type(self.holiday_status_id):
            self.project_id = False

    @api.constrains('project_id', 'holiday_status_id')
    def _check_mission_or_leave_exclusive(self):
        for record in self:
            is_mission = bool(record.project_id)
            is_leave = bool(record.holiday_status_id) and not self._is_activity_leave_type(record.holiday_status_id)
            if is_mission == is_leave:
                raise ValidationError(
                    _("Une saisie doit posséder soit une Mission soit un Congé, mais pas les deux ni aucun des deux.")
                )

    @api.constrains('project_id', 'employee_id')
    def _check_employee_assigned_to_project(self):
        for record in self:
            if not record.project_id or not record.employee_id:
                continue
            user = record.employee_id.user_id
            has_task = user and self.env['project.task'].search_count([
                ('project_id', '=', record.project_id.id),
                ('user_ids', 'in', user.id),
            ])
            if not has_task:
                raise ValidationError(
                    _("%(employee)s n'est assigné(e) à aucune tâche du projet %(project)s.",
                      employee=record.employee_id.name, project=record.project_id.name)
                )
