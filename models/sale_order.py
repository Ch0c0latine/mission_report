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
    mission_expense_template_id = fields.Many2one(
        'expense.scan.export.template', string="Modèle Excel des frais",
        help="Tableau des frais refacturés joint au courriel d'envoi des factures "
             "(par exemple le modèle du client). Vide : pas de tableau Excel.",
    )

    @api.depends('order_line', 'mission_project_ids')
    def _compute_mission_employee_names(self):
        Leave = self.env['hr.leave']
        for order in self:
            projects = order._mission_projects() if order.id else self.env['project.project']
            employees = Leave.search([('project_id', 'in', projects.ids)]).employee_id if projects else False
            order.mission_employee_names = ", ".join(sorted(employees.mapped('name'))) if employees else False
