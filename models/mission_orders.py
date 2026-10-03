# -*- coding: utf-8 -*-
"""Plusieurs affaires pour une même mission, chacune sur sa période.

Une mission (projet) n'a qu'un seul projet par affaire, mais peut avoir
plusieurs affaires qui se succèdent (les « volets »). Chaque affaire porte des
dates de début et de fin (facultatives tant qu'elle est seule). Une mission qui
a plusieurs affaires exige des périodes renseignées qui ne se chevauchent pas :

* les journées validées et les frais refacturés vont sur l'affaire dont la
  période contient leur date (avant la première, sur la première ; après la
  dernière, sur la dernière) ;
* les intervenants de la mission apparaissent sur chaque affaire.

Les dates se lisent aussi dans le titre du volet de la note de l'affaire
(« Volet 2 : période du 01/10/2026 au 31/03/2027 ») quand elles ne sont pas
renseignées.
"""
import re
from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .activity_report import INTERNAL, INTERNAL_KEY

_SPACE = r'(?:&nbsp;|\s|\xa0)*'
# « Volet 2 : période du 01/10/2026 au 31/03/2027 », avec ou sans espaces insécables.
VOLET_HEADING = re.compile(
    r'Volet' + _SPACE + r'(\d+)' + _SPACE + r':' + _SPACE + r'période du' + _SPACE
    + r'(\d\d/\d\d/\d{4})' + _SPACE + r'au' + _SPACE + r'(\d\d/\d\d/\d{4})')
# « Ce volet concerne la période du 01/07/2026 au 30/09/2026 : … » quand il n'y a pas de titre.
VOLET_PLAN_PERIOD = re.compile(
    r'Ce volet concerne la période du' + _SPACE + r'(\d\d/\d\d/\d{4})' + _SPACE + r'au' + _SPACE
    + r'(\d\d/\d\d/\d{4})')


class ProjectProject(models.Model):
    _inherit = 'project.project'

    def _mission_all_orders(self):
        """Toutes les affaires de la mission, de la plus ancienne à la plus récente."""
        self.ensure_one()
        project = self.sudo()
        orders = self.env['sale.order'].sudo().search([('project_id', '=', project.id)])
        for name in ('sale_order_id', 'reinvoiced_sale_order_id'):
            if name in project._fields and project[name]:
                orders |= project[name]
        orders |= self.env['sale.order.line'].sudo().search([('project_id', '=', project.id)]).order_id
        orders = orders.filtered(lambda o: o.state != 'cancel')
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

    mission_date_start = fields.Date(
        string="Début de l'affaire",
        help="Facultatif tant que la mission n'a qu'une affaire. Premier jour couvert par "
             "l'affaire : les journées et les frais de la mission à partir de cette date vont sur elle.")
    mission_date_end = fields.Date(
        string="Fin de l'affaire",
        help="Facultatif tant que la mission n'a qu'une affaire. Dernier jour couvert par l'affaire.")

    @api.constrains('mission_date_start', 'mission_date_end')
    def _check_mission_dates(self):
        for order in self:
            if order.mission_date_start and order.mission_date_end \
                    and order.mission_date_end < order.mission_date_start:
                raise ValidationError(_("La fin de l'affaire %s précède son début.", order.name))

    def _mission_covers(self, day):
        self.ensure_one()
        return (not self.mission_date_start or self.mission_date_start <= day) and \
            (not self.mission_date_end or day <= self.mission_date_end)

    def _mission_projects(self):
        """La mission de ces affaires : le projet de l'affaire et ceux de ses lignes."""
        Project = self.env['project.project'].sudo()
        projects = self.sudo().project_id | self.order_line.project_id.sudo()
        names = [n for n in ('sale_order_id', 'reinvoiced_sale_order_id') if n in Project._fields]
        if names and self.ids:
            projects |= Project.search(['|'] * (len(names) - 1) + [(n, 'in', self.ids) for n in names])
        return projects

    # ------------------------------------------------------------------
    # Périodes
    # ------------------------------------------------------------------

    def _mission_note_period(self):
        """(début, fin) lus dans le titre du volet de la note, sinon None."""
        self.ensure_one()
        note = self.note or ''
        found = VOLET_HEADING.search(note)
        groups = (2, 3)
        if not found:
            found, groups = VOLET_PLAN_PERIOD.search(note), (1, 2)
        if not found:
            return None
        try:
            return tuple(datetime.strptime(found.group(i), '%d/%m/%Y').date() for i in groups)
        except ValueError:
            return None

    def _mission_fill_dates_from_note(self):
        """Renseigne les dates vides d'après le titre du volet de la note."""
        for order in self:
            if order.mission_date_start and order.mission_date_end:
                continue
            period = order._mission_note_period()
            if not period:
                continue
            vals = {}
            if not order.mission_date_start:
                vals['mission_date_start'] = period[0]
            if not order.mission_date_end:
                vals['mission_date_end'] = period[1]
            order.sudo().with_context(**{INTERNAL_KEY: INTERNAL}).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._mission_check_periods()
        return orders

    def write(self, vals):
        result = super().write(vals)
        # Jeton interne : un drapeau de contexte simple pourrait être posé par un client.
        if self.env.context.get(INTERNAL_KEY) != INTERNAL and (
                'project_id' in vals or 'mission_date_start' in vals or 'mission_date_end' in vals):
            self._mission_check_periods()
        return result

    def _mission_check_periods(self):
        """Une mission à plusieurs affaires : périodes renseignées, sans chevauchement."""
        for order in self:
            project = order.project_id.sudo()
            if not project:
                continue
            others = project._mission_all_orders().filtered(lambda o: o != order)
            if not others:
                continue
            group = (order | others).sudo()
            group._mission_fill_dates_from_note()
            missing = group.filtered(lambda o: not o.mission_date_start or not o.mission_date_end)
            if missing:
                raise ValidationError(_(
                    "La mission « %(project)s » a plusieurs affaires. Renseignez les dates de "
                    "début et de fin de chacune (%(names)s).",
                    project=project.display_name, names=", ".join(missing.mapped('name'))))
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
