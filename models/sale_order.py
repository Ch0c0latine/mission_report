# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_employee_names = fields.Char(
        string="Intervenants",
        compute='_compute_mission_employee_names',
        compute_sudo=True,
        help="Personnes qui ont des saisies sur les missions (projets) de cette commande.",
    )

    mission_invoice_partner_ids = fields.Many2many(
        'res.partner', 'sale_order_mission_invoice_partner_rel', 'order_id', 'partner_id',
        string="Destinataires des factures",
        help="Contacts à qui envoyer les factures de cette affaire. Vide : le client de la facture.",
    )

    @api.depends('order_line', 'project_id')
    def _compute_mission_employee_names(self):
        Leave = self.env['hr.leave']
        for order in self:
            projects = order._mission_projects() if order.id else self.env['project.project']
            names = set()
            if projects:
                names |= set(Leave.search([('project_id', 'in', projects.ids)]).employee_id.mapped('name'))
                names |= set(projects.task_ids.user_ids.mapped('name'))
                names |= set(projects.user_id.mapped('name'))
            order.mission_employee_names = ", ".join(sorted(names)) if names else False
