# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Margin calculation of a mission, before the order exists.

The sales people fill the cost of the person (salary and charges, or the daily rate bought from a
freelance), the other costs, the daily rate sold and the duration. The sheet gives the margin per
day, per month and over the mission, the daily rates that reach a target margin, the net income of
the consultant, the commissions of the sales people, the long-distance allowances and the monthly
billing forecast. It is the same calculation as the spreadsheet it replaces.

The sheet belongs to a project (a draft one, created from the sheet if need be) and, later, to the
order. It is for the sales people and the managers only: it holds salaries.
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .public_holiday_wizard import french_public_holidays


def working_days_of_month(env, first, leave_days=0.0):
    """Working days of the month of `first` (Monday to Friday, French public holidays out), less leave."""
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    holidays = {day for day, _name in french_public_holidays(env, first.year)}
    days = 0
    day = first
    while day <= last:
        if day.weekday() < 5 and day not in holidays:
            days += 1
        day += timedelta(days=1)
    return max(days - (leave_days or 0.0), 0.0)


class MissionMargin(models.Model):
    _name = 'mission.margin'
    _description = "Margin calculation"
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True, help="Name of the calculation, e.g. the client and the consultant.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    project_id = fields.Many2one(
        'project.project', string="Project", index=True, tracking=True,
        help="The project of the mission, a draft one until the order is signed.")
    order_id = fields.Many2one(
        'sale.order', string="Order", index=True, tracking=True,
        help="Set once the order exists: the calculation then stays with it.")
    partner_id = fields.Many2one('res.partner', string="Customer", compute='_compute_partner', store=True,
                                 readonly=False)
    consultant = fields.Char(string="Consultant", help="The person, or the freelance, who does the mission.")
    note = fields.Html(string="Notes")

    # ---- Cost of the person -------------------------------------------------------------------
    cost_origin = fields.Selection(
        [('employee', "Employee"), ('freelance', "Freelance (daily rate bought)")],
        string="Cost of the person", default='employee', required=True)
    gross_salary = fields.Monetary(string="Gross yearly salary")
    paid_leave_days = fields.Float(string="Paid leave days a year", default=25.0)
    rtt_days = fields.Float(
        string="RTT days a year", default=8.0,
        help="Days off of an employee on a day-based contract (forfait jour).")
    weekend_days = fields.Float(string="Weekend days a year", default=104.0)
    public_holidays = fields.Float(string="Public holidays on weekdays", default=10.0)
    employer_charge_rate = fields.Float(string="Employer charges", default=0.457, digits=(16, 3))
    overhead_rate = fields.Float(
        string="Fixed and indirect costs", default=0.10, digits=(16, 3),
        help="Administrative charges (payroll, HR), premises, IT equipment, software, professional "
             "insurance and other indirect costs, as a share of the cost of the person.")
    payslip_monthly_cost = fields.Monetary(
        string="Monthly total cost (payslip)",
        help="When filled, replaces the salary and the employer charges: the total cost of the "
             "employee for a month, as on the payslip.")
    freelance_daily_rate = fields.Monetary(
        string="Freelance daily rate bought",
        help="Daily rate paid to a freelance: it replaces the salary and the charges.")

    # ---- Other costs --------------------------------------------------------------------------
    daily_cost_calendar = fields.Monetary(string="Cost per calendar day")
    daily_cost_worked = fields.Monetary(string="Cost per worked day", help="e.g. a daily allowance of 55 €.")
    mileage_monthly = fields.Monetary(string="Mileage allowances a month")
    expenses_monthly = fields.Monetary(string="Expenses a month")
    training_yearly = fields.Monetary(string="Training depreciation a year")
    ppe_yearly = fields.Monetary(string="PPE a year")
    equipment_yearly = fields.Monetary(string="Equipment (PC, tools, phone) a year", default=200.0)
    other_yearly = fields.Monetary(string="Other costs a year")

    # ---- Price --------------------------------------------------------------------------------
    daily_rate = fields.Monetary(string="Daily rate (TJM)", default=500.0, tracking=True)
    rebilled_daily = fields.Monetary(string="Expenses re-invoiced per worked day")
    duration_months = fields.Float(string="Duration of the mission (months)", default=12.0)
    start_date = fields.Date(string="Start", default=fields.Date.context_today)
    employee_charge_rate = fields.Float(string="Employee charges", default=0.23, digits=(16, 3))
    target_amount_1 = fields.Monetary(string="Target margin 1 a month", default=4000.0)
    target_amount_2 = fields.Monetary(string="Target margin 2 a month", default=2000.0)
    target_rate_1 = fields.Float(string="Target margin 1 (%)", default=0.30)
    target_rate_2 = fields.Float(string="Target margin 2 (%)", default=0.20)
    commission_threshold_rate = fields.Float(string="Commission threshold (margin %)", default=0.20)
    commission_threshold_amount = fields.Monetary(string="Commission threshold (margin a month)", default=2000.0)
    commission_rate_full = fields.Float(string="Full management", default=0.20)
    commission_rate_management = fields.Float(string="Management of the service or sales", default=0.10)
    commission_rate_referral = fields.Float(string="Referral of a candidate or a deal", default=0.05)

    igd_ids = fields.One2many('mission.margin.igd', 'margin_id', string="Long-distance allowances",
                              default=lambda self: self._default_igd())
    month_ids = fields.One2many('mission.margin.month', 'margin_id', string="Monthly billing forecast")

    # ---- Results ------------------------------------------------------------------------------
    days_per_year = fields.Float(string="Days worked a year", compute='_compute_results', digits=(16, 2))
    days_per_month = fields.Float(string="Days worked a month", compute='_compute_results', digits=(16, 2))
    base_cost = fields.Monetary(string="Cost of the person a year", compute='_compute_results')
    overhead_cost = fields.Monetary(string="Fixed and indirect costs a year", compute='_compute_results')
    loaded_cost = fields.Monetary(string="Loaded salary a year", compute='_compute_results')
    other_costs = fields.Monetary(string="Other costs a year", compute='_compute_results')
    total_cost = fields.Monetary(string="Total cost a year", compute='_compute_results')
    total_cost_month = fields.Monetary(string="Total cost a month", compute='_compute_results')
    cost_per_day = fields.Monetary(string="Total cost per worked day", compute='_compute_results')
    revenue = fields.Monetary(string="Billing a year", compute='_compute_results')
    price_per_day = fields.Monetary(string="Billing per worked day", compute='_compute_results')
    margin = fields.Monetary(string="Margin a year", compute='_compute_results')
    margin_month = fields.Monetary(string="Margin a month", compute='_compute_results')
    margin_day = fields.Monetary(string="Margin per worked day", compute='_compute_results')
    margin_rate = fields.Float(string="Margin (%)", compute='_compute_results', digits=(16, 3))
    margin_duration = fields.Monetary(string="Margin over the mission", compute='_compute_results')
    rate_target_1 = fields.Monetary(string="Daily rate for margin 1 (€ a month)", compute='_compute_results')
    rate_target_2 = fields.Monetary(string="Daily rate for margin 2 (€ a month)", compute='_compute_results')
    rate_target_rate_1 = fields.Monetary(string="Daily rate for margin 1 (%)", compute='_compute_results')
    rate_target_rate_2 = fields.Monetary(string="Daily rate for margin 2 (%)", compute='_compute_results')
    net_salary_month = fields.Monetary(string="Net salary a month", compute='_compute_results')
    net_salary_day = fields.Monetary(string="Net salary per worked day", compute='_compute_results')
    daily_fees_month = fields.Monetary(string="Daily fees a month", compute='_compute_results')
    daily_fees_day = fields.Monetary(string="Daily fees per worked day", compute='_compute_results')
    net_income_month = fields.Monetary(string="Net income a month", compute='_compute_results')
    net_income_day = fields.Monetary(string="Net income per worked day", compute='_compute_results')
    net_income_year = fields.Monetary(string="Net income a year", compute='_compute_results')
    commission_eligible = fields.Boolean(string="Commissions due", compute='_compute_results')
    commission_full = fields.Monetary(string="Full management", compute='_compute_results')
    commission_management = fields.Monetary(string="Management of the service or sales", compute='_compute_results')
    commission_referral = fields.Monetary(string="Referral", compute='_compute_results')
    commission_full_potential = fields.Monetary(compute='_compute_results')
    commission_management_potential = fields.Monetary(compute='_compute_results')
    commission_referral_potential = fields.Monetary(compute='_compute_results')
    forecast_revenue = fields.Monetary(string="Forecast billing", compute='_compute_forecast')
    forecast_margin = fields.Monetary(string="Forecast margin", compute='_compute_forecast')
    forecast_days = fields.Float(string="Forecast worked days", compute='_compute_forecast')

    def _default_igd(self):
        """The 2026 rates of the spreadsheet: a meal and the lodging, by period of the mission."""
        rows = [
            (_("First 3 months"), 1, 3, 21.4, 56.8),
            (_("Month 4 to 24"), 4, 24, 18.2, 48.3),
            (_("Month 25 to 72"), 25, 72, 15.0, 39.8),
        ]
        return [(0, 0, {'sequence': i, 'label': label, 'month_from': start, 'month_to': end,
                        'meal': meal, 'lodging': lodging})
                for i, (label, start, end, meal, lodging) in enumerate(rows, 1)]

    @api.depends('order_id.partner_id', 'project_id.partner_id')
    def _compute_partner(self):
        for margin in self:
            margin.partner_id = margin.order_id.partner_id or margin.project_id.partner_id or margin.partner_id

    @api.depends(
        'cost_origin', 'gross_salary', 'paid_leave_days', 'rtt_days', 'weekend_days', 'public_holidays',
        'employer_charge_rate', 'overhead_rate', 'payslip_monthly_cost', 'freelance_daily_rate',
        'daily_cost_calendar', 'daily_cost_worked', 'mileage_monthly', 'expenses_monthly', 'training_yearly',
        'ppe_yearly', 'equipment_yearly', 'other_yearly', 'daily_rate', 'rebilled_daily', 'duration_months',
        'employee_charge_rate', 'target_amount_1', 'target_amount_2', 'target_rate_1', 'target_rate_2',
        'commission_threshold_rate', 'commission_threshold_amount', 'commission_rate_full',
        'commission_rate_management', 'commission_rate_referral')
    def _compute_results(self):
        for m in self:
            days = 365 - m.weekend_days - m.public_holidays - m.paid_leave_days - m.rtt_days
            days = days if days > 0 else 0.0
            if m.cost_origin == 'freelance' and m.freelance_daily_rate:
                base = m.freelance_daily_rate * days
            elif m.payslip_monthly_cost:
                base = m.payslip_monthly_cost * 12
            else:
                base = m.gross_salary * (1 + m.employer_charge_rate)
            overhead = base * m.overhead_rate
            others = (m.daily_cost_calendar * 365 + m.daily_cost_worked * days + m.mileage_monthly * 12
                      + m.expenses_monthly * 12 + m.training_yearly + m.ppe_yearly + m.equipment_yearly
                      + m.other_yearly)
            total = base + overhead + others
            revenue = (m.daily_rate + m.rebilled_daily) * days
            margin = revenue - total
            per_day = (lambda amount: amount / days if days else 0.0)
            monthly_days = days / 12
            margin_month = margin / 12
            rate = margin / revenue if revenue else 0.0
            m.days_per_year = days
            m.days_per_month = monthly_days
            m.base_cost = base
            m.overhead_cost = overhead
            m.loaded_cost = base + overhead
            m.other_costs = others
            m.total_cost = total
            m.total_cost_month = total / 12
            m.cost_per_day = per_day(total)
            m.revenue = revenue
            m.price_per_day = m.daily_rate + m.rebilled_daily
            m.margin = margin
            m.margin_month = margin_month
            m.margin_day = per_day(margin)
            m.margin_rate = rate
            m.margin_duration = margin_month * m.duration_months
            # Daily rate that gives a target margin: the cost of a day plus what is wanted, less what is re-invoiced.
            m.rate_target_1 = ((total / 12 + m.target_amount_1) / monthly_days - m.rebilled_daily) if days else 0.0
            m.rate_target_2 = ((total / 12 + m.target_amount_2) / monthly_days - m.rebilled_daily) if days else 0.0
            m.rate_target_rate_1 = (per_day(total) / (1 - m.target_rate_1) - m.rebilled_daily) \
                if days and m.target_rate_1 < 1 else 0.0
            m.rate_target_rate_2 = (per_day(total) / (1 - m.target_rate_2) - m.rebilled_daily) \
                if days and m.target_rate_2 < 1 else 0.0
            net = m.gross_salary * (1 - m.employee_charge_rate)
            fees = m.daily_cost_calendar * 365 + m.daily_cost_worked * days
            m.net_salary_month = net / 12
            m.net_salary_day = per_day(net)
            m.daily_fees_month = fees / 12
            m.daily_fees_day = per_day(fees)
            m.net_income_month = (net + fees) / 12
            m.net_income_day = per_day(net + fees)
            m.net_income_year = net + fees
            eligible = rate > m.commission_threshold_rate or margin_month > m.commission_threshold_amount
            m.commission_eligible = eligible
            m.commission_full_potential = margin_month * m.commission_rate_full
            m.commission_management_potential = margin_month * m.commission_rate_management
            m.commission_referral_potential = margin_month * m.commission_rate_referral
            m.commission_full = m.commission_full_potential if eligible else 0.0
            m.commission_management = m.commission_management_potential if eligible else 0.0
            m.commission_referral = m.commission_referral_potential if eligible else 0.0

    @api.depends('month_ids.working_days', 'month_ids.revenue', 'month_ids.margin')
    def _compute_forecast(self):
        for m in self:
            m.forecast_days = sum(m.month_ids.mapped('working_days'))
            m.forecast_revenue = sum(m.month_ids.mapped('revenue'))
            m.forecast_margin = sum(m.month_ids.mapped('margin'))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_generate_months(self):
        """The months of the mission, from its start, with their working days (holidays out)."""
        for m in self:
            if not m.start_date:
                raise UserError(_("Enter the start of the mission."))
            leave = {line.date: line.leave_days for line in m.month_ids}
            first = m.start_date.replace(day=1)
            count = max(int(round(m.duration_months)), 1) if m.duration_months else 1
            commands = [(5, 0, 0)]
            for i in range(count):
                month = date(first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1, 1)
                commands.append((0, 0, {'date': month, 'leave_days': leave.get(month, 0.0)}))
            m.month_ids = commands
        return True

    @api.model
    def _action_open_margins(self, domain, context):
        return {'type': 'ir.actions.act_window', 'name': _("Margin calculations"), 'res_model': 'mission.margin',
                'view_mode': 'list,form', 'domain': domain, 'context': context}

    def action_create_project(self):
        self.ensure_one()
        if self.project_id:
            raise UserError(_("This calculation already has a project."))
        self.project_id = self.env['project.project'].create({
            'name': self.name, 'partner_id': self.partner_id.id, 'company_id': self.company_id.id})
        return self.action_open_project()

    def action_open_project(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'project.project', 'res_id': self.project_id.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': self.order_id.id,
                'view_mode': 'form', 'target': 'current'}


