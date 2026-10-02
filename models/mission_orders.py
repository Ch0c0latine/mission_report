# -*- coding: utf-8 -*-
"""Plusieurs affaires pour une même mission.

Une affaire qui prolonge une mission (nouvelle commande, même projet) se lie à
la mission par le champ « Missions associées » de la commande. Une mission
peut ainsi avoir plusieurs affaires :

* les frais refacturés vont sur la ligne de frais de l'affaire en cours (la
  dernière confirmée) ;
* les journées validées remplissent les lignes de journées des affaires dans
  l'ordre : chaque affaire jusqu'à sa quantité commandée, la dernière avec le
  reste ;
* les intervenants de la mission apparaissent sur chacune.
"""
from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    mission_order_ids = fields.Many2many(
        'sale.order', 'sale_order_mission_project_rel', 'project_id', 'order_id',
        string="Affaires associées",
        help="Affaires liées à cette mission en plus de celle du projet.")

    def _mission_all_orders(self):
        """Toutes les affaires de la mission, de la plus ancienne à la plus récente."""
        self.ensure_one()
        project = self.sudo()
        orders = project.mission_order_ids
        for name in ('sale_order_id', 'reinvoiced_sale_order_id'):
            if name in project._fields and project[name]:
                orders |= project[name]
        orders |= self.env['sale.order.line'].sudo().search([('project_id', '=', project.id)]).order_id
        return orders.sorted(lambda o: (o.date_order or fields.Datetime.now(), o.id))

    def _mission_current_order(self):
        """L'affaire en cours : la dernière confirmée."""
        self.ensure_one()
        confirmed = self._mission_all_orders().filtered(lambda o: o.state == 'sale')
        return confirmed[-1:] if confirmed else self.env['sale.order']


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_project_ids = fields.Many2many(
        'project.project', 'sale_order_mission_project_rel', 'order_id', 'project_id',
        string="Missions associées",
        help="Missions (projets) que cette affaire prolonge ou couvre, en plus de celles "
             "de ses lignes. Une mission peut avoir plusieurs affaires.")

    def _mission_projects(self):
        """Toutes les missions liées à ces affaires."""
        Project = self.env['project.project'].sudo()
        projects = self.mission_project_ids.sudo() | self.order_line.project_id.sudo()
        names = [n for n in ('sale_order_id', 'reinvoiced_sale_order_id') if n in Project._fields]
        if names and self.ids:
            projects |= Project.search(['|'] * (len(names) - 1) + [(n, 'in', self.ids) for n in names])
        return projects


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    @api.model
    def _expense_scan_orders_of(self, projects):
        """Les frais d'une mission vont sur l'affaire en cours."""
        orders = self.env['sale.order'].sudo()
        for project in projects.sudo():
            orders |= project._mission_current_order()
        return orders

    @api.model
    def _expense_scan_projects_of(self, order):
        """Les missions dont cette affaire est l'affaire en cours."""
        projects = super()._expense_scan_projects_of(order) | order.sudo()._mission_projects()
        return projects.filtered(lambda p: p._mission_current_order() == order)
