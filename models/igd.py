# -*- coding: utf-8 -*-
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
visible des seuls administrateurs ; il n'est imprimé nulle part.
"""
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

IGD_GROUP = 'base.group_system'


class ResCompany(models.Model):
    _inherit = 'res.company'

    igd_lodging_product_id = fields.Many2one(
        'product.product', string="Catégorie IGD logement", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]")
    igd_meal_product_id = fields.Many2one(
        'product.product', string="Catégorie IGD repas", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]")
    igd_real_meal_product_ids = fields.Many2many(
        'product.product', 'res_company_igd_real_meal_rel', 'company_id', 'product_id',
        string="Catégories de repas au réel", groups=IGD_GROUP,
        domain="[('can_be_expensed', '=', True)]",
        help="Un jour qui porte un repas au réel ne reçoit pas d'IGD repas.")


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

    igd_generated = fields.Boolean(readonly=True, copy=False, groups=IGD_GROUP)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    igd_category = fields.Boolean(
        string="Catégorie IGD", compute='_compute_igd_category', search='_search_igd_category')

    @api.model
    def _igd_product_ids(self):
        companies = self.env['res.company'].sudo().search([])
        return (companies.igd_lodging_product_id | companies.igd_meal_product_id).ids

    def _compute_igd_category(self):
        ids = set(self._igd_product_ids())
        for product in self:
            product.igd_category = product.id in ids

    @api.model
    def _search_igd_category(self, operator, value):
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', self._igd_product_ids())]


class MissionIgdWizard(models.TransientModel):
    _name = 'mission.igd.wizard'
    _description = "Génération des IGD du mois"

    employee_ids = fields.Many2many(
        'hr.employee', string="Salariés",
        default=lambda self: self.env.user.employee_id,
        help="Un salarié génère les siennes ; un responsable des dépenses peut choisir son équipe.")
    report_month = fields.Selection(
        selection=lambda self: self.env['mission.activity.report']._selection_report_month(),
        string="Mois", required=True, default=lambda self: str(date.today().month))
    report_year = fields.Selection(
        selection=lambda self: self.env['mission.activity.report']._selection_report_year(),
        string="Année", required=True, default=lambda self: str(date.today().year))

    def action_generate(self):
        """Crée les IGD du mois choisi pour les salariés choisis."""
        self.ensure_one()
        user = self.env.user
        manager = user.has_group('hr_expense.group_hr_expense_team_approver')
        employees = self.employee_ids or user.employee_id
        for employee in employees:
            if employee.user_id != user and not manager:
                raise UserError(_("Vous ne pouvez générer que vos propres IGD."))
        day = date(int(self.report_year), int(self.report_month), 1)
        Report = self.env['mission.activity.report'].sudo()
        created = self.env['hr.expense']
        for employee in employees:
            report = Report.search([('employee_id', '=', employee.id), ('date_from', '=', day)], limit=1) \
                or Report.create({'employee_id': employee.id, 'date_from': day})
            created |= report._igd_generate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense',
            'name': _("IGD créées"),
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', created.ids)],
            'target': 'current',
        }


class MissionActivityReport(models.Model):
    _inherit = 'mission.activity.report'

    def _igd_products(self):
        company = self.employee_id.company_id or self.env.company
        lodging, meal = company.igd_lodging_product_id, company.igd_meal_product_id
        if not lodging and not meal:
            raise UserError(_(
                "Choisissez les catégories IGD logement et repas sur la société "
                "(Paramètres › Sociétés › onglet IGD)."))
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
        """Mois de présence sur la mission jusqu'à celui du rapport, rattrapage compris."""
        start = project.igd_start.replace(day=1) if project.igd_start else date(1900, 1, 1)
        reports = self.search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', start), ('date_from', '<=', self.date_from)])
        return len([r for r in reports if r._igd_presence_days(r._get_report_data(), project)])

    def _igd_generate(self):
        self.ensure_one()
        company, lodging, meal = self._igd_products()
        data = self._get_report_data()
        Expense = self.env['hr.expense']
        created = Expense
        project_ids = {line.get('project_id') for line in data.get('missions', []) if line.get('project_id')}
        for project in self.env['project.project'].browse(sorted(project_ids)):
            if not project.igd_monthly_budget:
                continue
            days = self._igd_presence_days(data, project)
            if not days:
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
            target = project.igd_monthly_budget * self._igd_months_with_presence(project) - before
            left = target - sum(month.mapped('total_amount'))
            taken = {(e.product_id.id, e.date) for e in month}
            real_meals = set(Expense.search([
                ('employee_id', '=', self.employee_id.id),
                ('product_id', 'in', company.igd_real_meal_product_ids.ids),
                ('date', '>=', self.date_from), ('date', '<=', self.date_to),
                ('state', '!=', 'refused')]).mapped('date')) if company.igd_real_meal_product_ids else set()

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
                    created |= expense
                    taken.add((product.id, day))
                    left -= expense.total_amount
        return created
