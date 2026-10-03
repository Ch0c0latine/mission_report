# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Indemnités de grand déplacement (IGD) d'un mois, d'après un montant moyen prévu.

Sur une mission, un montant moyen d'IGD par mois peut être convenu. Pour le
rapport d'activité d'un salarié, les IGD du mois sont créées en notes de frais :

* d'abord l'IGD logement, jour de présence après jour de présence ;
* puis, s'il manque encore, l'IGD repas, sur les jours de présence sans repas
  au réel ;
* jusqu'à approcher au mieux le montant prévu ; un mois en dessous est rattrapé
  les mois suivants, un mois sans présence ne compte pas.

Les montants sont ceux des catégories IGD (barème Urssaf, révisé chaque année
sur la catégorie). Le montant prévu ne figure que sur la fiche de la mission,
visible des seuls administrateurs ; il n'est imprimé nulle part, et le détail
mensuel (part du mois, rattrapage, reste) n'est donné qu'à eux.
"""
from datetime import date

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, float_round
from odoo.tools.misc import format_amount
from odoo.tools.safe_eval import safe_eval

IGD_GROUP = 'base.group_system'


class ResCompany(models.Model):
    _inherit = 'res.company'

    igd_lodging_product_id = fields.Many2one(
        'product.product', string="Catégorie IGD logement", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]")
    igd_meal_product_id = fields.Many2one(
        'product.product', string="Catégorie IGD repas", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]")
    igd_expat_product_id = fields.Many2one(
        'product.product', string="Catégorie forfait expatriation", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]",
        help="Indemnités de long déplacement à l'étranger (forfait expatriation). Comptée "
             "parmi les IGD pour le filtre des dépenses.")
    igd_real_meal_product_ids = fields.Many2many(
        'product.product', 'res_company_igd_real_meal_rel', 'company_id', 'product_id',
        string="Catégories de repas au réel", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]",
        help="Un jour qui porte un repas au réel ne reçoit pas d'IGD repas.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Les catégories d'IGD se règlent dans Paramètres › Activité (réservé aux administrateurs).
    igd_lodging_product_id = fields.Many2one(
        related='company_id.igd_lodging_product_id', readonly=False)
    igd_meal_product_id = fields.Many2one(
        related='company_id.igd_meal_product_id', readonly=False)
    igd_expat_product_id = fields.Many2one(
        related='company_id.igd_expat_product_id', readonly=False)
    igd_real_meal_product_ids = fields.Many2many(
        related='company_id.igd_real_meal_product_ids', readonly=False)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    igd_monthly_budget = fields.Monetary(
        string="IGD moyens prévus par mois", groups=IGD_GROUP,
        currency_field='igd_currency_id',
        help="Montant moyen d'IGD à verser par mois de présence sur cette mission.")
    igd_start = fields.Date(
        string="IGD à partir du", groups=IGD_GROUP,
        help="Premier mois pris en compte pour le rattrapage. Vide : depuis le début.")
    igd_currency_id = fields.Many2one(
        'res.currency', compute='_compute_igd_currency_id', groups=IGD_GROUP)

    def _compute_igd_currency_id(self):
        for project in self:
            project.igd_currency_id = project.company_id.currency_id or self.env.company.currency_id


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # La mission de la dépense. Odoo ne la déclare pas ; expense_scan déclare le même champ
    # (libellé, aide, suppression) : sans attribut ici, sa définition reste la sienne quand il
    # est installé, et la colonne survit à la désinstallation de l'un ou de l'autre.
    project_id = fields.Many2one('project.project')
    igd_generated = fields.Boolean(readonly=True, copy=False, groups=IGD_GROUP)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    igd_category = fields.Boolean(
        string="Catégorie IGD", compute='_compute_igd_category', search='_search_igd_category')

    @api.model
    def _igd_product_ids(self):
        companies = self.env['res.company'].sudo().search([])
        return (companies.igd_lodging_product_id | companies.igd_meal_product_id
                | companies.igd_expat_product_id).ids

    def _compute_igd_category(self):
        ids = set(self._igd_product_ids())
        for product in self:
            product.igd_category = product.id in ids

    @api.model
    def _search_igd_category(self, operator, value):
        """Booléen cherché par '=', '!=', 'in' ou 'not in' : Odoo 19 réécrit « = True » en 'in'."""
        if operator not in ('=', '!=', 'in', 'not in'):
            raise NotImplementedError(operator)
        values = {bool(v) for v in (value if isinstance(value, (list, tuple, set)) else [value])}
        wanted = values if operator in ('=', 'in') else {True, False} - values
        if wanted == {True, False}:
            return [(1, '=', 1)]
        if not wanted:
            return [(0, '=', 1)]
        return [('id', 'in' if True in wanted else 'not in', self._igd_product_ids())]


class MissionIgdWizard(models.TransientModel):
    _name = 'mission.igd.wizard'
    # hr.mixin : sans lui, un salarié sans droit RH ne peut pas poser un many2many vers hr.employee.
    _inherit = ['hr.mixin']
    _description = "Génération des IGD du mois"

    state = fields.Selection([('choose', "Choix"), ('done', "Résultat")], default='choose')
    employee_ids = fields.Many2many(
        'hr.employee', string="Salariés",
        default=lambda self: self.env.user.employee_id,
        help="Un salarié génère les siennes ; un responsable des dépenses peut choisir son équipe.")
    report_month = fields.Selection(
        selection=lambda self: self.env['mission.activity.report']._selection_report_month(),
        string="Mois", required=True, default=lambda self: str(fields.Date.context_today(self).month))
    report_year = fields.Selection(
        selection=lambda self: self.env['mission.activity.report']._selection_report_year(),
        string="Année", required=True, default=lambda self: str(fields.Date.context_today(self).year))
    result = fields.Html(readonly=True, sanitize=False)
    created_expense_ids = fields.Many2many(
        'hr.expense', 'mission_igd_wizard_expense_rel', 'wizard_id', 'expense_id')
    missing_employee_ids = fields.Many2many(
        'hr.employee', 'mission_igd_wizard_missing_rel', 'wizard_id', 'employee_id')

    def _igd_allowed_employees(self, employees):
        """Parmi ces salariés, ceux pour qui l'utilisateur peut générer des IGD.

        Les responsables des dépenses gardent tout ; un approbateur d'équipe est
        limité au domaine de la règle d'Odoo sur les dépenses (ir_rule_hr_expense_approver) :
        lui-même, ses subordonnés, les salariés de ses départements et ceux dont il est
        l'approbateur des dépenses ; les autres ne génèrent que les leurs.
        """
        user = self.env.user
        if user.has_group('hr_expense.group_hr_expense_user') or user.has_group(IGD_GROUP):
            return employees
        # sudo : un salarié ne lit pas toutes les fiches ; la liste est celle de la règle ci-dessous.
        Employee = self.env['hr.employee'].sudo()
        own = Employee.search([('id', 'in', employees.ids), ('user_id', '=', user.id)])
        if not user.has_group('hr_expense.group_hr_expense_team_approver'):
            return own
        return own | Employee.search([
            ('id', 'in', employees.ids),
            '|', '|',
            ('id', 'child_of', user.employee_ids.ids),
            ('department_id.manager_id.user_id', '=', user.id),
            ('expense_manager_id', '=', user.id),
        ])

    def action_generate(self):
        """Crée les IGD du mois choisi pour les salariés choisis et en rend compte."""
        self.ensure_one()
        employees = self.employee_ids or self.env.user.employee_id
        refused = employees - self._igd_allowed_employees(employees)
        if refused:
            raise UserError(_(
                "Vous ne pouvez générer des IGD que pour vous-même, vos subordonnés, les salariés "
                "de vos départements ou ceux dont vous approuvez les dépenses. Non autorisé : %s.",
                ", ".join(refused.sudo().mapped('name'))))
        day = date(int(self.report_year), int(self.report_month), 1)
        Report = self.env['mission.activity.report'].sudo()
        created = self.env['hr.expense']
        missing = self.env['hr.employee']
        lines = []
        for employee in employees:
            report = Report.search([('employee_id', '=', employee.id), ('date_from', '=', day)], limit=1) \
                or Report.create({'employee_id': employee.id, 'date_from': day})
            notes, summary = [], []
            created |= report._igd_generate(notes, summary)
            lines.extend(self._summary_line(employee, item) for item in summary)
            for kind, text in notes:
                lines.append(Markup("<b>%s</b> : %s") % (employee.name, text))
                if kind == 'entries':
                    missing |= employee
        if not lines:
            lines.append(escape(_("Aucune mission n'a d'IGD moyens prévus par mois.")))
        title = _("IGD créées") if created else _("Aucune IGD générée")
        body = Markup("<h4>%s</h4>%s") % (title, Markup().join(Markup("<p>%s</p>") % line for line in lines))
        if missing:
            body += Markup("<p>%s</p>") % _(
                "Saisissez des journées travaillées sur une mission pour laquelle les IGD sont prévues.")
        self.write({
            'state': 'done', 'result': body,
            'created_expense_ids': [(6, 0, created.ids)],
            'missing_employee_ids': [(6, 0, missing.ids)],
        })
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
            'name': _("Générer les IGD"),
        }

    def _summary_line(self, employee, item):
        """Ce qui est créé pour un salarié sur une mission ; le détail du montant prévu
        n'est donné qu'aux administrateurs."""
        money = lambda amount: format_amount(self.env, amount, item['currency'])  # noqa: E731
        text = _("%(employee)s, %(project)s : %(lodging)s IGD logement et %(meals)s IGD repas "
                 "créés pour un total de %(total)s d'IGD dans le mois",
                 employee=employee.name, project=item['project'].name, lodging=item['lodging'],
                 meals=item['meals'], total=money(item['total']))
        if not self.env.user.has_group(IGD_GROUP):
            return escape(text + ".")
        text += _(" : %s pour ce mois.", money(item['month']))
        if not float_is_zero(item['catchup'], precision_digits=2):
            text += " " + _("Rattrapage de %s des mois précédents.", money(item['catchup']))
        if not float_is_zero(item['surplus'], precision_digits=2):
            text += " " + _("Excédent de %s des mois précédents déduit.", money(item['surplus']))
        if not float_is_zero(item['left'], precision_digits=2):
            text += " " + _("Reste %s d'IGD à répartir sur les saisies suivantes.", money(item['left']))
        return escape(text)

    def action_open_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense',
            'name': _("IGD créées"),
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', self.created_expense_ids.ids)],
            'target': 'current',
        }

    def action_open_entries(self):
        """La saisie des temps du salarié, en vue mensuelle sur le mois visé."""
        self.ensure_one()
        employee = self.missing_employee_ids[:1] or self.employee_ids[:1] or self.env.user.employee_id
        day = date(int(self.report_year), int(self.report_month), 1)
        Actions = self.env['ir.actions.actions']
        own = employee.user_id == self.env.user
        action = Actions._for_xml_id('hr_holidays.hr_leave_action_new_request' if own
                                     else 'hr_holidays.hr_leave_action_action_approve_department')
        context = safe_eval(action.get('context') or '{}', {'uid': self.env.uid})
        for name in ('search_default_year', 'search_default_current_year'):
            context.pop(name, None)
        context.update({'initial_date': "%s 00:00:00" % day, 'mission_scale': 'month'})
        if not own:
            context['search_default_employee_id'] = employee.id
            views = action.get('views') or []
            action['views'] = [v for v in views if v[1] == 'calendar'] + [v for v in views if v[1] != 'calendar']
        action['context'] = context
        return action


class MissionActivityReport(models.Model):
    _inherit = 'mission.activity.report'

    def _igd_products(self):
        company = self.employee_id.company_id or self.env.company
        lodging, meal = company.igd_lodging_product_id, company.igd_meal_product_id
        if not lodging and not meal:
            raise UserError(_(
                "Choisissez les catégories IGD logement et repas sur la société "
                "(Paramètres › Activité)."))
        return company, lodging, meal

    def _igd_presence_days(self, data, project):
        """Jours du mois où le salarié est sur cette mission."""
        days = []
        for line in data.get('missions', []):
            if line.get('project_id') != project.id:
                continue
            for day, value in zip(data.get('days', []), line.get('values', [])):
                if value:
                    days.append(fields.Date.to_date(day['date']))
        return sorted(set(days))

    def _igd_months_with_presence(self, project):
        """Mois à compter jusqu'à celui du rapport : celui-ci, et les mois précédents où il y
        avait de la présence sur la mission et déjà des IGD saisies.

        Un mois sans aucune IGD n'est pas à rattraper : le rattrapage ne reprend que
        ce qu'un mois commencé a laissé en dessous du montant prévu. Le rapport d'un mois
        sans rapport enregistré est calculé à la volée, sans être créé.
        """
        last = self.date_from.replace(day=1)
        first = project.igd_start.replace(day=1) if project.igd_start else date(1900, 1, 1)
        recorded = self.env['hr.expense'].sudo().search([
            ('employee_id', '=', self.employee_id.id), ('project_id', '=', project.id),
            ('product_id', 'in', self.env['product.product']._igd_product_ids()),
            ('state', '!=', 'refused'), ('date', '>=', first), ('date', '<', last)])
        months = sorted({day.replace(day=1) for day in recorded.mapped('date')} | {last})
        count = 0
        for month in months:
            if month == last:
                report = self
            else:
                report = self.search([('employee_id', '=', self.employee_id.id), ('date_from', '=', month)],
                                     limit=1) or self.new({'employee_id': self.employee_id.id, 'date_from': month})
            if report._igd_presence_days(report._get_report_data(), project):
                count += 1
        return count

    def _igd_generate(self, notes=None, summary=None):
        """Crée les IGD du mois.

        ``notes`` reçoit les raisons de ce qui n'est pas créé, sous la forme
        (nature, texte) ; la nature « entries » signale des journées à saisir.
        ``summary`` reçoit, par mission, ce qui a été créé et la répartition du montant.
        """
        self.ensure_one()
        notes = [] if notes is None else notes
        summary = [] if summary is None else summary
        company, lodging, meal = self._igd_products()
        data = self._get_report_data()
        Expense = self.env['hr.expense']
        created = Expense
        project_ids = {line.get('project_id') for line in data.get('missions', []) if line.get('project_id')}
        if not project_ids:
            notes.append(('entries', _("aucune journée de mission saisie ce mois-ci.")))
        for project in self.env['project.project'].browse(sorted(project_ids)):
            if not project.igd_monthly_budget:
                continue
            days = self._igd_presence_days(data, project)
            if not days:
                notes.append(('entries', _("aucune journée de présence sur « %s » ce mois-ci.", project.name)))
                continue  # mois complet d'absence : pas d'IGD
            igd_products = (lodging | meal).ids
            base = [('employee_id', '=', self.employee_id.id), ('project_id', '=', project.id),
                    ('product_id', 'in', igd_products), ('state', '!=', 'refused')]
            # Les IGD créées ici et encore en brouillon sont refaites.
            Expense.search(base + [('date', '>=', self.date_from), ('date', '<=', self.date_to),
                                   ('igd_generated', '=', True), ('state', '=', 'draft')]).unlink()
            since = [('date', '>=', project.igd_start.replace(day=1))] if project.igd_start else []
            before = sum(Expense.search(base + since + [('date', '<', self.date_from)]).mapped('total_amount'))
            month = Expense.search(base + [('date', '>=', self.date_from), ('date', '<=', self.date_to)])
            months = self._igd_months_with_presence(project)
            target = project.igd_monthly_budget * months - before
            left = target - sum(month.mapped('total_amount'))
            if float_compare(left, 0.0, precision_digits=2) <= 0:
                notes.append(('info', _("le montant prévu pour « %s » est déjà atteint.", project.name)))
            taken = {(e.product_id.id, e.date) for e in month}
            real_meals = set(Expense.search([
                ('employee_id', '=', self.employee_id.id),
                ('product_id', 'in', company.igd_real_meal_product_ids.ids),
                ('date', '>=', self.date_from), ('date', '<=', self.date_to),
                ('state', '!=', 'refused')]).mapped('date')) if company.igd_real_meal_product_ids else set()

            made = Expense
            for product, allowed in ((lodging, lambda d: True), (meal, lambda d: d not in real_meals)):
                if not product:
                    continue
                amount = product.standard_price
                if not amount:
                    continue
                for day in days:
                    # Approcher au mieux : une IGD de plus tant qu'il reste au moins la moitié de son montant.
                    if float_compare(left, amount / 2, precision_digits=2) < 0:
                        break
                    if (product.id, day) in taken or not allowed(day):
                        continue
                    expense = Expense.create({
                        'name': product.name,
                        'employee_id': self.employee_id.id,
                        'product_id': product.id,
                        'date': day,
                        'quantity': 1,
                        'project_id': project.id,
                        'company_id': (self.employee_id.company_id or company).id,
                        'igd_generated': True,
                    })
                    made |= expense
                    taken.add((product.id, day))
                    left -= expense.total_amount
            created |= made
            if made:
                total = sum(made.mapped('total_amount'))
                month_total = total + sum(month.mapped('total_amount'))
                budget = project.igd_monthly_budget
                # Rattrapage : ce qui dépasse le mois, dans la limite de ce qui manquait avant lui.
                gap = max(budget * (months - 1) - before, 0.0)
                catchup = min(max(month_total - budget, 0.0), gap)
                # Excédent : ce qui a été versé en trop avant ce mois, retranché de celui-ci.
                surplus = max(before - budget * (months - 1), 0.0)
                summary.append({
                    'project': project,
                    'currency': project.igd_currency_id,
                    'lodging': len(made.filtered(lambda e: e.product_id == lodging)),
                    'meals': len(made.filtered(lambda e: e.product_id == meal)),
                    'total': total,
                    'month': month_total - catchup,
                    'catchup': catchup,
                    'surplus': surplus,
                    'left': max(float_round(left, precision_digits=2), 0.0),
                })
        return created
