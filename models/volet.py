# -*- coding: utf-8 -*-
"""Nouveau volet : l'affaire suivante d'une mission, sur de nouvelles dates.

Un volet est une affaire de la mission qui prend la suite des précédentes. Le
bouton « Nouveau volet » copie l'affaire (client, projet, conditions, lignes) et
en refait les dates, le titre du volet et le prévisionnel mensuel de la note :
jours ouvrés des intervenants sur la période, jours fériés et congés déjà posés
déduits, multipliés par le tarif journalier.
"""
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz
from babel.dates import format_date as babel_format_date
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.intervals import Intervals
from odoo.tools.misc import format_amount

from .mission_orders import _SPACE, VOLET_HEADING

# Bloc du prévisionnel : « Ce volet concerne … » et les lignes de mois qui suivent.
VOLET_PLAN = re.compile(
    r'<div>Ce volet concerne la période du[^<]*</div>'
    r'(?:<div>[^<]*\d{4}\s*:\s*[\d.,]+ jours? travaillés?[^<]*</div>)*')
DAILY_RATE = re.compile(r'(montant journalier de' + _SPACE + r')[\d\s\xa0.,]+?(\s*EUR HT/jour)')


def work_days_by_month(env, employees, start, end):
    """{(année, mois): jours} ouvrés des employés de ``start`` à ``end`` inclus.

    Selon le calendrier de travail de chacun, jours fériés déduits, ainsi que
    les congés posés ou demandés (les saisies de mission, elles, ne comptent pas
    comme absence).
    """
    result = defaultdict(float)
    for employee in employees:
        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        if not calendar:
            continue
        tz = pytz.timezone(employee.tz or calendar.tz or 'UTC')
        start_dt = tz.localize(datetime.combine(start, time.min))
        end_dt = tz.localize(datetime.combine(end, time.max))
        resource = employee.resource_id
        # Hors absences des ressources rattachées à un congé : les congés sont repris plus bas.
        work = calendar._work_intervals_batch(
            start_dt, end_dt, resources=resource, tz=tz,
            domain=[('time_type', '=', 'leave'), ('holiday_id', '=', False)])[resource.id]
        leaves = env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id), ('project_id', '=', False),
            ('state', 'in', ('confirm', 'validate1', 'validate')),
            ('date_from', '<=', end_dt.astimezone(pytz.utc).replace(tzinfo=None)),
            ('date_to', '>=', start_dt.astimezone(pytz.utc).replace(tzinfo=None))])
        cuts = []
        for leave in leaves:
            first = max(start_dt, pytz.utc.localize(leave.date_from).astimezone(tz))
            last = min(end_dt, pytz.utc.localize(leave.date_to).astimezone(tz))
            if first < last:
                cuts.append((first, last, leave))
        hours = defaultdict(float)
        for first, last, _meta in work - Intervals(cuts):
            hours[first.date()] += (last - first).total_seconds() / 3600
        per_day = calendar.hours_per_day or 8.0
        for day, worked in hours.items():
            result[(day.year, day.month)] += round(min(worked / per_day, 1.0) * 2) / 2
    return dict(result)


def number(value):
    """9 ou 10,5 ; milliers séparés par une espace."""
    if abs(value - round(value)) < 0.005:
        return f"{int(round(value)):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").rstrip("0")


def days_text(value):
    return "%s %s" % (number(value), "jour travaillé" if value <= 1 else "jours travaillés")


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _volet_day_lines(self):
        """Lignes de journées de l'affaire (ni frais, ni notes)."""
        return self.order_line.filtered(
            lambda l: not l.display_type and l.is_service and not l.product_id.can_be_expensed)

    def _volet_workers(self):
        """Les intervenants de la mission : ceux qui ont des saisies, sinon ceux d'une tâche."""
        self.ensure_one()
        projects = self._mission_projects()
        Employee = self.env['hr.employee'].sudo()
        if not projects:
            return Employee
        workers = self.env['hr.leave'].sudo().search([('project_id', 'in', projects.ids)]).employee_id
        if not workers:
            workers = Employee.search([('user_id', 'in', projects.sudo().task_ids.user_ids.ids)])
        return workers.filtered('active')

    def action_mission_new_volet(self):
        self.ensure_one()
        if not self.project_id:
            raise UserError(_("Choisissez d'abord le projet de l'affaire (onglet Autres informations)."))
        return {
            'type': 'ir.actions.act_window', 'name': _("Nouveau volet"),
            'res_model': 'mission.volet.wizard', 'context': {'default_order_id': self.id},
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
        }


