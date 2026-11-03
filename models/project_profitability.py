# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Profitability of a mission, in the profitability panel of its project.

Odoo's panel adds up what is invoiced (revenues) and what is billed (vendor bills, expenses,
timesheets). The days of a mission are not timesheets: they come from the validated monthly
reports. Three lines are added to the costs of the panel, for the people allowed to see them:

* the days validated on the mission, at the daily cost of each person: the wage of their HR
  contract times a coefficient (employer charges), divided by the working days of the month
  (the working hours for a mission billed per hour);
* the IGD generated for the mission;
* the expenses of the mission marked "not re-invoiced" (with the receipt scanner).

Expenses already counted by Odoo, through the analytic account of the project, are not counted
twice. The revenues are Odoo's own: the delivered days of the order lines feed the amount to
invoice, so the margin follows the validation of the reports.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models

from .work_time import hours_by_day, work_intervals

#: Expense states that are a cost paid, and a cost to come.
BILLED_STATES = ('posted', 'in_payment', 'paid')
TO_BILL_STATES = ('submitted', 'approved')


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_cost_coefficient = fields.Float(
        string="Wage coefficient", default=1.0, digits=(16, 2),
        help="Multiplied by the gross monthly wage of the HR contract to give the cost of an employee for "
             "the company: 1.45 adds employer charges of 45 %. The cost of a day is that cost divided by "
             "the working days of the month.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_cost_coefficient = fields.Float(related='company_id.mission_cost_coefficient', readonly=False)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    def _mission_show_costs(self):
        """The wages and the allowances are for the managers of the project and of the employees."""
        user = self.env.user
        return user.has_group('project.group_project_manager') or user.has_group('hr.group_hr_manager')

    def _get_profitability_labels(self):
        return {
            **super()._get_profitability_labels(),
            'mission_salaries': _("Mission days (wages)"),
            'mission_igd': _("Long-distance allowances (IGD)"),
            'mission_expenses': _("Expenses not re-invoiced"),
        }

    def _get_profitability_sequence_per_invoice_type(self):
        return {
            **super()._get_profitability_sequence_per_invoice_type(),
            'mission_salaries': 11,
            'mission_igd': 14,
            'mission_expenses': 15,
        }

    def _get_profitability_items(self, with_action=True):
        data = super()._get_profitability_items(with_action)
        if not self._mission_show_costs():
            return data
        sequences = self._get_profitability_sequence_per_invoice_type()
        for section, (billed, to_bill) in self._mission_cost_sections().items():
            if not (billed or to_bill):
                continue
            data['costs']['data'].append({
                'id': section, 'sequence': sequences[section], 'billed': -billed, 'to_bill': -to_bill})
            data['costs']['total']['billed'] -= billed
            data['costs']['total']['to_bill'] -= to_bill
        return data

    # ------------------------------------------------------------------
    # Costs
    # ------------------------------------------------------------------

    def _mission_cost_sections(self):
        """{section: (billed, to bill)} in the currency of the project."""
        self.ensure_one()
        sections = {'mission_salaries': (self._mission_salary_cost(), 0.0)}
        sections.update(self._mission_expense_costs())
        return sections

    def _mission_salary_cost(self):
        """Cost of the validated days and hours of the mission, at the daily cost of each person."""
        self.ensure_one()
        project = self.sudo()
        company = project.company_id or self.env.company
        coefficient = company.mission_cost_coefficient or 1.0
        basis = {}
        total = 0.0
        for report in self.env['mission.activity.report'].sudo().search([('state', '=', 'validated')]):
            data = report.snapshot or {}
            lines = [line for line in data.get('missions', []) if line.get('project_id') == project.id]
            if not lines:
                continue
            employee = report.employee_id.sudo()
            wage = employee.contract_wage
            if not wage:
                continue
            days = data.get('days', [])
            for line in lines:
                unit = line.get('unit', 'day')
                for day, value in zip(days, line.get('values', [])):
                    if not value:
                        continue
                    day = fields.Date.to_date(day['date'])
                    key = (employee.id, day.year, day.month, unit)
                    if key not in basis:
                        basis[key] = self._mission_month_basis(employee, day.year, day.month, unit)
                    if basis[key]:
                        total += wage * coefficient * value / basis[key]
        return self._mission_convert(total, company)

    @api.model
    def _mission_month_basis(self, employee, year, month, unit):
        """Working days (or hours) of the month of the employee, public holidays deducted.

        Time off is not deducted: the wage of a month does not change with it.
        """
        first = date(year, month, 1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        work, _tz = work_intervals(self.env, employee, first, last)
        per_day = hours_by_day(work)
        return sum(per_day.values()) if unit == 'hour' else float(len(per_day))

    def _mission_convert(self, amount, company):
        if not amount:
            return 0.0
        currency = self.currency_id or company.currency_id
        return company.currency_id._convert(amount, currency, company, fields.Date.context_today(self))

    def _mission_expense_costs(self):
        """The IGD and the expenses not re-invoiced of the mission, split by state."""
        self.ensure_one()
        project = self.sudo()
        Expense = self.env['hr.expense'].sudo()
        if 'project_id' not in Expense._fields:
            return {}
        base = [('project_id', '=', project.id), ('state', 'in', BILLED_STATES + TO_BILL_STATES)]
        account = str(project.account_id.id) if project.account_id else None

        def counted_by_odoo(expense):
            # Odoo's own expense line counts those that carry the analytic account of the project.
            distribution = getattr(expense, 'analytic_distribution', None) or {}
            return bool(account) and any(account in key.split(',') for key in distribution)
        groups = {}
        if 'igd_generated' in Expense._fields:
            groups['mission_igd'] = base + [('igd_generated', '=', True)]
        if 'reinvoice_mode' in Expense._fields:
            groups['mission_expenses'] = base + [('reinvoice_mode', '=', 'none')] + (
                [('igd_generated', '=', False)] if 'igd_generated' in Expense._fields else [])
        result = {}
        for section, domain in groups.items():
            billed = to_bill = 0.0
            for expense in Expense.search(domain).filtered(lambda e: not counted_by_odoo(e)):
                amount = expense.company_currency_id._convert(
                    expense.total_amount, project.currency_id or expense.company_currency_id,
                    expense.company_id, expense.date or fields.Date.context_today(self)) \
                    if 'company_currency_id' in Expense._fields else expense.total_amount
                if expense.state in BILLED_STATES:
                    billed += amount
                else:
                    to_bill += amount
            result[section] = (billed, to_bill)
        return result
