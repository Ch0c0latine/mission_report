# -*- coding: utf-8 -*-
"""Plusieurs affaires pour une même mission, chacune sur sa période.

Une affaire qui prolonge une mission (nouvelle commande, même projet) se lie à
la mission par le champ « Missions associées » de la commande. Chaque affaire
peut porter des dates de début et de fin (facultatives). Une mission liée à
plusieurs affaires exige des périodes renseignées qui ne se chevauchent pas :

* les journées validées et les frais refacturés vont sur l'affaire dont la
  période contient leur date (avant la première, sur la première ; après la
  dernière, sur la dernière) ;
* les intervenants de la mission apparaissent sur chaque affaire.
"""
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
        orders |= self.env['sale.order'].sudo().search([('project_id', '=', project.id)])
        return orders.sorted(lambda o: (
            o.mission_date_start or (o.date_order.date() if o.date_order else date.min), o.id))

    def _mission_order_on(self, day):
        """L'affaire de la mission à cette date (confirmée), sinon la plus proche."""
        self.ensure_one()
        orders = self._mission_all_orders().filtered(lambda o: o.state == 'sale')
        if not orders:
            return self.env['sale.order']
        if len(orders) == 1 or not day:
            return orders[-1]
        for order in orders:
            if order._mission_covers(day):
                return order
        dated = orders.filtered('mission_date_start')
        if dated and day < min(dated.mapped('mission_date_start')):
            return dated.sorted('mission_date_start')[0]
        return orders[-1]

    def _mission_current_order(self):
        """L'affaire en cours : celle d'aujourd'hui."""
        self.ensure_one()
        return self._mission_order_on(fields.Date.context_today(self))


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_project_ids = fields.Many2many(
        'project.project', 'sale_order_mission_project_rel', 'order_id', 'project_id',
        string="Missions associées",
        help="Missions (projets) que cette affaire prolonge ou couvre, en plus de celles "
             "de ses lignes. Une mission peut avoir plusieurs affaires, chacune sur sa période.")
    mission_date_start = fields.Date(
        string="Début de l'affaire",
        help="Facultatif. Premier jour couvert par l'affaire : les journées et les frais de la "
             "mission à partir de cette date vont sur elle.")
    mission_date_end = fields.Date(
        string="Fin de l'affaire",
        help="Facultatif. Dernier jour couvert par l'affaire.")

    def _mission_covers(self, day):
        self.ensure_one()
        return (not self.mission_date_start or self.mission_date_start <= day) and \
            (not self.mission_date_end or day <= self.mission_date_end)

    def _mission_projects(self):
        """Toutes les missions liées à ces affaires."""
        Project = self.env['project.project'].sudo()
        projects = self.mission_project_ids.sudo() | self.order_line.project_id.sudo()
        if 'project_id' in self._fields:
            projects |= self.sudo().project_id
        names = [n for n in ('sale_order_id', 'reinvoiced_sale_order_id') if n in Project._fields]
        if names and self.ids:
            projects |= Project.search(['|'] * (len(names) - 1) + [(n, 'in', self.ids) for n in names])
        return projects

    # ------------------------------------------------------------------
    # Lien avec le « Projet » de l'onglet Autres informations
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._mission_link_project()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if 'project_id' in vals or 'mission_project_ids' in vals or 'mission_date_start' in vals \
                or 'mission_date_end' in vals:
            self._mission_link_project()
        return result

    def _mission_link_project(self):
        """Le projet de l'affaire est une de ses missions ; les périodes ne se chevauchent pas."""
        for order in self:
            if 'project_id' in order._fields and order.project_id \
                    and order.project_id not in order.mission_project_ids:
                order.mission_project_ids = [(4, order.project_id.id)]
        self._mission_check_periods()

    def _mission_check_periods(self):
        for order in self:
            for project in order.mission_project_ids.sudo():
                others = project._mission_all_orders().filtered(lambda o: o != order)
                if not others:
                    continue
                group = order | others
                missing = group.filtered(lambda o: not o.mission_date_start or not o.mission_date_end)
                if missing:
                    raise ValidationError(_(
                        "La mission « %(project)s » est déjà liée à l'affaire %(other)s. Renseignez "
                        "les dates de début et de fin de chacune de ses affaires (%(names)s).",
                        project=project.display_name, other=others[0].name,
                        names=", ".join(missing.mapped('name'))))
                ordered = group.sorted('mission_date_start')
                for left, right in zip(ordered, ordered[1:]):
                    if left.mission_date_end >= right.mission_date_start:
                        raise ValidationError(_(
                            "Les périodes des affaires %(left)s et %(right)s de la mission « %(project)s » "
                            "se chevauchent.", left=left.name, right=right.name,
                            project=project.display_name))


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    @api.model
    def _expense_scan_orders_of(self, projects):
        """Les affaires confirmées des missions : chacune ne prend que sa période."""
        orders = self.env['sale.order'].sudo()
        for project in projects.sudo():
            orders |= project._mission_all_orders().filtered(lambda o: o.state == 'sale')
        return orders

    @api.model
    def _expense_scan_projects_of(self, order):
        return super()._expense_scan_projects_of(order) | order.sudo()._mission_projects()

    @api.model
    def _expense_scan_in_period(self, expenses, order):
        """Seuls les frais datés dans la période de l'affaire, quand la mission en a plusieurs."""
        return expenses.filtered(lambda e: e.project_id.sudo()._mission_order_on(e.date) == order)
