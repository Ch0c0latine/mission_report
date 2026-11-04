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

    # ---- Cost of the person -------------------------------------------------------------------
    cost_origin = fields.Selection(
        [('employee', "Employee"), ('freelance', "Freelance")],
        string="Cost of the person", default='employee', required=True)
    gross_salary = fields.Monetary(string="Gross yearly salary", default=40000.0)
    salary_preset = fields.Selection(
        lambda self: self._salary_presets(), string="Gross yearly salary", compute='_compute_salary_preset',
        store=True, readonly=False, help="Pick a usual salary, or type the exact amount below.")
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
    daily_cost_worked = fields.Monetary(
        string="Daily amount", help="Paid to the employee for each day worked, e.g. a daily allowance of 55 €.")
    daily_cost_reason = fields.Char(string="Reason of the daily amount", help="e.g. daily allowance, travel.")
    mileage_monthly = fields.Monetary(string="Mileage allowances a month")
    expenses_monthly = fields.Monetary(string="Expenses a month")
    training_yearly = fields.Monetary(string="Training depreciation a year")
    ppe_yearly = fields.Monetary(string="PPE a year")
    equipment_yearly = fields.Monetary(string="Equipment (PC, tools, phone) a year", default=200.0)
    other_yearly = fields.Monetary(string="Other costs a year")

    # ---- Price --------------------------------------------------------------------------------
    margin_wanted = fields.Integer(
        string="Margin wanted (%)", default=20,
        help="Move the slider: the daily rate follows the margin wanted (rounded up to 5 €) when the costs "
             "change. Type a daily rate to set it by hand.")
    rate_manual = fields.Boolean(string="Rate typed by hand", default=False)
    daily_rate = fields.Monetary(string="Daily rate sold (TJM)", tracking=True)
    rebilled_daily = fields.Monetary(string="Expenses re-invoiced per day")
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

    igd_lodging = fields.Boolean(string="Lodging")
    igd_lunch = fields.Boolean(string="Lunch")
    igd_dinner = fields.Boolean(string="Dinner")
    igd_monthly_reason = fields.Char(string="Reason of the monthly amount", help="e.g. agreed with the customer.")
    igd_monthly_amount = fields.Monetary(
        string="Monthly amount",
        help="0: every day worked gets what is ticked, at the rates of the scale (Settings). "
             "Otherwise, the agreed amount of allowances a month (e.g. 1 000 € a month).")
    igd_rebilled = fields.Boolean(
        string="Allowances re-invoiced to the customer",
        help="The allowances are added to the expenses re-invoiced per day.")
    igd_rate_ids = fields.One2many(related='company_id.mission_igd_rate_ids', string="Scale of the allowances")
    month_ids = fields.One2many('mission.margin.month', 'margin_id', string="Monthly billing forecast")

    # ---- Results ------------------------------------------------------------------------------
    days_per_year = fields.Float(string="Days worked a year", compute='_compute_results', digits=(16, 2))
    days_per_month = fields.Float(string="Days worked a month", compute='_compute_results', digits=(16, 2))
    base_cost = fields.Monetary(string="Cost of the person a year", compute='_compute_results')
    overhead_cost = fields.Monetary(string="Fixed and indirect costs a year", compute='_compute_results')
    loaded_cost = fields.Monetary(string="Loaded cost a year", compute='_compute_results')
    other_costs = fields.Monetary(string="Total other costs", compute='_compute_results')
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
    commission_full = fields.Monetary(string="Full management", compute='_compute_results')
    commission_management = fields.Monetary(string="Management of the service or sales", compute='_compute_results')
    commission_referral = fields.Monetary(string="Referral", compute='_compute_results')
    commission_full_potential = fields.Monetary(compute='_compute_results')
    commission_management_potential = fields.Monetary(compute='_compute_results')
    commission_referral_potential = fields.Monetary(compute='_compute_results')
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
        'daily_cost_calendar', 'daily_cost_worked', 'mileage_monthly', 'expenses_monthly', 'training_yearly',
        'ppe_yearly', 'equipment_yearly', 'other_yearly', 'daily_rate', 'rebilled_daily', 'duration_months',
        'employee_charge_rate', 'target_amount_1', 'target_amount_2', 'target_rate_1', 'target_rate_2',
        'commission_threshold_rate', 'commission_threshold_amount', 'commission_rate_full',
        'commission_rate_management', 'commission_rate_referral', 'igd_lodging', 'igd_lunch', 'igd_dinner',
        'igd_monthly_amount', 'igd_rebilled', 'company_id.mission_igd_rate_ids.month_from',
        'company_id.mission_igd_rate_ids.month_to', 'company_id.mission_igd_rate_ids.meal',
        'company_id.mission_igd_rate_ids.lodging')
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
            # A freelance bills his expenses in his daily rate: only the other costs of the sheet remain.
            igd = 0.0 if freelance else m._igd_per_day()
            others = m.other_yearly if freelance else (
                m.daily_cost_calendar * 365 + m.daily_cost_worked * days + m.mileage_monthly * 12
                + m.expenses_monthly * 12 + m.training_yearly + m.ppe_yearly + m.equipment_yearly
                + m.other_yearly + igd * days)
            rebilled = m.rebilled_daily + (igd if m.igd_rebilled else 0.0)
            total = base + overhead + others
            revenue = (m.daily_rate + rebilled) * days
            m.igd_daily = igd
            m.igd_month = igd * days / 12
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
            fees = 0.0 if freelance else m.daily_cost_calendar * 365 + m.daily_cost_worked * days
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
    # Selectors: salary, allowances, margin wanted
    # ------------------------------------------------------------------

    SALARY_STEP = 2500
    SALARY_MIN = 30000
    SALARY_MAX = 80000

    @api.model
    def _salary_presets(self):
        steps = range(self.SALARY_MIN, self.SALARY_MAX + 1, self.SALARY_STEP)
        return [(str(value), "{:,} €".format(value).replace(",", " ")) for value in steps]

    @api.depends('gross_salary')
    def _compute_salary_preset(self):
        for m in self:
            value = int(round(m.gross_salary)) if m.gross_salary else 0
            known = self.SALARY_MIN <= value <= self.SALARY_MAX and value % self.SALARY_STEP == 0                 and value == m.gross_salary
            m.salary_preset = str(value) if known else False

    @api.onchange('salary_preset')
    def _onchange_salary_preset(self):
        if self.salary_preset:
            self.gross_salary = float(self.salary_preset)
            self._follow_margin()

    def _igd_per_day(self):
        """Allowances per worked day: the amount agreed a month, or what is ticked on every day worked.

        With every day worked populated, the scale (Settings) gives the rates by month of the mission.
        """
        self.ensure_one()
        if self.igd_monthly_amount:
            days = 365 - self.weekend_days - self.public_holidays - self.paid_leave_days - self.rtt_days
            return self.igd_monthly_amount * 12 / days if days > 0 else 0.0
        meals = int(bool(self.igd_lunch)) + int(bool(self.igd_dinner))
        if not (meals or self.igd_lodging):
            return 0.0
        months = max(int(round(self.duration_months)), 1)
        rates = self.company_id.sudo().mission_igd_rate_ids.sorted(lambda line: (line.sequence, line.id))
        total = 0.0
        for month in range(1, months + 1):
            line = next((line for line in rates
                         if line.month_from <= month and (not line.month_to or month <= line.month_to)), None)
            if line:
                total += meals * line.meal + (line.lodging if self.igd_lodging else 0.0)
        return total / months

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
        'daily_cost_calendar', 'daily_cost_worked', 'mileage_monthly', 'expenses_monthly', 'training_yearly',
        'ppe_yearly', 'equipment_yearly', 'other_yearly', 'rebilled_daily', 'duration_months', 'igd_lodging',
        'igd_lunch', 'igd_dinner', 'igd_monthly_amount', 'igd_rebilled', 'margin_wanted')

    def _follow_margin(self):
        for m in self:
            if not m.rate_manual:
                m.with_context(margin_follow=True).daily_rate = m._rate_for_margin(m.margin_wanted / 100.0)

    @api.onchange(*COST_FIELDS)
    def _onchange_follow_margin(self):
        self._follow_margin()

    @api.onchange('margin_wanted')
    def _onchange_margin_wanted(self):
        # Moving the slider gives the control back to the margin.
        self.rate_manual = False
        self._follow_margin()

    @api.onchange('daily_rate')
    def _onchange_daily_rate(self):
        # Typed by hand: unless it is the rate the margin wanted gave (the sheet sets it itself).
        if not self.rate_manual and self.daily_rate != self._rate_for_margin(self.margin_wanted / 100.0):
            self.rate_manual = True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'daily_rate' in vals and 'rate_manual' not in vals:
                vals['rate_manual'] = True
        records = super().create(vals_list)
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


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_igd_rate_ids = fields.One2many(related='company_id.mission_igd_rate_ids', readonly=False)


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_igd_rate_ids = fields.One2many(
        'mission.igd.rate', 'company_id', string="Scale of the allowances",
        default=lambda self: self._default_igd_rates())

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

    def _mission_igd_ensure_rates(self):
        for company in self.filtered(lambda c: not c.mission_igd_rate_ids):
            company.mission_igd_rate_ids = company._default_igd_rates()

    @api.model
    def _mission_igd_init(self):
        """The scale of the allowances of the companies that have none yet (install and update)."""
        self.search([])._mission_igd_ensure_rates()


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
