# -*- coding: utf-8 -*-
"""Nouveau volet : l'affaire suivante d'une mission, sur de nouvelles dates.

Un volet est une affaire de la mission qui prend la suite des précédentes. Le
bouton « Nouveau volet » copie l'affaire (client, projet, conditions, lignes)
sur les nouvelles dates : la ligne de journées devient une ligne par mois du
volet, au tarif de l'affaire d'origine, pour les jours ouvrés des intervenants
(jours fériés et congés déjà posés déduits). La description de la prestation et
la phrase sur les frais sont reprises de l'affaire d'origine, la note ne garde
que les conditions ; le devis imprime le titre du volet et le détail par mois.
"""
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz
from babel.dates import format_date as babel_format_date
from dateutil.relativedelta import relativedelta
from lxml import etree, html as lxml_html
from markupsafe import Markup, escape

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import is_html_empty
from odoo.tools.intervals import Intervals
from odoo.tools.misc import format_amount

from .activity_report import INTERNAL, INTERNAL_KEY
from .mission_orders import VOLET_HEADING, VOLET_PLAN_PERIOD
from .public_holiday_wizard import mission_timezone

# Ligne de mois du prévisionnel d'une ancienne note : « octobre 2026 : 22 jours travaillés soit … ».
PLAN_MONTH = re.compile(r'^[^\W\d_]+ \d{4} ?: ?[\d.,]+ ?jours?\b', re.IGNORECASE)
# Fin de l'introduction du prévisionnel, passée à la ligne : « de: ».
PLAN_TAIL = re.compile(r'^de ?:?$', re.IGNORECASE)
NOTE_BLOCKS = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'table', 'blockquote', 'pre'}


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
        tz = mission_timezone(employee.company_id, employee)
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


def _text(value):
    return " ".join((value or "").replace("\xa0", " ").split())


def _note_blocks(note):
    """[(html, texte)] des paragraphes de premier niveau d'une note."""
    try:
        parts = lxml_html.fragments_fromstring(note)
    except (etree.ParserError, ValueError):
        return []
    # Une note entièrement prise dans un seul bloc : ses paragraphes sont à l'intérieur.
    while len(parts) == 1 and not isinstance(parts[0], str) and parts[0].tag == 'div' \
            and any(child.tag in NOTE_BLOCKS for child in parts[0]):
        wrapper = parts[0]
        parts = ([wrapper.text] if wrapper.text else []) + list(wrapper)
    blocks = []
    for part in parts:
        if isinstance(part, str):
            if part.strip():
                blocks.append((str(escape(part)), _text(part)))
            continue
        if not isinstance(part.tag, str):  # commentaire
            continue
        tail, part.tail = part.tail, None
        blocks.append((etree.tostring(part, encoding='unicode', method='html'), _text(part.text_content())))
        if tail and tail.strip():
            blocks.append((str(escape(tail)), _text(tail)))
    return blocks


