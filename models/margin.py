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
import math
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .igd import BASIS
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

    name = fields.Char(
        compute='_compute_name', store=True, readonly=False, tracking=True,
        help="Filled in from the customer, the consultant, the daily rate and the duration while you do not "
             "write your own name.")
    name_auto = fields.Char(compute='_compute_name', store=True)
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

    # ---- Consultant: pay and charges ----------------------------------------------------------
    cost_origin = fields.Selection(
        [('employee', "Employee"), ('freelance', "Freelance")],
        string="Consultant type", default='employee', required=True)
    gross_salary = fields.Monetary(string="Gross yearly salary", default=40000.0)
    salary_min = fields.Monetary(related='company_id.mission_salary_min')
    salary_max = fields.Monetary(related='company_id.mission_salary_max')
    paid_leave_days = fields.Float(string="Paid leave days a year", default=25.0)
    rtt_days = fields.Float(
        string="RTT days a year", default=8.0,
        help="Days off of an employee on a day-based contract (forfait jour).")
    weekend_days = fields.Float(string="Weekend days a year", default=104.0)
    public_holidays = fields.Float(string="Public holidays on weekdays", default=10.0)
    # The rates of the company (Settings) are copied into each sheet: a later change of the company
    # does not move the sheets already made, and the sheet cannot change them.
    employer_charge_rate = fields.Float(
        string="Employer charges", digits=(16, 3), readonly=True, copy=True, default=0.457)
    overhead_rate = fields.Float(
        string="Fixed and indirect costs", digits=(16, 3), readonly=True, copy=True, default=0.10,
        help="Administrative charges (payroll, HR), premises, IT equipment, software, professional "
             "insurance and other indirect costs, as a share of the pay and charges. Set for the company "
             "in the Settings.")
    payslip_monthly_cost = fields.Monetary(
        string="Monthly total cost (payslip)",
        help="When filled, replaces the salary and the employer charges: the total cost of the "
             "employee for a month, as on the payslip.")
    freelance_daily_rate = fields.Monetary(
        string="Freelance daily rate bought",
        help="Daily rate paid to a freelance: it replaces the salary and the charges.")

    # ---- Amounts agreed with the consultant ----------------------------------------------------
    daily_cost_worked = fields.Monetary(
        string="Fixed amount per day worked", help="Paid to the employee for each day worked, e.g. travel.")
    daily_cost_reason = fields.Char(string="Reason of the daily amount", help="e.g. travel, daily allowance.")
    fixed_monthly_amount = fields.Monetary(
        string="Fixed amount per month",
        help="Agreed with the employee each month, whatever the days worked (e.g. a rent). It does not "
             "interfere with the long-distance allowances.")
    fixed_monthly_reason = fields.Char(string="Reason of the monthly amount", help="e.g. rent.")

    # ---- Other costs, from the shortest period to the longest -----------------------------------
    other_worked_daily = fields.Monetary(string="Other costs per day worked")
    other_worked_daily_note = fields.Char(string="Note", help="e.g. what the amount is for.")
    daily_cost_calendar = fields.Monetary(string="Other calendar costs", help="Per calendar day.")
    daily_cost_calendar_note = fields.Char(string="Note")
    expenses_monthly = fields.Monetary(string="Other monthly costs")
    expenses_monthly_note = fields.Char(string="Note")
    mileage_monthly = fields.Monetary(string="Mileage allowances a month")
    mileage_monthly_note = fields.Char(string="Note")
    training_yearly = fields.Monetary(string="Training depreciation a year")
    training_yearly_note = fields.Char(string="Note")
    ppe_yearly = fields.Monetary(string="PPE a year")
    ppe_yearly_note = fields.Char(string="Note")
    equipment_yearly = fields.Monetary(string="Equipment (PC, tools, phone) a year", default=200.0)
    equipment_yearly_note = fields.Char(string="Note")
    other_yearly = fields.Monetary(string="Other yearly costs")
    other_yearly_note = fields.Char(string="Note")

    # ---- Price --------------------------------------------------------------------------------
    margin_wanted = fields.Integer(
        string="Margin slider (%)", default=20,
        help="Move the slider: the daily rate follows the margin wanted (rounded up to 5 €) when the costs "
             "change. Type a daily rate to set it by hand.")
    rate_manual = fields.Boolean(string="Rate typed by hand", default=False)
    daily_rate = fields.Monetary(string="Daily rate sold (TJM)", tracking=True)
    rebilled_daily = fields.Monetary(string="Expenses re-invoiced per day worked")
    rebilled_daily_note = fields.Char(string="Note")
    rebilled_monthly = fields.Monetary(string="Expenses re-invoiced per month")
    rebilled_monthly_note = fields.Char(string="Note")
    duration_months = fields.Float(string="Duration of the mission (months)", default=12.0)
    start_date = fields.Date(string="Start", default=fields.Date.context_today)
    employee_charge_rate = fields.Float(
        string="Employee charges", digits=(16, 3), readonly=True, copy=True, default=0.23)
    target_amount_1 = fields.Monetary(string="Target margin 1 a month", default=4000.0)
    target_amount_2 = fields.Monetary(string="Target margin 2 a month", default=2000.0)
    target_rate_1 = fields.Float(string="Target margin 1 (%)", default=0.30)
    target_rate_2 = fields.Float(string="Target margin 2 (%)", default=0.20)

    # ---- Commissions: the conditions are the company's, the rates follow the status -------------
    commission_threshold_rate = fields.Float(
        string="Commission threshold (margin %)", readonly=True, copy=True, default=0.20)
    commission_threshold_amount = fields.Monetary(
        string="Commission threshold (margin a month)", readonly=True, copy=True, default=2000.0)
    commission_rule_id = fields.Many2one(
        'mission.commission.rule', string="Status of the salesperson", copy=True,
        domain="[('company_id', '=', company_id)]",
        help="The commission rates depend on the status of the salesperson (Settings).")
    commission_cap = fields.Float(
        related='company_id.mission_commission_cap', string="Cap (share of the gross margin of a business)")
    commission_rate_sourcing = fields.Float(
        related='commission_rule_id.rate_sourcing', string="Sourcing of a candidate")
    commission_rate_referral = fields.Float(related='commission_rule_id.rate_referral', string="Business referral")
    commission_rate_candidate = fields.Float(
        related='commission_rule_id.rate_candidate', string="Full management, candidate side")
    commission_rate_client = fields.Float(
        related='commission_rule_id.rate_client', string="Full management, client side")
    commission_rate_full = fields.Float(
        related='commission_rule_id.rate_full', string="Full management of the business")
    commission_rate_team = fields.Float(
        related='commission_rule_id.rate_team', string="Services managed by the collaborators")
    show_commissions = fields.Boolean(related='company_id.mission_show_commissions')

    # ---- Long-distance allowances --------------------------------------------------------------
    igd_lodging = fields.Boolean(string="Lodging")
    igd_lunch = fields.Boolean(string="Meal 1")
    igd_dinner = fields.Boolean(string="Meal 2")
    igd_expat = fields.Boolean(string="Expat allowance")
    igd_expat_amount = fields.Monetary(
        string="Expat allowance per day worked", help="Free amount: the expat allowance is not on the scale.")
    igd_lodging_basis = fields.Selection(
        BASIS, string="Lodging on", default='worked', required=True,
        help="Days worked, or every calendar day (weekends, public holidays and time off included).")
    igd_meal_basis = fields.Selection(
        BASIS, string="Meals on", default='worked', required=True,
        help="Days worked, or every calendar day (weekends, public holidays and time off included).")
    igd_expat_basis = fields.Selection(
        BASIS, string="Expat allowance on", default='worked', required=True,
        help="Days worked, or every calendar day (weekends, public holidays and time off included).")
    igd_scale_choice = fields.Selection(
        lambda self: self._igd_scale_choices(), string="Allowance rates", default='2',
        help="The rates of the scale that apply to every day of the mission: using one period only avoids a "
             "change of profitability and of pay when the mission passes the next period.")
    igd_rebilled = fields.Boolean(
        string="Allowances re-invoiced to the customer",
        help="The allowances are added to the expenses re-invoiced per day.")
    igd_line_ids = fields.One2many(
        'mission.margin.igd', 'margin_id', string="Scale of the allowances", copy=True,
        default=lambda self: self._default_igd_lines(),
        help="Copied from the scale of the company: edit it here for this mission only.")
    month_ids = fields.One2many('mission.margin.month', 'margin_id', string="Monthly billing forecast")

    # ---- Results ------------------------------------------------------------------------------
    days_per_year = fields.Float(string="Days worked a year", compute='_compute_results', digits=(16, 2))
    days_per_month = fields.Float(string="Days worked a month", compute='_compute_results', digits=(16, 2))
    base_cost = fields.Monetary(string="Pay and charges a year", compute='_compute_results')
    overhead_cost = fields.Monetary(string="Fixed and indirect costs a year", compute='_compute_results')
    loaded_cost = fields.Monetary(string="Loaded cost a year", compute='_compute_results')
    other_costs = fields.Monetary(string="Total other mission charges and allowances", compute='_compute_results')
    igd_daily = fields.Monetary(string="Allowances per worked day", compute='_compute_results')
    igd_month = fields.Monetary(string="Allowances a month", compute='_compute_results')
    rebilled_total = fields.Monetary(string="Expenses re-invoiced per worked day", compute='_compute_results')
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
    commission_sourcing = fields.Monetary(string="Sourcing of a candidate", compute='_compute_results')
    commission_referral = fields.Monetary(string="Business referral", compute='_compute_results')
    commission_candidate = fields.Monetary(string="Full management, candidate side", compute='_compute_results')
    commission_client = fields.Monetary(string="Full management, client side", compute='_compute_results')
    commission_full = fields.Monetary(string="Full management of the business", compute='_compute_results')
    commission_team = fields.Monetary(string="Services managed by the collaborators", compute='_compute_results')
    commission_cap_amount = fields.Monetary(string="Most a business can give a month", compute='_compute_results')
    breakdown = fields.Json(string="Breakdown of the monthly revenue", compute='_compute_results')
    forecast_revenue = fields.Monetary(string="Forecast billing", compute='_compute_forecast')
    forecast_margin = fields.Monetary(string="Forecast margin", compute='_compute_forecast')
    forecast_days = fields.Float(string="Forecast worked days", compute='_compute_forecast')

    @api.depends('partner_id', 'consultant', 'daily_rate', 'duration_months')
    def _compute_name(self):
        """\"Customer - Consultant - 420 € a day - 12 months\": the name of a sheet nobody named, kept up to date
        until the user writes their own."""
        for m in self:
            parts = [part for part in (m.partner_id.name, m.consultant) if part] or [_("Margin calculation")]
            if m.daily_rate:
                parts.append(_("%(rate)s a day", rate=("%g %s" % (m.daily_rate, m.currency_id.symbol or ""))))
            if m.duration_months:
                parts.append(_("%(months)s months", months=("%g" % m.duration_months)))
            auto = " - ".join(parts)
            if not m.name or m.name == m.name_auto:
                m.name = auto
            m.name_auto = auto

    @api.depends('order_id.partner_id', 'project_id.partner_id')
    def _compute_partner(self):
        for margin in self:
            margin.partner_id = margin.order_id.partner_id or margin.project_id.partner_id or margin.partner_id

    @api.depends(
        'cost_origin', 'gross_salary', 'paid_leave_days', 'rtt_days', 'weekend_days', 'public_holidays',
        'employer_charge_rate', 'overhead_rate', 'payslip_monthly_cost', 'freelance_daily_rate',
        'other_worked_daily', 'daily_cost_calendar', 'daily_cost_worked', 'fixed_monthly_amount', 'mileage_monthly',
        'expenses_monthly', 'training_yearly', 'ppe_yearly', 'equipment_yearly', 'other_yearly', 'daily_rate',
        'rebilled_daily', 'rebilled_monthly', 'duration_months', 'employee_charge_rate', 'target_amount_1',
        'target_amount_2', 'target_rate_1', 'target_rate_2', 'commission_threshold_rate',
        'commission_threshold_amount', 'commission_rule_id.rate_sourcing', 'commission_rule_id.rate_referral',
        'commission_rule_id.rate_candidate', 'commission_rule_id.rate_client', 'commission_rule_id.rate_full',
        'commission_rule_id.rate_team', 'company_id.mission_commission_cap', 'igd_lodging', 'igd_lunch', 'igd_dinner', 'igd_expat', 'igd_expat_amount', 'igd_lodging_basis', 'igd_meal_basis', 'igd_expat_basis', 'igd_scale_choice',
        'igd_rebilled', 'igd_line_ids.month_from', 'igd_line_ids.month_to', 'igd_line_ids.meal',
        'igd_line_ids.lodging')
    def _compute_results(self):
        for m in self:
            days = 365 - m.weekend_days - m.public_holidays - m.paid_leave_days - m.rtt_days
            days = days if days > 0 else 0.0
            freelance = m.cost_origin == 'freelance'
            if freelance and m.freelance_daily_rate:
                base = m.freelance_daily_rate * days
            elif m.payslip_monthly_cost and not freelance:
                base = m.payslip_monthly_cost * 12
            else:
                base = 0.0 if freelance else m.gross_salary * (1 + m.employer_charge_rate)
            overhead = base * m.overhead_rate
            # A freelance bills his expenses in his daily rate: no allowances, no amounts agreed with him.
            allowances = 0.0 if freelance else m._igd_year()
            igd = allowances / days if days else 0.0
            agreed = 0.0 if freelance else m.daily_cost_worked * days + m.fixed_monthly_amount * 12
            generic = (m.other_worked_daily * days + m.daily_cost_calendar * 365 + m.expenses_monthly * 12
                       + m.other_yearly)
            employee_only = 0.0 if freelance else (
                m.mileage_monthly * 12 + m.training_yearly + m.ppe_yearly + m.equipment_yearly)
            others = generic + employee_only + agreed + allowances
            rebilled = (m.rebilled_daily + (igd if m.igd_rebilled else 0.0)
                        + (m.rebilled_monthly * 12 / days if days else 0.0))
            total = base + overhead + others
            revenue = (m.daily_rate + rebilled) * days
            m.igd_daily = igd
            m.igd_month = allowances / 12
            m.rebilled_total = rebilled
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
            m.price_per_day = m.daily_rate + rebilled
            m.margin = margin
            m.margin_month = margin_month
            m.margin_day = per_day(margin)
            m.margin_rate = rate
            m.margin_duration = margin_month * m.duration_months
            # Daily rate that gives a target margin: the cost of a day plus what is wanted, less what is re-invoiced.
            m.rate_target_1 = ((total / 12 + m.target_amount_1) / monthly_days - rebilled) if days else 0.0
            m.rate_target_2 = ((total / 12 + m.target_amount_2) / monthly_days - rebilled) if days else 0.0
            m.rate_target_rate_1 = (per_day(total) / (1 - m.target_rate_1) - rebilled) \
                if days and m.target_rate_1 < 1 else 0.0
            m.rate_target_rate_2 = (per_day(total) / (1 - m.target_rate_2) - rebilled) \
                if days and m.target_rate_2 < 1 else 0.0
            net = 0.0 if freelance else m.gross_salary * (1 - m.employee_charge_rate)
            m.net_salary_month = net / 12
            m.net_salary_day = per_day(net)
            m.daily_fees_month = agreed / 12
            m.daily_fees_day = per_day(agreed)
            m.net_income_month = (net + agreed) / 12
            m.net_income_day = per_day(net + agreed)
            m.net_income_year = net + agreed
            eligible = rate > m.commission_threshold_rate or margin_month > m.commission_threshold_amount
            m.commission_eligible = eligible
            # Each role gives its share of the margin of a month, once the business is profitable enough.
            for role in ('sourcing', 'referral', 'candidate', 'client', 'full', 'team'):
                share = margin_month * m['commission_rate_' + role]
                m['commission_' + role] = share if eligible and margin_month > 0 else 0.0
            m.commission_cap_amount = max(margin_month, 0.0) * m.commission_cap if eligible else 0.0
            calendar = m.daily_cost_calendar * 365
            m.breakdown = m._breakdown(freelance, base, overhead, agreed + allowances, calendar,
                                       others - agreed - allowances - calendar, margin, revenue)

    def _breakdown(self, freelance, base, overhead, paid_to_consultant, calendar, other, margin, revenue):
        """Where a month of billing goes: the pay of the consultant (net, then the charges), the amounts paid
        to them, the fixed and indirect costs, the other costs and what stays with the company."""
        self.ensure_one()
        parts = []
        if freelance or self.payslip_monthly_cost:
            parts.append(('pay', _("Freelance") if freelance else _("Pay and charges"), base))
        else:
            parts += [
                ('net', _("Net salary of the consultant"), self.gross_salary * (1 - self.employee_charge_rate)),
                ('employee', _("Employee charges"), self.gross_salary * self.employee_charge_rate),
                ('employer', _("Employer charges"), self.gross_salary * self.employer_charge_rate)]
        parts += [
            ('allowances', _("Allowances and amounts paid to the consultant"), paid_to_consultant),
            ('calendar', _("Other calendar costs"), calendar),
            ('overhead', _("Fixed and indirect costs"), overhead),
            ('other', _("Other mission charges"), other),
            ('margin', _("Margin of the company"), margin)]
        return {
            'total': revenue / 12,
            'deficit': max(-margin, 0.0) / 12,
            'symbol': self.currency_id.symbol or '',
            'after': self.currency_id.position == 'after',
            'segments': [{'key': key, 'label': label, 'value': value / 12}
                         for key, label, value in parts if value > 0.005],
        }

    @api.depends('month_ids.working_days', 'month_ids.revenue', 'month_ids.margin')
    def _compute_forecast(self):
        for m in self:
            m.forecast_days = sum(m.month_ids.mapped('working_days'))
            m.forecast_revenue = sum(m.month_ids.mapped('revenue'))
            m.forecast_margin = sum(m.month_ids.mapped('margin'))

    # ------------------------------------------------------------------
    # The long-distance allowances and the status of the salesperson
    # ------------------------------------------------------------------

    @api.model
    def _igd_scale_choices(self):
        """'0': the scale by month of the mission; '1', '2', '3'...: one period of the scale for every month."""
        rows = self.env.company.sudo().mission_igd_rate_ids.sorted(lambda line: (line.sequence, line.id))
        return [('0', _("By month of the mission"))] + [
            (str(index), _("%s only", row.label)) for index, row in enumerate(rows, 1)]

    @api.model
    def default_get(self, fields_list):
        """The rates and the thresholds of the company, and its first status of salesperson: read when a sheet
        is made (the columns themselves are created before the settings of the company exist)."""
        values = super().default_get(fields_list)
        company = self.env.company
        for name, source in (
                ('employer_charge_rate', 'mission_employer_charge_rate'),
                ('employee_charge_rate', 'mission_employee_charge_rate'),
                ('overhead_rate', 'mission_overhead_rate'),
                ('commission_threshold_rate', 'mission_commission_threshold_rate'),
                ('commission_threshold_amount', 'mission_commission_threshold_amount')):
            if name in fields_list and 'default_' + name not in self.env.context:
                values[name] = company[source]
        if 'commission_rule_id' in fields_list and not values.get('commission_rule_id'):
            rule = self._default_commission_rule()
            if rule:
                values['commission_rule_id'] = rule.id
        if 'igd_scale_choice' in fields_list and 'default_igd_scale_choice' not in self.env.context:
            values['igd_scale_choice'] = self._default_igd_choice()
        return values

    @api.model
    def _default_igd_choice(self):
        """The second period of the scale (month 4 to 24) when there is one: the pay and the profitability of the
        mission do not change when it passes the fourth month."""
        count = len(self.env.company.sudo().mission_igd_rate_ids)
        return '2' if count >= 2 else ('1' if count else '0')

    @api.model
    def _default_igd_lines(self):
        return self.env.company._mission_igd_scale_commands()

    @api.model
    def _default_commission_rule(self):
        return self.env['mission.commission.rule'].search([('company_id', '=', self.env.company.id)], limit=1)

    def _ensure_igd_lines(self):
        """The scale of the company, copied into the sheet: edited there, it does not touch the reference."""
        for margin in self.filtered(lambda m: not m.igd_line_ids):
            margin.igd_line_ids = margin.company_id._mission_igd_scale_commands()

    def action_reset_igd_scale(self):
        for margin in self:
            margin.igd_line_ids = [(5, 0, 0)] + margin.company_id._mission_igd_scale_commands()
        return True

    def _igd_year(self):
        """Allowances of a year: what is ticked, at the rates of the scale of the sheet, on the days chosen for each
        (the days worked, or every calendar day), and the expat allowance at its free amount.

        One period of the scale applies to every month when it is chosen; otherwise the rates follow the month
        of the mission (the first months cost more than the following ones).
        """
        self.ensure_one()
        worked = max(365 - self.weekend_days - self.public_holidays - self.paid_leave_days - self.rtt_days, 0.0)

        def span(basis):
            return 365.0 if basis == 'calendar' else worked

        expat = self.igd_expat_amount * span(self.igd_expat_basis) if self.igd_expat else 0.0
        meals = int(bool(self.igd_lunch)) + int(bool(self.igd_dinner))
        if not (meals or self.igd_lodging):
            return expat
        lodging_days, meal_days = span(self.igd_lodging_basis), span(self.igd_meal_basis)

        def year_at(line):
            return (line.lodging * lodging_days if self.igd_lodging else 0.0) + meals * line.meal * meal_days

        lines = (self.igd_line_ids or self.company_id.sudo().mission_igd_rate_ids).sorted(
            lambda line: line.sequence)
        choice = int(self.igd_scale_choice or 0)
        if 0 < choice <= len(lines):
            return year_at(lines[choice - 1]) + expat
        months = max(int(round(self.duration_months)), 1)
        total = 0.0
        for month in range(1, months + 1):
            line = next((line for line in lines
                         if line.month_from <= month and (not line.month_to or month <= line.month_to)), None)
            if line:
                total += year_at(line)
        return total / months + expat

    def _igd_per_day(self):
        """The allowances of a year, per day worked."""
        self.ensure_one()
        worked = max(365 - self.weekend_days - self.public_holidays - self.paid_leave_days - self.rtt_days, 0.0)
        return self._igd_year() / worked if worked else 0.0

    def _rate_for_margin(self, rate):
        """Daily rate that gives a margin (share of the billing), rounded up to 5 €."""
        self.ensure_one()
        if not self.days_per_year or rate >= 1:
            return 0.0
        rate_day = self.cost_per_day / (1 - rate) - self.rebilled_total
        return float(math.ceil(max(rate_day, 0.0) / 5.0) * 5)

    #: the inputs that change the cost of a day: the daily rate follows them while a margin is wanted.
    COST_FIELDS = (
        'cost_origin', 'gross_salary', 'paid_leave_days', 'rtt_days', 'weekend_days', 'public_holidays',
        'employer_charge_rate', 'overhead_rate', 'payslip_monthly_cost', 'freelance_daily_rate',
        'other_worked_daily', 'daily_cost_calendar', 'daily_cost_worked', 'fixed_monthly_amount', 'mileage_monthly',
        'expenses_monthly', 'training_yearly', 'ppe_yearly', 'equipment_yearly', 'other_yearly', 'rebilled_daily',
        'rebilled_monthly', 'duration_months', 'igd_lodging', 'igd_lunch', 'igd_dinner', 'igd_expat',
        'igd_expat_amount', 'igd_lodging_basis', 'igd_meal_basis', 'igd_expat_basis', 'igd_scale_choice',
        'igd_rebilled', 'margin_wanted')

    def _follow_margin(self):
        for m in self:
            if not m.rate_manual:
                m.with_context(margin_follow=True).daily_rate = m._rate_for_margin(m.margin_wanted / 100.0)

    @api.onchange(*COST_FIELDS)
    def _onchange_follow_margin(self):
        self._follow_margin()

    @api.onchange('margin_wanted')
    def _onchange_margin_wanted(self):
        # The slider placed by the daily rate typed or slid (it follows the rate): the rate stays.
        if self.rate_manual and self.margin_wanted == min(max(int(round(self.margin_rate * 100)), 10), 40):
            return
        # Moving the slider gives the control back to the margin.
        self.rate_manual = False
        self._follow_margin()

    @api.onchange('daily_rate')
    def _onchange_daily_rate(self):
        # Typed by hand: unless it is the rate the margin wanted gave (the sheet sets it itself).
        if not self.rate_manual and self.daily_rate != self._rate_for_margin(self.margin_wanted / 100.0):
            self.rate_manual = True
        # The margin slider follows the daily rate it did not give (within its limits of 10 to 40 %).
        if self.rate_manual and self.revenue:
            self.margin_wanted = min(max(int(round(self.margin_rate * 100)), 10), 40)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'daily_rate' in vals and 'rate_manual' not in vals:
                vals['rate_manual'] = True
        records = super().create(vals_list)
        records._ensure_igd_lines()
        for record, vals in zip(records, vals_list):
            if 'daily_rate' not in vals:
                record._follow_margin()
        records._sync_links()
        return records

    def write(self, vals):
        if 'margin_wanted' in vals and 'rate_manual' not in vals and 'daily_rate' not in vals:
            vals = dict(vals, rate_manual=False)
        elif 'daily_rate' in vals and 'rate_manual' not in vals and not self.env.context.get('margin_follow'):
            vals = dict(vals, rate_manual=True)
        result = super().write(vals)
        if 'daily_rate' not in vals and any(key in vals for key in self.COST_FIELDS + ('rate_manual',)):
            self._follow_margin()
        if 'project_id' in vals or 'order_id' in vals:
            self._sync_links()
        return result

    def _sync_links(self):
        """The order and the project of a sheet are the same mission: each takes the other's when it has none."""
        for m in self:
            if m.order_id and m.project_id and not m.order_id.project_id:
                m.order_id.sudo().project_id = m.project_id
            elif m.order_id and not m.project_id and m.order_id.project_id:
                m.project_id = m.order_id.project_id

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _quote_product(self):
        """The service of the days: a service sold, not expensed, whose tasks go to the project of the order
        (a product tied to a project or a template of its own would open a second project)."""
        domain = [('type', '=', 'service'), ('sale_ok', '=', True), ('can_be_expensed', '=', False),
                  ('service_tracking', '=', 'task_in_project'), ('project_id', '=', False),
                  ('project_template_id', '=', False)]
        Product = self.env['product.product']
        found = (Product.search(domain + [('name', 'ilike', 'assistance technique')], order='id desc', limit=1)
                 or Product.search(domain, order='id desc', limit=1))
        if found:
            return found
        # A database with no such service: the one delivered with the module.
        template = self.env.ref('mission_report.product_mission_days', raise_if_not_found=False)
        return template.product_variant_id if template and template.sudo().active else Product

    def action_create_order(self):
        """The quote of the mission: the customer, the project, the daily rate and the days of the sheet."""
        self.ensure_one()
        if self.order_id:
            raise UserError(_("This calculation already has an order."))
        if not self.partner_id:
            raise UserError(_("Choose the customer first."))
        if not self.project_id:
            self.action_create_project()
        days = sum(self.month_ids.mapped('working_days')) or round(self.days_per_month * max(self.duration_months, 1))
        product = self._quote_product()
        line = {'product_id': product.id, 'product_uom_qty': days, 'price_unit': self.daily_rate,
                'project_id': self.project_id.id} if product else {
            'name': self.name, 'product_uom_qty': days, 'price_unit': self.daily_rate}
        values = {
            'partner_id': self.partner_id.id, 'project_id': self.project_id.id, 'mission_volet_number': 1,
            'order_line': [(0, 0, line)]}
        # An order made from a sheet is the first phase of a mission (the next ones follow it).
        if 'greenengine_volets' in self.env['sale.order']._fields:
            values['greenengine_volets'] = True
        order = self.env['sale.order'].create(values)
        self.order_id = order
        return self.action_open_order()

    def action_open_profitability(self):
        self.ensure_one()
        if not self.project_id:
            raise UserError(_("Create the project first."))
        return self.project_id.with_context(active_id=self.project_id.id).project_update_all_action()

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
        self.project_id.invalidate_recordset(['mission_draft'])
        return self.action_open_project()

    def action_open_project(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'project.project', 'res_id': self.project_id.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': self.order_id.id,
                'view_mode': 'form', 'target': 'current'}


