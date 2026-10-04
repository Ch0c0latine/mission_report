# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


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

    def action_mission_edit(self):
        """« Modifier » dans la fenêtre de la saisie : la fiche complète, dans une fenêtre
        (voir leave_edit_action.js), puis le calendrier est relu."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'mission_report.edit_leave',
            'params': {'leave_id': self.sudo().leave_id.id},
        }

    def action_mission_reopen(self):
        """Modifier une saisie approuvée : elle repasse d'abord en attente d'approbation (le
        process d'hr_holidays n'autorise pas de changer les dates d'une saisie approuvée), puis la
        fiche s'ouvre ; une fois modifiée, elle est approuvée de nouveau."""
        self.ensure_one()
        leave = self.env['hr.leave'].browse(self.sudo().leave_id.id)
        if leave.state in ('validate1', 'validate'):
            if not leave.can_back_to_approve:
                raise UserError(_("Votre profil ne permet pas de remettre cette saisie en attente d'approbation."))
            leave.action_back_to_approval()
        return self.action_mission_edit()

    def action_mission_delete(self):
        """Supprime une saisie refusée ou annulée, avec les droits de l'utilisateur."""
        self.ensure_one()
        leave = self.env['hr.leave'].browse(self.sudo().leave_id.id)
        if leave.state not in ('refuse', 'cancel'):
            raise UserError(_("Seule une saisie refusée ou annulée peut être supprimée."))
        leave.unlink()