def split_volet_note(note):
    """(description, frais, conditions) d'une note à l'ancienne, None si elle ne se découpe pas.

    Description : les paragraphes avant « Les prestations seront réalisées »,
    sauf le titre du volet ; frais : ce qui suit, avant « Principe de
    facturation », sauf le prévisionnel mensuel ; conditions : de « Principe de
    facturation » à la fin. Le paragraphe du tarif et le prévisionnel sont
    laissés : le devis les imprime d'après les lignes. Aucun autre texte n'est
    perdu : il va dans la description ou les frais.
    """
    if is_html_empty(note):
        return None
    blocks = _note_blocks(note)
    texts = [text for _html, text in blocks]
    rate = next((i for i, text in enumerate(texts) if text.startswith("Les prestations seront réalisées")), None)
    if rate is None:
        return None
    terms = next((i for i in range(rate + 1, len(texts)) if texts[i].startswith("Principe de facturation")), None)
    if terms is None:
        return None
    description = [i for i in range(rate) if texts[i] and not VOLET_HEADING.search(texts[i])]
    if not description:
        return None
    expenses = [i for i in range(rate + 1, terms) if texts[i] and not (
        VOLET_PLAN_PERIOD.search(texts[i]) or PLAN_MONTH.match(texts[i]) or PLAN_TAIL.match(texts[i]))]
    return (
        "".join(blocks[i][0] for i in description),
        "".join(blocks[i][0] for i in expenses),
        "".join(html for html, _plain in blocks[terms:]),
    )


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_volet_number = fields.Integer(
        string="Volet", copy=False,
        help="Numéro du volet de la mission, imprimé sur le devis avec la période de l'affaire.")
    mission_description = fields.Html(
        string="Description de la prestation",
        help="Imprimée sur le devis sous l'objet de la proposition. Reprise par « Nouveau volet ».")
    mission_expenses_text = fields.Html(
        string="Frais",
        help="La phrase sur les frais, imprimée sur le devis après le prix et le volume prévisionnel. "
             "Reprise par « Nouveau volet ».")

    def _volet_day_lines(self):
        """Lignes de journées de l'affaire (ni frais, ni notes)."""
        return self.order_line.filtered('mission_day_line')

    def _volet_legacy(self):
        """Affaire d'avant les champs de prestation : tout est dans la note."""
        self.ensure_one()
        return is_html_empty(self.mission_description) and is_html_empty(self.mission_expenses_text)

    def action_mission_fill_from_note(self):
        """Reprend d'une note à l'ancienne la description, la phrase sur les frais, le numéro du volet
        et les conditions, pour que le devis s'imprime avec les champs de prestation."""
        done = self.browse()
        for order in self:
            if not order._volet_legacy():
                continue
            parts = split_volet_note(order.note)
            if not parts:
                continue
            description, expenses, terms = parts
            vals = {'mission_description': description, 'mission_expenses_text': expenses, 'note': terms}
            heading = VOLET_HEADING.search(order.note or '')
            if heading and not order.mission_volet_number:
                vals['mission_volet_number'] = int(heading.group(1))
            order.write(vals)
            done |= order
        if not done:
            raise UserError(_(
                "La note n'a pas pu être découpée (ou la prestation est déjà renseignée) : "
                "reprenez la description et les frais à la main."))
        return True

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


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    mission_day_line = fields.Boolean(
        string="Ligne de journées", compute='_compute_mission_day_line',
        help="Prestation comptée en journées : ni frais refacturés, ni section ou note. Les journées "
             "validées des comptes rendus en font la quantité livrée.")
    mission_period_start = fields.Date(
        string="Début de période",
        help="Ligne d'un mois du volet : les journées validées de cette période vont sur elle.")
    mission_period_end = fields.Date(string="Fin de période")

    @api.depends('display_type', 'is_service', 'product_id.can_be_expensed')
    def _compute_mission_day_line(self):
        for line in self:
            line.mission_day_line = not line.display_type and line.is_service \
                and not line.product_id.can_be_expensed

    @api.constrains('mission_period_start', 'mission_period_end')
    def _check_mission_period(self):
        for line in self:
            if line.mission_period_start and line.mission_period_end \
                    and line.mission_period_end < line.mission_period_start:
                raise ValidationError(_("La fin de période de la ligne « %s » précède son début.", line.name))

    def mission_period_label(self):
        """« 01/10/2026 – 31/10/2026 », vide sans période."""
        self.ensure_one()
        if not (self.mission_period_start and self.mission_period_end):
            return ""
        return "%s – %s" % (self.mission_period_start.strftime('%d/%m/%Y'),
                            self.mission_period_end.strftime('%d/%m/%Y'))

    def mission_quantity_label(self):
        """« 22 jours » pour des lignes de journées (leur total), sinon la quantité et son unité."""
        quantity = sum(self.mapped('product_uom_qty'))
        if self and all(self.mapped('mission_day_line')):
            return "%s %s" % (number(quantity), "jour" if quantity < 2 else "jours")
        return ("%s %s" % (number(quantity), self[:1].product_uom_id.name or "")).strip()

    def _mission_lines_on(self, day):
        """Les lignes qui prennent ce jour : celles dont la période le contient, sinon les plus proches.

        Sans période sur aucune ligne : toutes.
        """
        dated = self.filtered(lambda l: l.mission_period_start and l.mission_period_end)
        if not dated:
            return self

        def distance(line):
            if day < line.mission_period_start:
                return (line.mission_period_start - day).days
            return max((day - line.mission_period_end).days, 0)

        nearest = min(distance(line) for line in dated)
        return dated.filtered(lambda l: distance(l) == nearest)

    def _mission_prorata(self, total):
        """[(ligne, part)] : ``total`` réparti au prorata des quantités commandées, le reste sur la dernière."""
        lines = self.sorted(lambda l: (l.sequence, l.id))
        quantity = sum(lines.mapped('product_uom_qty'))
        shares, given = [], 0.0
        for line in lines[:-1]:
            share = round(total * (line.product_uom_qty / quantity if quantity else 1.0 / len(lines)), 2)
            shares.append((line, share))
            given += share
        shares.append((lines[-1], round(total - given, 2)))
        return shares