class MissionIgdRate(models.Model):
    """The scale of the long-distance allowances (URSSAF), by period of a mission, for a company."""
    _name = 'mission.igd.rate'
    _description = "Rate of the long-distance allowances"
    _order = 'company_id, sequence, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    sequence = fields.Integer(default=10)
    label = fields.Char(string="Period", required=True)
    month_from = fields.Integer(string="From month", default=1)
    month_to = fields.Integer(string="To month", help="0: until the end of the mission.")
    meal = fields.Monetary(string="Meal", currency_field='currency_id')
    lodging = fields.Monetary(
        string="Lodging and breakfast", currency_field='currency_id',
        help="Lodging and breakfast in the other departments.")
    total = fields.Monetary(
        string="Total per worked day", compute='_compute_total', currency_field='currency_id',
        help="Two meals and the lodging. Not due on leave, on the days back home, or when the "
             "travel is paid at its actual cost.")

    @api.depends('meal', 'lodging')
    def _compute_total(self):
        for line in self:
            line.total = 2 * line.meal + line.lodging


class MissionMarginIgd(models.Model):
    """The scale of the allowances of one margin calculation: a copy of the one of the company that can be
    edited for this mission only."""
    _name = 'mission.margin.igd'
    _description = "Rate of the allowances of a margin calculation"
    _order = 'margin_id, sequence, id'

    margin_id = fields.Many2one('mission.margin', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='margin_id.currency_id')
    sequence = fields.Integer(default=10)
    label = fields.Char(string="Period", required=True)
    month_from = fields.Integer(string="From month", default=1)
    month_to = fields.Integer(string="To month", help="0: until the end of the mission.")
    meal = fields.Monetary(string="Meal", currency_field='currency_id')
    lodging = fields.Monetary(string="Lodging and breakfast", currency_field='currency_id')
    total = fields.Monetary(string="Total per worked day", compute='_compute_total', currency_field='currency_id')

    @api.depends('meal', 'lodging')
    def _compute_total(self):
        for line in self:
            line.total = 2 * line.meal + line.lodging


