# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _get_on_leave_ids(self, partner=False):
        # Statut Discuss (avatars de la messagerie et du chatter) : hr_holidays
        # passe en "En congé", avec une icône d'avion, tout utilisateur ayant
        # une saisie en cours, mission comprise. Un salarié en mission travaille :
        # il garde son statut normal. Sert aussi au statut des contacts, via
        # res.partner._get_on_leave_ids.
        on_leave_ids = super()._get_on_leave_ids(partner=partner)
        if not on_leave_ids:
            return on_leave_ids
        now = fields.Datetime.now()
        current = self.env['hr.leave'].sudo().search([
            ('user_id', '!=', False),
            ('date_from', '<=', now),
            ('date_to', '>=', now),
            ('state', '=', 'validate'),
        ])
        users = current._get_mission_only_employees().user_id
        excluded = set(users.partner_id.ids if partner else users.ids)
        return [record_id for record_id in on_leave_ids if record_id not in excluded]
