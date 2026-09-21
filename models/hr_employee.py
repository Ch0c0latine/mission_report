# -*- coding: utf-8 -*-
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Badge de présence (listes et fiches d'employés, carte d'avatar, Discuss) :
    # hr_holidays le passe à "En congé" dès qu'une saisie est en cours, mission
    # comprise. On ajoute une valeur dédiée plutôt que de renommer celle des
    # congés, qui doit rester "En congé".
    #
    # Le préfixe presence_holiday est volontaire : il évite que les composants
    # d'hr_holidays ne retombent sur le cas "présence" par défaut. Le libellé,
    # l'icône et la couleur affichés viennent de static/src/js/presence_status.js.
    hr_icon_display = fields.Selection(selection_add=[
        ('presence_holiday_activity', 'En activité'),
    ])
    activity_date_to = fields.Date(
        "Fin de l'activité en cours",
        compute='_compute_activity_date_to',
        help="Dernier jour de la saisie de mission en cours. Alimente le badge "
             "de présence, qui annonce une fin d'activité et non un retour de congé."
    )

    def _get_current_entries(self):
        """Saisies validées couvrant l'instant présent, pour ces employés.

        Mêmes critères que le _compute_leave_status d'hr_holidays, qui décide de
        l'affichage du badge.
        """
        now = fields.Datetime.now()
        return self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', self.ids),
            ('date_from', '<=', now),
            ('date_to', '>=', now),
            ('state', '=', 'validate'),
        ])

    def _compute_activity_date_to(self):
        dates = {}
        # Le critère mission est project_id : entry_type est calculé et non stocké.
        for leave in self._get_current_entries().filtered('project_id'):
            employee_id = leave.employee_id.id
            known = dates.get(employee_id)
            if leave.request_date_to and (known is None or leave.request_date_to > known):
                dates[employee_id] = leave.request_date_to
        for employee in self:
            employee.activity_date_to = dates.get(employee.id, False)

    def _compute_presence_icon(self):
        super()._compute_presence_icon()
        on_leave = self.filtered(
            lambda employee: employee.hr_icon_display in (
                'presence_holiday_absent', 'presence_holiday_present'))
        if not on_leave:
            return
        current = on_leave._get_current_entries()
        # Un congé en cours l'emporte : il reste le motif d'absence à afficher.
        on_activity_ids = set(current.filtered('project_id').employee_id.ids)
        on_activity_ids -= set(current.filtered(lambda leave: not leave.project_id).employee_id.ids)
        on_leave.filtered(lambda employee: employee.id in on_activity_ids).update({
            'hr_icon_display': 'presence_holiday_activity',
        })


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    # Le badge s'affiche aussi sur les fiches publiques, qui lisent les valeurs
    # de hr.employee.
    activity_date_to = fields.Date(
        "Fin de l'activité en cours", compute='_compute_activity_date_to')

    def _compute_activity_date_to(self):
        self._compute_from_employee('activity_date_to')