class MissionVoletWizard(models.TransientModel):
    _name = 'mission.volet.wizard'
    # hr.mixin : voir mission.igd.wizard.
    _inherit = ['hr.mixin']
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
    note_warning = fields.Char(compute='_compute_note_warning')

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

    @api.depends('order_id')
    def _compute_note_warning(self):
        for wizard in self:
            order = wizard.order_id
            wizard.note_warning = bool(order) and order._volet_legacy() and not is_html_empty(order.note) \
                and not split_volet_note(order.note) and _(
                    "La note de l'affaire d'origine n'a pas pu être découpée : elle sera recopiée telle "
                    "quelle (titre et prévisionnel de l'ancien volet compris), et la description de la "
                    "prestation et les frais resteront vides. Reprenez-les dans l'onglet Prestation du "
                    "nouveau volet.") or False

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

    def _volet_number(self):
        """Le plus grand numéro de volet de la mission, plus un.

        Numéros des affaires et titres de leur note, affaires annulées et
        affaires rattachées par leurs seules lignes comprises ; au moins le
        nombre d'affaires.
        """
        project = self.order_id.project_id.sudo()
        orders = self.env['sale.order'].sudo().search([('project_id', '=', project.id)]) \
            | project._mission_all_orders() | self.order_id.sudo()
        numbers = [o.mission_volet_number for o in orders if o.mission_volet_number]
        numbers += [int(found.group(1)) for found in (VOLET_HEADING.search(o.note or '') for o in orders) if found]
        return max(numbers + [len(orders)]) + 1

    def _volet_lines(self):
        """Les lignes du nouveau volet : celles de l'affaire d'origine, la ligne de journées en une par mois.

        Chaque mois prend ses jours ouvrés (répartis au prorata des quantités
        s'il y a plusieurs prestations), au prix de l'affaire d'origine ; les
        frais repartent de zéro.
        """
        order = self.order_id
        months = [(month, days) for month, days in self._months() if days]
        lines = order._get_copiable_order_lines().sorted(lambda l: (l.sequence, l.id))
        groups = defaultdict(lambda: self.env['sale.order.line'])
        for line in lines.filtered('mission_day_line'):
            groups[(line.product_id, line.price_unit)] |= line
        total = sum(line.product_uom_qty for group in groups.values() for line in group)
        commands, done = [], set()
        for line in lines:
            if not line.mission_day_line:
                vals = line.copy_data({'sequence': len(commands) + 1})[0]
                if not line.display_type and line.product_id.can_be_expensed:
                    vals['product_uom_qty'] = 0.0
                commands.append(Command.create(vals))
                continue
            key = (line.product_id, line.price_unit)
            if key in done:
                continue
            done.add(key)
            group = groups[key]
            share = sum(group.mapped('product_uom_qty')) / total if total else 1.0 / len(groups)
            name = line.product_id.with_context(lang=order.partner_id.lang).display_name
            for month, days in months:
                first = max(month, self.date_start)
                last = min(month + relativedelta(months=1, days=-1), self.date_end)
                period = "%s – %s" % (first.strftime('%d/%m/%Y'), last.strftime('%d/%m/%Y'))
                commands.append(Command.create(line.copy_data({
                    'sequence': len(commands) + 1,
                    'name': "%s\n%s" % (name, period),
                    'product_uom_qty': round(days * share, 2),
                    'price_unit': line.price_unit,
                    'mission_period_start': first,
                    'mission_period_end': last,
                })[0]))
        return commands

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
            order.with_context(**{INTERNAL_KEY: INTERNAL}).write({
                'mission_date_start': self.source_date_start, 'mission_date_end': self.source_date_end})
        description, expenses, note = order.mission_description, order.mission_expenses_text, order.note
        if order._volet_legacy():
            # Affaire à l'ancienne : description, frais et conditions sont tirés de sa note.
            parts = split_volet_note(order.note)
            if parts:
                description, expenses, note = parts
        new = order.copy({
            'project_id': order.project_id.id,
            'mission_date_start': self.date_start,
            'mission_date_end': self.date_end,
            'mission_volet_number': self._volet_number(),
            'mission_description': description,
            'mission_expenses_text': expenses,
            'note': note,
            'date_order': fields.Datetime.now(),
            'order_line': self._volet_lines(),
        })
        new.message_post(body=_("Volet créé à partir de %s.", order.name))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': new.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current',
        }
