# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Badge de présence (listes et fiches d'employés, carte d'avatar, Discuss) :
    # hr_holidays le passe à "En congé" dès qu'une saisie est en cours, mission
    # comprise. On ajoute une valeur dédiée plutôt que de renommer celle des
    # congés, qui doit rester "En congé".
    #
    # Le préfixe presence_holiday est volontaire : c'est lui qui déclenche
    # l'icône avion et le "de retour le ..." du composant d'hr_holidays, tous
    # deux corrects pour une mission.
    hr_icon_display = fields.Selection(selection_add=[
        ('presence_holiday_activity', 'En activité'),
    ])

    def _compute_presence_icon(self):
        super()._compute_presence_icon()
        on_leave = self.filtered(
            lambda employee: employee.hr_icon_display in (
                'presence_holiday_absent', 'presence_holiday_present'))
        if not on_leave:
            return
        # Même requête que le _compute_leave_status d'hr_holidays, qui décide de
        # l'affichage du badge. Le critère mission est project_id : entry_type
        # est calculé et non stocké.
        now = fields.Datetime.now()
        current = self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', on_leave.ids),
            ('date_from', '<=', now),
            ('date_to', '>=', now),
            ('state', '=', 'validate'),
        ])
        # Un congé en cours l'emporte : il reste le motif d'absence à afficher.
        on_activity_ids = set(current.filtered('project_id').employee_id.ids)
        on_activity_ids -= set(current.filtered(lambda leave: not leave.project_id).employee_id.ids)
        on_leave.filtered(lambda employee: employee.id in on_activity_ids).update({
            'hr_icon_display': 'presence_holiday_activity',
        })