class MissionMarginIgd(models.Model):
    _name = 'mission.margin.igd'
    _description = "Long-distance allowances of a margin calculation"
    _order = 'sequence, id'

    margin_id = fields.Many2one('mission.margin', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(string="Period", required=True)
    month_from = fields.Integer(string="From month")
    month_to = fields.Integer(string="To month")
    meal = fields.Monetary(string="Meal", currency_field='currency_id')
    lodging = fields.Monetary(
        string="Lodging and breakfast", currency_field='currency_id',
        help="Lodging and breakfast in the other departments.")
    total = fields.Monetary(
        string="Total per worked day", compute='_compute_total', currency_field='currency_id',
        help="Two meals and the lodging. Not due on leave, on the days back home, or when the "
             "travel is paid at its actual cost.")
    currency_id = fields.Many2one(related='margin_id.currency_id')

    @api.depends('meal', 'lodging')
    def _compute_total(self):
        for line in self:
            line.total = 2 * line.meal + line.lodging


class MissionMarginMonth(models.Model):
    _name = 'mission.margin.month'
    _description = "Month of the billing forecast of a margin calculation"
    _order = 'date, id'

    margin_id = fields.Many2one('mission.margin', required=True, ondelete='cascade')
    date = fields.Date(string="Month", required=True)
    leave_days = fields.Float(string="Planned leave, closure")
    working_days = fields.Float(string="Working days", compute='_compute_month')
    revenue = fields.Monetary(string="Monthly billing", compute='_compute_month', currency_field='currency_id')
    margin = fields.Monetary(string="Monthly margin", compute='_compute_month', currency_field='currency_id')
    currency_id = fields.Many2one(related='margin_id.currency_id')

    @api.depends('date', 'leave_days', 'margin_id.price_per_day', 'margin_id.margin_day')
    def _compute_month(self):
        for line in self:
            days = working_days_of_month(self.env, line.date.replace(day=1), line.leave_days) if line.date else 0.0
            line.working_days = days
            line.revenue = days * line.margin_id.price_per_day
            line.margin = days * line.margin_id.margin_day


class ProjectProject(models.Model):
    _inherit = 'project.project'

    margin_ids = fields.One2many('mission.margin', 'project_id', string="Margin calculations")
    margin_count = fields.Integer(compute='_compute_margin_count')

    def _compute_margin_count(self):
        # The salaries stay with the sales people and the managers: the count is read without their rights.
        counts = dict(self.env['mission.margin'].sudo()._read_group(
            [('project_id', 'in', self.ids)], ['project_id'], ['__count']))
        for project in self:
            project.margin_count = counts.get(project, 0)

    def action_open_margins(self):
        self.ensure_one()
        return self.env['mission.margin']._action_open_margins([('project_id', '=', self.id)], {'default_project_id': self.id})


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    margin_count = fields.Integer(compute='_compute_margin_count')

    def _compute_margin_count(self):
        counts = dict(self.env['mission.margin'].sudo()._read_group(
            [('order_id', 'in', self.ids)], ['order_id'], ['__count']))
        for order in self:
            order.margin_count = counts.get(order, 0)

    def action_open_margins(self):
        self.ensure_one()
        return self.env['mission.margin']._action_open_margins(
            [('order_id', '=', self.id)], {'default_order_id': self.id, 'default_project_id': self.project_id.id})