class MissionVoletWizard(models.TransientModel):
    _name = 'mission.volet.wizard'
    _description = "Nouveau volet d'une affaire"

    order_id = fields.Many2one('sale.order', string="Affaire d'origine", required=True, readonly=True)
    employee_ids = fields.Many2many(
        'hr.employee', 'mission_volet_wizard_employee_rel', 'wizard_id', 'employee_id',
        string="Intervenants",
        help="Les jours ouvrés du volet sont ceux de ces personnes.")
    date_start = fields.Date(string="Début du volet", required=True)
    date_end = fields.Date(string="Fin du volet", required=True)
    needs_source_dates = fields.Boolean(compute='_compute_needs_source_dates')
    source_date_start = fields.Date(string="Début de l'affaire d'origine")
    source_date_end = fields.Date(string="Fin de l'affaire d'origine")
    days = fields.Float(string="Jours ouvrés", compute='_compute_plan')
    plan = fields.Html(string="Prévisionnel", compute='_compute_plan', sanitize=False)
    warning = fields.Char(compute='_compute_plan')

    # -- valeurs par défaut ------------------------------------------------

    @api.model
    def _default_start(self, order):
        """Le lendemain de la fin de la dernière affaire de la mission, sinon le mois suivant."""
        if not order.project_id:
            return False
        ends = []
        for other in order.project_id.sudo()._mission_all_orders():
            period = other._mission_note_period()
            end = other.mission_date_end or (period and period[1])
            if end:
                ends.append(end)
        if ends:
            return max(ends) + timedelta(days=1)
        return (fields.Date.context_today(self) + relativedelta(months=1)).replace(day=1)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['sale.order'].browse(res.get('order_id') or self.env.context.get('default_order_id'))
        if order:
            res['order_id'] = order.id
            res['employee_ids'] = [(6, 0, order._volet_workers().ids)]
            start = self._default_start(order)
            if start:
                res['date_start'] = start
                res['date_end'] = start + relativedelta(months=6) - timedelta(days=1)
            period = order._mission_note_period()
            res['source_date_start'] = order.mission_date_start or (period and period[0]) \
                or (order.date_order and order.date_order.date())
            res['source_date_end'] = order.mission_date_end or (period and period[1]) \
                or (start - timedelta(days=1) if start else False)
        return res

    @api.depends('order_id')
    def _compute_needs_source_dates(self):
        for wizard in self:
            order = wizard.order_id
            period = order._mission_note_period() if order else None
            wizard.needs_source_dates = bool(order) and not period and not (
                order.mission_date_start and order.mission_date_end)

    # -- prévisionnel --------------------------------------------------------

    def _rate(self):
        """Tarif journalier de l'affaire : celui de sa ligne de journées (moyenne pondérée s'il y en a plusieurs)."""
        lines = self.order_id._volet_day_lines()
        quantity = sum(lines.mapped('product_uom_qty'))
        if not lines:
            return 0.0
        if quantity:
            return sum(l.price_unit * l.product_uom_qty for l in lines) / quantity
        return lines[0].price_unit

    def _months(self):
        """[(premier jour du mois, jours ouvrés)] du volet."""
        self.ensure_one()
        if not self.date_start or not self.date_end or self.date_end < self.date_start:
            return []
        by_month = work_days_by_month(self.env, self.employee_ids, self.date_start, self.date_end)
        return [(fields.Date.to_date("%d-%02d-01" % key), value) for key, value in sorted(by_month.items())]

    def _holidays_warning(self):
        """Une année sans aucun jour férié saisi : ils compteraient comme des jours travaillés."""
        self.ensure_one()
        if not self.date_start or not self.date_end or self.date_end < self.date_start:
            return False
        Leaves = self.env['resource.calendar.leaves'].sudo()
        missing = [
            str(year) for year in range(self.date_start.year, self.date_end.year + 1)
            if not Leaves.search_count([
                ('resource_id', '=', False), ('holiday_id', '=', False),
                ('date_from', '>=', '%s-01-01 00:00:00' % year),
                ('date_from', '<=', '%s-12-31 23:59:59' % year)])]
        if not missing:
            return False
        return _("Aucun jour férié n'est saisi pour %s : ils compteraient comme des jours travaillés. "
                 "Générez-les d'abord (Activité › Configuration › Générer les jours fériés français).",
                 ", ".join(missing))

    @api.depends('employee_ids', 'date_start', 'date_end', 'order_id')
    def _compute_plan(self):
        for wizard in self:
            months = wizard._months()
            total = sum(days for _month, days in months)
            wizard.days = total
            wizard.warning = wizard._holidays_warning()
            rate = wizard.order_id and wizard._rate()
            currency = wizard.order_id.currency_id
            rows = Markup().join(
                Markup("<tr><td>%s</td><td class='text-end'>%s</td><td class='text-end'>%s</td></tr>") % (
                    babel_format_date(month, 'LLLL yyyy', locale='fr_FR'), number(days),
                    format_amount(wizard.env, days * rate, currency))
                for month, days in months)
            wizard.plan = Markup(
                "<table class='table table-sm'><thead><tr><th>%s</th><th class='text-end'>%s</th>"
                "<th class='text-end'>%s</th></tr></thead><tbody>%s</tbody>"
                "<tfoot><tr><th>%s</th><th class='text-end'>%s</th><th class='text-end'>%s</th></tr></tfoot></table>"
            ) % (_("Mois"), _("Jours"), _("Montant HT"), rows, _("Total"), number(total),
                 format_amount(wizard.env, total * rate, currency)) if months else False

    # -- création ------------------------------------------------------------

    def _volet_note(self, order, count):
        """La note de l'affaire d'origine, avec le titre et le prévisionnel du nouveau volet."""
        months = self._months()
        total = sum(days for _month, days in months)
        rate = self._rate()
        start, end = (d.strftime('%d/%m/%Y') for d in (self.date_start, self.date_end))
        heading = "Volet %s&nbsp;:&nbsp;période du %s au %s" % (count, start, end)
        plan = "<div>Ce volet concerne la période du %s au %s: %s soit un prévisionnel de:</div>" % (
            start, end, ("%s jours ouvrés" % number(total)) if total > 1 else "%s jour ouvré" % number(total))
        for month, days in months:
            plan += "<div>%s\t: %s soit \t%s EUR</div>" % (
                babel_format_date(month, 'LLLL yyyy', locale='fr_FR'), days_text(days), number(days * rate))
        note = order.note or ''
        if VOLET_HEADING.search(note):
            note = VOLET_HEADING.sub(heading, note, count=1)
        else:
            note = "<h5>%s</h5>" % heading + note
        if VOLET_PLAN.search(note):
            note = VOLET_PLAN.sub(lambda _m: plan, note, count=1)
        else:
            closing = note.find('</h5>')
            at = closing + len('</h5>') if closing >= 0 else 0
            note = note[:at] + plan + note[at:]
        if rate:
            note = DAILY_RATE.sub(lambda m: "%s%s%s" % (m.group(1), number(rate).replace(" ", ""), m.group(2)),
                                  note, count=1)
        return note

    def action_create(self):
        self.ensure_one()
        order = self.order_id
        if self.date_end < self.date_start:
            raise UserError(_("La fin du volet précède son début."))
        if not self.employee_ids:
            raise UserError(_(
                "Choisissez au moins un intervenant : ses jours ouvrés donnent le prévisionnel du volet."))
        if not self.days:
            raise UserError(_(
                "Aucun jour ouvré sur cette période pour les intervenants choisis : vérifiez les dates "
                "et leur calendrier de travail."))
        if self.needs_source_dates:
            if not (self.source_date_start and self.source_date_end):
                raise UserError(_("Renseignez les dates de l'affaire d'origine."))
            order.with_context(mission_no_check=True).write({
                'mission_date_start': self.source_date_start, 'mission_date_end': self.source_date_end})
        count = len(order.project_id.sudo()._mission_all_orders()) + 1
        new = order.copy({
            'project_id': order.project_id.id,
            'mission_date_start': self.date_start,
            'mission_date_end': self.date_end,
            'note': self._volet_note(order, count),
            'date_order': fields.Datetime.now(),
        })
        day_lines = order._volet_day_lines()
        old_total = sum(day_lines.mapped('product_uom_qty'))
        for line in new._volet_day_lines():
            old = day_lines.filtered(lambda l: l.name == line.name and l.product_id == line.product_id)[:1]
            share = (old.product_uom_qty / old_total) if old_total and old else 1.0 / len(day_lines)
            line.product_uom_qty = round(self.days * share, 2)
        for line in new.order_line.filtered(lambda l: not l.display_type and l.product_id.can_be_expensed):
            line.product_uom_qty = 0.0
        new.message_post(body=_("Volet créé à partir de %s.", order.name))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': new.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current',
        }