class MissionCommissionRule(models.Model):
    """The commission rates of a status of salesperson (Settings): the sheet takes the rates of its status."""
    _name = 'mission.commission.rule'
    _description = "Commission rates of a status of salesperson"
    _order = 'company_id, sequence, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Status", required=True, translate=True)
    rate_sourcing = fields.Float(
        string="Sourcing of a candidate", digits=(16, 3),
        help="Sourcing (cooptation) of a candidate: first qualification and first talks.")
    rate_referral = fields.Float(
        string="Business referral", digits=(16, 3),
        help="Referral of a business: identification, qualification of the need and first negotiation.")
    rate_candidate = fields.Float(
        string="Full management, candidate side", digits=(16, 3),
        help="Sourcing, interviews, qualification, technical file, negotiation, HR follow-up, equipment.")
    rate_client = fields.Float(
        string="Full management, client side", digits=(16, 3),
        help="Needs, technical and financial proposal, negotiation, follow-up of the mission, reporting.")
    rate_full = fields.Float(
        string="Full management of the business", digits=(16, 3),
        help="Candidate side and client side together.")
    rate_team = fields.Float(
        string="Services managed by the collaborators", digits=(16, 3),
        help="Services managed by the collaborators under the direct responsibility of the person.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_igd_rate_ids = fields.One2many(related='company_id.mission_igd_rate_ids', readonly=False)
    mission_commission_rule_ids = fields.One2many(related='company_id.mission_commission_rule_ids', readonly=False)
    mission_employer_charge_rate = fields.Float(related='company_id.mission_employer_charge_rate', readonly=False)
    mission_employee_charge_rate = fields.Float(related='company_id.mission_employee_charge_rate', readonly=False)
    mission_overhead_rate = fields.Float(related='company_id.mission_overhead_rate', readonly=False)
    mission_commission_threshold_rate = fields.Float(
        related='company_id.mission_commission_threshold_rate', readonly=False)
    mission_commission_threshold_amount = fields.Monetary(
        related='company_id.mission_commission_threshold_amount', readonly=False)
    mission_commission_cap = fields.Float(related='company_id.mission_commission_cap', readonly=False)
    mission_show_commissions = fields.Boolean(related='company_id.mission_show_commissions', readonly=False)
    mission_salary_min = fields.Monetary(related='company_id.mission_salary_min', readonly=False)
    mission_salary_max = fields.Monetary(related='company_id.mission_salary_max', readonly=False)


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_igd_rate_ids = fields.One2many(
        'mission.igd.rate', 'company_id', string="Scale of the allowances",
        default=lambda self: self._default_igd_rates())
    mission_commission_rule_ids = fields.One2many(
        'mission.commission.rule', 'company_id', string="Commission rates by status")
    mission_employer_charge_rate = fields.Float(
        string="Employer charges", digits=(16, 3), default=0.457,
        help="Share of the gross salary: copied into each margin calculation, which cannot change it.")
    mission_employee_charge_rate = fields.Float(
        string="Employee charges", digits=(16, 3), default=0.23,
        help="Share of the gross salary, to work out the net salary of the consultant.")
    mission_overhead_rate = fields.Float(
        string="Fixed and indirect costs", digits=(16, 3), default=0.10,
        help="Share of the pay and charges: administration, premises, IT, insurance...")
    mission_commission_threshold_rate = fields.Float(
        string="Commission threshold (margin %)", default=0.20,
        help="A commission is due when the margin is over this share of the billing...")
    mission_commission_threshold_amount = fields.Monetary(
        string="Commission threshold (margin a month)", default=2000.0, currency_field='currency_id',
        help="...or over this amount a month.")
    mission_commission_cap = fields.Float(
        string="Cap (share of the gross margin of a business)", default=0.20,
        help="No more than this share of the gross margin of a business can be given as commissions.")
    mission_show_commissions = fields.Boolean(
        string="Show the commissions", default=True,
        help="Untick to hide the commissions of the margin calculations.")
    mission_salary_min = fields.Monetary(
        string="Lowest gross yearly salary", default=21876.0, currency_field='currency_id',
        help="The minimum wage of the country (the French SMIC is 21 876 € a year in 2026): the start of the "
             "salary slider of the margin calculations.")
    mission_salary_max = fields.Monetary(
        string="Highest gross yearly salary", default=80000.0, currency_field='currency_id',
        help="The end of the salary slider of the margin calculations.")

    @api.model
    def _default_igd_rates(self):
        """The 2026 scale: a meal and the lodging, by period of the mission."""
        rows = [
            (_("First 3 months"), 1, 3, 21.4, 56.8),
            (_("Month 4 to 24"), 4, 24, 18.2, 48.3),
            (_("Month 25 to 72"), 25, 72, 15.0, 39.8),
        ]
        return [(0, 0, {'sequence': i, 'label': label, 'month_from': start, 'month_to': end,
                        'meal': meal, 'lodging': lodging})
                for i, (label, start, end, meal, lodging) in enumerate(rows, 1)]

    def _mission_igd_scale_commands(self):
        """The scale of the company as the lines of a margin calculation."""
        self.ensure_one()
        rows = self.sudo().mission_igd_rate_ids.sorted(lambda line: (line.sequence, line.id))
        return [(0, 0, {'sequence': row.sequence, 'label': row.label, 'month_from': row.month_from,
                        'month_to': row.month_to, 'meal': row.meal, 'lodging': row.lodging}) for row in rows]

    def _default_commission_rules(self):
        """The rules of Green Engine (version B): the partners, then the account managers, business providers
        and co-optations placed under a partner."""
        self.ensure_one()
        return [
            {'company_id': self.id, 'sequence': 1, 'name': _("Partner"), 'rate_sourcing': 0.05,
             'rate_referral': 0.05, 'rate_candidate': 0.10, 'rate_client': 0.10, 'rate_full': 0.20,
             'rate_team': 0.04},
            {'company_id': self.id, 'sequence': 2, 'name': _("Account manager, business provider or co-optation"),
             'rate_sourcing': 0.04, 'rate_referral': 0.04, 'rate_candidate': 0.08, 'rate_client': 0.08,
             'rate_full': 0.16, 'rate_team': 0.0},
        ]

    def _mission_igd_ensure_rates(self):
        for company in self.filtered(lambda c: not c.mission_igd_rate_ids):
            company.mission_igd_rate_ids = company._default_igd_rates()

    @api.model
    def _mission_igd_init(self):
        """The scale of the allowances and the commission rates of the companies that have none yet (install and
        update)."""
        companies = self.search([])
        companies._mission_igd_ensure_rates()
        for company in companies.filtered(lambda c: not c.mission_commission_rule_ids):
            self.env['mission.commission.rule'].create(company._default_commission_rules())
        # The sheets made before the scale of a sheet existed.
        self.env['mission.margin'].sudo().with_context(active_test=False).search([])._ensure_igd_lines()
        for sheet in self.env['mission.margin'].sudo().with_context(active_test=False).search(
                [('commission_rule_id', '=', False)]):
            sheet.commission_rule_id = self.env['mission.commission.rule'].search(
                [('company_id', '=', sheet.company_id.id)], limit=1)


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
    mission_draft = fields.Boolean(
        string="Draft", compute='_compute_mission_draft', store=True,
        help="Project of a margin calculation whose order is not confirmed yet.")

    @api.depends('margin_ids', 'margin_ids.order_id.state')
    def _compute_mission_draft(self):
        for project in self:
            sheets = project.sudo().margin_ids
            project.mission_draft = bool(sheets) and not any(
                order.state == 'sale' for order in sheets.order_id)

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
