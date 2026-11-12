# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Margin calculation: the figures of the spreadsheet it replaces (consultant at 40 000 € + 55 € a day)."""
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import AccessError


@tagged('post_install', '-at_install', 'mission_report')
class TestMargin(TransactionCase):

    def _sheet(self, **values):
        data = {'name': "Test", 'gross_salary': 40000.0, 'daily_cost_worked': 55.0, 'daily_rate': 500.0}
        data.update(values)
        return self.env['mission.margin'].create(data)

    def test_the_spreadsheet_figures(self):
        sheet = self._sheet()
        self.assertEqual(sheet.days_per_year, 218)
        self.assertAlmostEqual(sheet.loaded_cost, 40000 * 1.457 * 1.10, places=2)
        self.assertAlmostEqual(sheet.total_cost, 76298.0, places=2)
        self.assertAlmostEqual(sheet.revenue, 109000.0, places=2)
        self.assertAlmostEqual(sheet.margin, 32702.0, places=2)
        self.assertAlmostEqual(sheet.margin_month, 2725.17, places=2)
        self.assertAlmostEqual(sheet.margin_day, 150.01, places=2)
        self.assertAlmostEqual(sheet.margin_rate, 0.30002, places=4)
        self.assertAlmostEqual(sheet.margin_duration, 32702.0, places=2)
        self.assertAlmostEqual(sheet.rate_target_1, 570.17, places=2)
        self.assertAlmostEqual(sheet.rate_target_2, 460.08, places=2)
        self.assertAlmostEqual(sheet.rate_target_rate_1, 499.99, places=2)
        self.assertAlmostEqual(sheet.rate_target_rate_2, 437.49, places=2)
        self.assertAlmostEqual(sheet.net_salary_day, 141.28, places=2)
        self.assertAlmostEqual(sheet.net_income_day, 196.28, places=2)
        self.assertAlmostEqual(sheet.net_income_month, 3565.83, places=2)

    def test_commissions_need_the_margin_threshold(self):
        sheet = self._sheet()
        self.assertTrue(sheet.commission_eligible)
        self.assertAlmostEqual(sheet.commission_full, 545.03, places=2)
        self.assertAlmostEqual(sheet.commission_candidate, 272.52, places=2)
        self.assertAlmostEqual(sheet.commission_client, 272.52, places=2)
        self.assertAlmostEqual(sheet.commission_referral, 136.26, places=2)
        poor = self._sheet(daily_rate=400.0)
        self.assertFalse(poor.commission_eligible)
        self.assertEqual(poor.commission_full, 0.0)

    def test_a_freelance_replaces_the_salary(self):
        sheet = self._sheet(cost_origin='freelance', freelance_daily_rate=400.0, gross_salary=0.0,
                            daily_cost_worked=0.0)
        self.assertAlmostEqual(sheet.base_cost, 400.0 * 218, places=2)
        # The expenses of a freelance are in his daily rate: no allowance, no equipment, no net income.
        self.assertAlmostEqual(sheet.total_cost, 400.0 * 218 * 1.10, places=2)
        self.assertEqual(sheet.net_income_month, 0.0)
        employee_costs = self._sheet(cost_origin='freelance', freelance_daily_rate=400.0, daily_cost_worked=60.0,
                                     igd_lodging=True, igd_lunch=True, igd_dinner=True, mileage_monthly=300.0)
        self.assertAlmostEqual(employee_costs.total_cost, sheet.total_cost, places=2)

    def test_the_margin_wanted_gives_the_daily_rate(self):
        # Without a daily rate typed, the 20 % margin wanted by default sets it, rounded up to 5 euros.
        sheet = self.env['mission.margin'].create({'name': "Auto", 'gross_salary': 40000.0, 'daily_cost_worked': 55.0})
        self.assertEqual(sheet.margin_wanted, 20)
        self.assertFalse(sheet.rate_manual)
        self.assertEqual(sheet.daily_rate % 5, 0)
        self.assertGreaterEqual(sheet.margin_rate, 0.20)
        self.assertLess(sheet.margin_rate, 0.21)
        sheet.write({'margin_wanted': 30})
        self.assertGreaterEqual(sheet.margin_rate, 0.30)
        self.assertLess(sheet.margin_rate, 0.31)
        # The costs change: the daily rate follows the margin wanted.
        before = sheet.daily_rate
        sheet.gross_salary = 50000.0
        self.assertGreater(sheet.daily_rate, before)
        self.assertGreaterEqual(sheet.margin_rate, 0.30)
        # A daily rate typed by hand stays.
        sheet.daily_rate = 700.0
        self.assertTrue(sheet.rate_manual)
        sheet.gross_salary = 60000.0
        self.assertEqual(sheet.daily_rate, 700.0)

    def test_the_name_fills_itself_until_it_is_written(self):
        partner = self.env['res.partner'].create({'name': "Client nom"})
        sheet = self.env['mission.margin'].create({'partner_id': partner.id, 'consultant': "Alex"})
        self.assertTrue(sheet.name)
        self.assertIn("Client nom", sheet.name)
        self.assertIn("Alex", sheet.name)
        self.assertIn("12", sheet.name)
        before = sheet.name
        sheet.consultant = "Sam"
        self.assertIn("Sam", sheet.name)
        self.assertNotEqual(sheet.name, before)
        # A name written by hand stays.
        sheet.name = "Mon nom"
        sheet.consultant = "Robin"
        self.assertEqual(sheet.name, "Mon nom")
        empty = self.env['mission.margin'].create({})
        self.assertTrue(empty.name)

    def test_the_name_follows_the_customer_in_a_form(self):
        partner = self.env['res.partner'].create({'name': "Client formulaire"})
        from odoo.tests import Form
        alex = self.env['res.partner'].create({'name': "Alex"})
        with Form(self.env['mission.margin']) as form:
            form.partner_id = partner
            form.consultant_id = alex
        self.assertIn("Client formulaire", form.record.name)
        self.assertIn("Alex", form.record.name)

    def test_the_allowances_total_a_month(self):
        sheet = self._sheet(igd_lodging=True, igd_lunch=True, duration_months=2.0, igd_scale_choice='0')
        self.assertAlmostEqual(sheet.igd_month, (21.4 + 56.8) * 218 / 12, delta=0.05)

    def test_the_salary_slider_goes_from_the_minimum_wage_to_the_limit_of_the_company(self):
        sheet = self._sheet()
        company = self.env.company
        self.assertEqual(sheet.salary_min, company.mission_salary_min)
        self.assertEqual(sheet.salary_max, company.mission_salary_max)
        self.assertAlmostEqual(company.mission_salary_min, 21876.0)
        self.assertAlmostEqual(company.mission_salary_max, 80000.0)

    def test_the_allowances_follow_the_meals_and_the_lodging(self):
        sheet = self._sheet(igd_lodging=True, igd_lunch=True, igd_dinner=True, duration_months=3.0,
                            igd_scale_choice='0')
        self.assertAlmostEqual(sheet.igd_daily, 2 * 21.4 + 56.8, delta=0.01)
        sheet.duration_months = 12.0
        # 3 months at the first rate, 9 at the second: the average per day worked.
        expected = (3 * (2 * 21.4 + 56.8) + 9 * (2 * 18.2 + 48.3)) / 12
        self.assertAlmostEqual(sheet.igd_daily, expected, delta=0.01)
        sheet.igd_dinner = False
        sheet.igd_lodging = False
        self.assertAlmostEqual(sheet.igd_daily, (3 * 21.4 + 9 * 18.2) / 12, delta=0.01)
        cost = self._sheet(daily_rate=500.0).total_cost
        with_igd = self._sheet(daily_rate=500.0, igd_lunch=True)
        self.assertGreater(with_igd.total_cost, cost)
        rebilled = self._sheet(daily_rate=500.0, igd_lunch=True, igd_rebilled=True)
        self.assertGreater(rebilled.price_per_day, 500.0)

    def test_the_quote_is_created_from_the_sheet(self):
        partner = self.env['res.partner'].create({'name': "Client test marge"})
        sheet = self._sheet(partner_id=partner.id, start_date='2031-05-01', duration_months=2.0)
        sheet.action_generate_months()
        action = sheet.action_create_order()
        order = sheet.order_id
        self.assertEqual(action['res_id'], order.id)
        self.assertEqual(order.partner_id, partner)
        self.assertEqual(order.project_id, sheet.project_id)
        self.assertEqual(sum(order.order_line.mapped('product_uom_qty')), 19 + 20)
        self.assertEqual(order.order_line.price_unit, 500.0)

    def test_the_payslip_cost_replaces_the_charges(self):
        sheet = self._sheet(payslip_monthly_cost=5000.0)
        self.assertAlmostEqual(sheet.base_cost, 60000.0, places=2)

    def test_the_scale_of_a_sheet_is_a_copy_of_the_one_of_the_company(self):
        rates = self.env.company.mission_igd_rate_ids
        self.assertEqual(len(rates), 3)
        self.assertAlmostEqual(rates[0].total, 2 * 21.4 + 56.8, places=2)
        self.assertAlmostEqual(rates[2].total, 69.8, places=2)
        sheet = self._sheet(igd_lunch=True, duration_months=2.0, igd_scale_choice='0')
        self.assertEqual(len(sheet.igd_line_ids), 3)
        self.assertAlmostEqual(sheet.igd_daily, 21.4, delta=0.01)
        # The sheet edits its own scale: the reference of the company does not move.
        sheet.igd_line_ids[0].meal = 25.0
        self.assertAlmostEqual(sheet.igd_daily, 25.0, delta=0.01)
        self.assertAlmostEqual(rates[0].meal, 21.4)
        # And a new reference does not move the sheets already made.
        rates[0].meal = 30.0
        sheet.invalidate_recordset()
        self.assertAlmostEqual(sheet.igd_daily, 25.0, delta=0.01)
        self.assertAlmostEqual(self._sheet(igd_lunch=True, duration_months=2.0, igd_scale_choice='0').igd_daily,
                               30.0, delta=0.01)
        sheet.action_reset_igd_scale()
        self.assertAlmostEqual(sheet.igd_daily, 30.0, delta=0.01)

    def test_one_period_of_the_scale_applies_to_every_month(self):
        # By default, the rates of month 4 to 24 for the whole mission: nothing changes at the fourth month.
        sheet = self._sheet(igd_lodging=True, igd_lunch=True, igd_dinner=True, duration_months=12.0)
        self.assertEqual(sheet.igd_scale_choice, '2')
        self.assertAlmostEqual(sheet.igd_daily, 2 * 18.2 + 48.3, delta=0.01)
        sheet.duration_months = 36.0
        self.assertAlmostEqual(sheet.igd_daily, 2 * 18.2 + 48.3, delta=0.01)
        sheet.igd_scale_choice = '3'
        self.assertAlmostEqual(sheet.igd_daily, 2 * 15.0 + 39.8, delta=0.01)
        sheet.igd_scale_choice = '1'
        self.assertAlmostEqual(sheet.igd_daily, 2 * 21.4 + 56.8, delta=0.01)
        sheet.igd_scale_choice = '0'
        self.assertLess(sheet.igd_daily, 2 * 21.4 + 56.8)
        self.assertGreater(sheet.igd_daily, 2 * 15.0 + 39.8)

    def test_a_fixed_monthly_amount_is_not_a_long_distance_allowance(self):
        sheet = self._sheet(igd_lodging=True, igd_lunch=True, igd_dinner=True)
        before = sheet.total_cost
        igd = sheet.igd_daily
        sheet.fixed_monthly_amount = 300.0
        self.assertAlmostEqual(sheet.igd_daily, igd, places=4)
        self.assertAlmostEqual(sheet.total_cost, before + 300.0 * 12, places=2)
        # It is paid to the employee: it is in the net income.
        self.assertAlmostEqual(sheet.daily_fees_month, (55.0 * 218 + 300.0 * 12) / 12, places=2)

    def test_the_other_costs_by_period(self):
        sheet = self._sheet(daily_cost_worked=0.0)
        before = sheet.total_cost
        sheet.write({'other_worked_daily': 10.0, 'daily_cost_calendar': 2.0, 'expenses_monthly': 100.0,
                     'other_yearly': 500.0})
        self.assertAlmostEqual(sheet.total_cost, before + 10.0 * 218 + 2.0 * 365 + 100.0 * 12 + 500.0, places=2)
        # They are costs of the company, not amounts paid to the consultant.
        self.assertAlmostEqual(sheet.net_income_month, sheet.net_salary_month, places=2)

    def test_the_expenses_re_invoiced_per_month_add_to_the_billing(self):
        sheet = self._sheet()
        before = sheet.revenue
        sheet.rebilled_monthly = 100.0
        self.assertAlmostEqual(sheet.revenue, before + 1200.0, places=2)

    def test_the_rates_of_the_company_are_copied_and_cannot_be_changed_by_the_sheet(self):
        company = self.env.company
        old = self._sheet()
        self.assertAlmostEqual(old.employer_charge_rate, 0.457)
        self.assertAlmostEqual(old.overhead_rate, 0.10)
        self.assertAlmostEqual(old.employee_charge_rate, 0.23)
        company.mission_employer_charge_rate = 0.50
        self.assertAlmostEqual(self._sheet().employer_charge_rate, 0.50)
        self.assertAlmostEqual(old.employer_charge_rate, 0.457)
        fields_get = self.env['mission.margin'].fields_get(
            ['employer_charge_rate', 'overhead_rate', 'employee_charge_rate', 'commission_threshold_rate',
             'commission_threshold_amount'], attributes=['readonly'])
        self.assertTrue(all(field['readonly'] for field in fields_get.values()))

    def test_the_commission_rates_follow_the_status_of_the_salesperson(self):
        company = self.env.company
        junior = self.env['mission.commission.rule'].create({
            'company_id': company.id, 'name': "Junior", 'rate_full': 0.10, 'rate_candidate': 0.05,
            'rate_client': 0.05, 'rate_sourcing': 0.02, 'rate_referral': 0.02})
        sheet = self._sheet()
        self.assertAlmostEqual(sheet.commission_rate_full, 0.20)
        full = sheet.commission_full
        sheet.commission_rule_id = junior
        self.assertAlmostEqual(sheet.commission_full, full / 2, places=2)
        self.assertAlmostEqual(sheet.commission_referral, sheet.margin_month * 0.02, places=2)
        company.mission_show_commissions = False
        self.assertFalse(sheet.show_commissions)

    def test_the_rules_of_the_company_give_two_statuses(self):
        rules = self.env['mission.commission.rule'].search([('company_id', '=', self.env.company.id)])
        by_rate = {rule.rate_full: rule for rule in rules}
        partner, account_manager = by_rate[0.20], by_rate[0.16]
        self.assertEqual((partner.rate_sourcing, partner.rate_referral, partner.rate_candidate, partner.rate_client,
                          partner.rate_team), (0.05, 0.05, 0.10, 0.10, 0.04))
        self.assertEqual((account_manager.rate_sourcing, account_manager.rate_referral, account_manager.rate_candidate,
                          account_manager.rate_client, account_manager.rate_team), (0.04, 0.04, 0.08, 0.08, 0.0))
        sheet = self._sheet()
        self.assertEqual(sheet.commission_rule_id, partner)
        self.assertAlmostEqual(sheet.commission_team, sheet.margin_month * 0.04, places=2)
        self.assertAlmostEqual(sheet.commission_cap_amount, sheet.margin_month * 0.20, places=2)
        sheet.commission_rule_id = account_manager
        self.assertAlmostEqual(sheet.commission_full, sheet.margin_month * 0.16, places=2)
        self.assertEqual(sheet.commission_team, 0.0)
        # Under the thresholds, nothing is due.
        poor = self._sheet(daily_rate=400.0)
        self.assertEqual(poor.commission_cap_amount, 0.0)

    def test_the_calendar_costs_have_their_own_part_of_the_ring(self):
        sheet = self._sheet(daily_cost_calendar=3.0, other_yearly=600.0)
        parts = {part['key']: part['value'] for part in sheet.breakdown['segments']}
        self.assertAlmostEqual(parts['calendar'], 3.0 * 365 / 12, places=2)
        self.assertAlmostEqual(parts['other'], (600.0 + 200.0) / 12, places=2)
        self.assertAlmostEqual(sum(parts.values()), sheet.revenue / 12, places=2)
        keys = [part['key'] for part in sheet.breakdown['segments']]
        self.assertLess(keys.index('allowances'), keys.index('calendar'))
        self.assertLess(keys.index('calendar'), keys.index('overhead'))
        self.assertNotIn('calendar', {part['key'] for part in self._sheet().breakdown['segments']})

    def test_each_other_charge_has_a_note(self):
        sheet = self._sheet(other_yearly=100.0, other_yearly_note="Insurance", daily_cost_calendar=2.0,
                            daily_cost_calendar_note="Car", rebilled_monthly_note="Rent")
        self.assertEqual(sheet.other_yearly_note, "Insurance")
        for name in ('other_worked_daily', 'daily_cost_calendar', 'expenses_monthly', 'mileage_monthly',
                     'training_yearly', 'ppe_yearly', 'equipment_yearly', 'other_yearly', 'rebilled_daily',
                     'rebilled_monthly'):
            self.assertIn(name + '_note', self.env['mission.margin']._fields)

    def test_the_allowances_can_be_paid_on_the_calendar_days(self):
        # Lodging at the rate of month 4 to 24 (48.30), on every day of the year instead of the days worked.
        worked = self._sheet(igd_lodging=True)
        self.assertAlmostEqual(worked.igd_month, 48.3 * 218 / 12, delta=0.01)
        calendar = self._sheet(igd_lodging=True, igd_lodging_basis='calendar')
        self.assertAlmostEqual(calendar.igd_month, 48.3 * 365 / 12, delta=0.01)
        self.assertAlmostEqual(calendar.igd_daily, 48.3 * 365 / 218, delta=0.01)
        # Each allowance has its own basis: the meals stay on the days worked.
        mixed = self._sheet(igd_lodging=True, igd_lunch=True, igd_lodging_basis='calendar')
        self.assertAlmostEqual(mixed.igd_month, (48.3 * 365 + 18.2 * 218) / 12, delta=0.01)
        meals = self._sheet(igd_lunch=True, igd_dinner=True, igd_meal_basis='calendar')
        self.assertAlmostEqual(meals.igd_month, 2 * 18.2 * 365 / 12, delta=0.01)

    def test_the_expat_allowance_is_a_free_amount(self):
        sheet = self._sheet()
        before = sheet.total_cost
        sheet.write({'igd_expat': True, 'igd_expat_amount': 30.0})
        self.assertAlmostEqual(sheet.total_cost, before + 30.0 * 218, places=2)
        self.assertAlmostEqual(sheet.igd_daily, 30.0, places=2)
        sheet.igd_expat_basis = 'calendar'
        self.assertAlmostEqual(sheet.igd_month, 30.0 * 365 / 12, delta=0.01)
        sheet.igd_expat = False
        self.assertEqual(sheet.igd_daily, 0.0)

    def test_the_margin_slider_follows_the_daily_rate_typed_or_slid(self):
        from odoo.tests import Form
        with Form(self.env['mission.margin']) as form:
            form.gross_salary = 40000.0
            form.daily_rate = 600.0
            self.assertTrue(form.rate_manual)
            self.assertEqual(form.margin_wanted, min(max(int(round(form.margin_rate * 100)), 0), 90))
            self.assertGreater(form.margin_wanted, 20)
            # Moving the margin slider gives the control back to the margin.
            form.margin_wanted = 15
            self.assertFalse(form.rate_manual)
            self.assertEqual(form.margin_wanted, 15)

    def test_a_mission_by_the_day_follows_the_days_planned(self):
        """14 days of intervention over 6 months: a day costs and earns what it did, the month and the mission
        follow the days planned."""
        full = self._sheet(duration_months=6.0)
        daily = self._sheet(duration_months=6.0, mission_days=14.0)
        self.assertAlmostEqual(daily.margin_day, full.margin_day, places=4)
        self.assertAlmostEqual(daily.cost_per_day, full.cost_per_day, places=4)
        self.assertAlmostEqual(daily.days_per_month, 14 / 6, delta=0.05)
        self.assertAlmostEqual(daily.mission_days_total, 14.0, places=4)
        self.assertAlmostEqual(daily.margin_month, daily.margin_day * 14 / 6, delta=0.05)
        self.assertAlmostEqual(daily.margin_duration, daily.margin_day * 14, delta=0.05)
        self.assertAlmostEqual(daily.total_cost_month, daily.cost_per_day * 14 / 6, delta=0.05)
        self.assertAlmostEqual(daily.net_income_month, daily.net_income_day * 14 / 6, delta=0.05)
        # The ring is the month of this mission: the parts add up to its billing.
        parts = {part['key']: part['value'] for part in daily.breakdown['segments']}
        self.assertAlmostEqual(daily.breakdown['total'], daily.price_per_day * 14 / 6, delta=0.05)
        self.assertAlmostEqual(sum(parts.values()), daily.price_per_day * 14 / 6, delta=0.05)
        # The rate for a margin of the month follows the days planned.
        self.assertGreater(daily.rate_target_2, daily.cost_per_day)
        # The months share the days planned; the order is for the days planned.
        daily.start_date = '2031-05-01'
        daily.action_generate_months()
        self.assertEqual(daily.month_ids.mapped('days_planned'), [3.0, 3.0, 2.0, 2.0, 2.0, 2.0])
        self.assertAlmostEqual(daily.forecast_days, 14.0)
        self.assertAlmostEqual(daily.forecast_revenue, daily.price_per_day * 14, delta=0.5)
        partner = self.env['res.partner'].create({'name': "Client journalier"})
        daily.partner_id = partner
        daily.action_create_order()
        self.assertEqual(sum(daily.order_id.order_line.mapped('product_uom_qty')), 14.0)
        # Full time is unchanged.
        self.assertAlmostEqual(full.days_per_month, 218 / 12, delta=0.05)
        self.assertAlmostEqual(full.margin_duration, full.margin_day * 218 / 12 * 6, delta=0.5)

    def test_a_fixed_price_is_the_daily_rate_of_the_days_estimated(self):
        sheet = self._sheet(billing_mode='forfait', mission_days=10.0, duration_months=2.0)
        self.assertAlmostEqual(sheet.fixed_price, sheet.daily_rate * 10, delta=0.05)
        self.assertAlmostEqual(sheet.margin_duration, sheet.margin_day * 10, delta=0.05)
        # More than the days estimated, the margin is gone: the days the price pays.
        self.assertAlmostEqual(sheet.breakeven_days, sheet.fixed_price / sheet.cost_per_day, delta=0.05)
        self.assertGreater(sheet.breakeven_days, 10.0)
        # Typing the price gives the equivalent daily rate.
        sheet.fixed_price = 6000.0
        self.assertAlmostEqual(sheet.daily_rate, 600.0, delta=0.05)
        self.assertAlmostEqual(sheet.fixed_price, 6000.0, delta=0.05)
        # In an unsaved form too.
        from odoo.tests import Form
        with Form(self.env['mission.margin']) as form:
            form.billing_mode = 'forfait'
            form.mission_days = 8.0
            form.fixed_price = 4000.0
            self.assertAlmostEqual(form.daily_rate, 500.0, delta=0.05)
        # The quote is one line at the fixed price.
        partner = self.env['res.partner'].create({'name': "Client au forfait"})
        sheet.partner_id = partner
        sheet.action_create_order()
        line = sheet.order_id.order_line
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_uom_qty, 1.0)
        self.assertAlmostEqual(line.price_unit, 6000.0, delta=0.05)
        self.assertIn("10", line.name)
        # Time and materials stays by the day.
        regie = self._sheet(mission_days=10.0, partner_id=partner.id)
        regie.action_create_order()
        self.assertEqual(regie.order_id.order_line.product_uom_qty, 10.0)

    def test_the_actual_profitability_opens_the_project_of_the_sheet(self):
        sheet = self._sheet()
        sheet.action_create_project()
        action = sheet.action_open_profitability()
        self.assertEqual(action['context']['active_id'], sheet.project_id.id)
        self.assertNotEqual(action['context']['active_id'], sheet.id)
        self.assertEqual(action['context']['active_model'], 'project.project')

    def test_the_status_of_a_calculation_follows_its_project_and_its_order(self):
        partner = self.env['res.partner'].create({'name': "Client statut"})
        sheet = self._sheet(partner_id=partner.id)
        self.assertEqual(sheet.state, 'draft')
        sheet.action_create_project()
        self.assertEqual(sheet.state, 'project')
        sheet.action_create_order()
        self.assertEqual(sheet.state, 'quote')
        sheet.order_id.action_confirm()
        self.assertEqual(sheet.state, 'order')

    def test_a_gap_with_the_order_is_shown_and_never_written_by_itself(self):
        from odoo.exceptions import UserError
        partner = self.env['res.partner'].create({'name': "Client écart"})
        sheet = self._sheet(partner_id=partner.id, daily_rate=500.0)
        sheet.action_create_order()
        self.assertFalse(sheet.order_gap)
        self.assertAlmostEqual(sheet.order_price, 500.0)
        sheet.daily_rate = 520.0
        self.assertTrue(sheet.order_gap)
        self.assertIn("500", sheet.order_gap_short)
        self.assertIn("520", sheet.order_gap_text)
        # The order does not move by itself.
        self.assertAlmostEqual(sheet.order_id.order_line.price_unit, 500.0)
        # Back to the conditions of the order.
        sheet.action_restore_order_conditions()
        self.assertAlmostEqual(sheet.daily_rate, 500.0)
        self.assertFalse(sheet.order_gap)
        # A change recorded in a confirmed order needs its note.
        sheet.order_id.action_confirm()
        sheet.daily_rate = 550.0
        wizard = self.env['mission.margin.condition.wizard'].create({'margin_id': sheet.id, 'reason': 'client'})
        self.assertTrue(wizard.note_required)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.note = "Renegotiated with the customer on 5 November"
        wizard.action_confirm()
        self.assertAlmostEqual(sheet.order_id.order_line.price_unit, 550.0)
        self.assertFalse(sheet.order_gap)
        bodies = " ".join(sheet.order_id.message_ids.mapped('body'))
        self.assertIn("Renegotiated with the customer", bodies)

    def test_the_totals_are_those_of_the_mission(self):
        sheet = self._sheet(duration_months=6.0, mission_days=14.0)
        self.assertAlmostEqual(sheet.mission_days_total, 14.0, delta=0.01)
        self.assertAlmostEqual(sheet.mission_cost, sheet.cost_per_day * 14, delta=0.5)
        self.assertAlmostEqual(sheet.mission_revenue, sheet.price_per_day * 14, delta=0.5)
        self.assertAlmostEqual(sheet.mission_revenue - sheet.mission_cost, sheet.margin_duration, delta=1.0)

    def _deal(self, rate=480.0, days=100.0, project_partner=True):
        """A customer, a project and an order of the project, as the sales people have them."""
        partner = self.env['res.partner'].create({'name': "Client affaire", 'is_company': True})
        project = self.env['project.project'].create({'name': "Affaire", 'partner_id': partner.id})
        product = self.env['mission.margin']._quote_product()
        expenses = self.env['product.product'].create({
            'name': "Frais à refacturer", 'type': 'service', 'can_be_expensed': True})
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'project_id': project.id,
            'order_line': [
                (0, 0, {'product_id': product.id, 'product_uom_qty': days, 'price_unit': rate,
                        'project_id': project.id}),
                # The expenses re-invoiced are not days: they must not count in the conditions.
                (0, 0, {'product_id': expenses.id, 'product_uom_qty': 2000.0, 'price_unit': 1.0})]})
        return partner, project, order

    def test_the_people_to_choose_as_consultant(self):
        team = self.env['hr.employee'].create({
            'name': "Consultant maison",
            'work_contact_id': self.env['res.partner'].create({'name': "Consultant maison"}).id})
        candidate = self.env['res.partner'].create({
            'name': "Candidat X", 'category_id': [(4, self.env.ref('mission_report.partner_category_candidate').id)]})
        stranger = self.env['res.partner'].create({'name': "Fournisseur quelconque"})
        people = self._sheet().consultant_partner_ids
        self.assertIn(team.work_contact_id, people)
        self.assertIn(candidate, people)
        self.assertNotIn(stranger, people)

    def test_the_project_gives_the_order_the_customer_and_the_conditions(self):
        from odoo.tests import Form
        partner, project, order = self._deal(rate=480.0, days=100.0)
        with Form(self.env['mission.margin']) as form:
            form.project_id = project
            self.assertEqual(form.order_id, order)
            self.assertEqual(form.partner_id, partner)
            self.assertAlmostEqual(form.daily_rate, 480.0)
            self.assertAlmostEqual(form.mission_days, 100.0)
            self.assertTrue(form.margin_rate)
        sheet = form.record
        self.assertEqual(sheet.order_id, order)
        self.assertEqual(sheet.project_id, project)
        self.assertFalse(sheet.order_gap)

    def test_the_consultant_gives_the_salary_of_the_contract(self):
        from odoo.tests import Form
        employee = self.env['hr.employee'].create({
            'name': "Salarié du contrat",
            'work_contact_id': self.env['res.partner'].create({'name': "Salarié du contrat"}).id})
        employee.sudo().write({'wage': 3500.0})
        if not employee.sudo().contract_wage:
            self.skipTest("no wage on the contract in this version")
        with Form(self.env['mission.margin']) as form:
            form.consultant_id = employee.work_contact_id
            self.assertAlmostEqual(form.gross_salary, 3500.0 * 12)
            self.assertEqual(form.cost_origin, 'employee')

    def test_the_payslip_cost_takes_precedence_over_the_salary(self):
        plain = self._sheet(daily_cost_worked=0.0, duration_months=12.0)
        slip = self._sheet(daily_cost_worked=0.0, payslip_monthly_cost=5000.0, gross_salary=40000.0)
        # The cost of the pay is the payslip, with no employer charges added on top of it.
        self.assertAlmostEqual(slip.base_cost, 5000.0 * 12, delta=0.01)
        self.assertAlmostEqual(slip.loaded_cost, 5000.0 * 12 * 1.10, delta=0.01)
        self.assertGreater(slip.total_cost, plain.total_cost)
        # The salary of the sheet no longer moves the cost, the margin or the net income.
        before = (slip.total_cost, slip.margin, slip.net_income_month, slip.net_salary_month)
        slip.gross_salary = 90000.0
        self.assertEqual(before, (slip.total_cost, slip.margin, slip.net_income_month, slip.net_salary_month))
        # The salary behind the payslip: what the cost holds once the employer charges are taken off.
        gross = 5000.0 * 12 / 1.457
        self.assertAlmostEqual(slip.gross_used, gross, delta=0.01)
        self.assertAlmostEqual(slip.net_salary_month, gross * 0.77 / 12, delta=0.01)
        # The ring tells the same story: net + charges of the employee + employer charges = the payslip.
        parts = {part['key']: part['value'] for part in slip.breakdown['segments']}
        self.assertAlmostEqual(parts['net'] + parts['employee'] + parts['employer'], 5000.0, delta=0.01)
        self.assertAlmostEqual(sum(parts.values()), slip.revenue / 12, delta=0.01)
        # Without a payslip, the salary of the sheet is the one used.
        self.assertAlmostEqual(plain.gross_used, 40000.0, delta=0.01)
        # The help of the salary says it, only when the payslip is filled.
        view = self.env['mission.margin'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn("takes precedence", view)

    def _seller(self, login, partner=False):
        groups = [self.env.ref('base.group_user').id, self.env.ref('sales_team.group_sale_salesman').id]
        if partner:
            groups.append(self.env.ref('mission_report.group_mission_partner').id)
        return self.env['res.users'].create({'name': login, 'login': login, 'group_ids': [(6, 0, groups)]})

    def test_the_status_of_the_partners_is_only_offered_to_the_partners(self):
        Rule = self.env['mission.commission.rule']
        associate = Rule.search([('rate_team', '>', 0)], limit=1)
        manager = Rule.search([('rate_team', '=', 0), ('rate_full', '>', 0)], limit=1)
        self.assertEqual(associate.group_id, self.env.ref('mission_report.group_mission_partner'))
        account_manager = self._seller('chargedaffaires_zz@example.com')
        partner = self._seller('associe_zz@example.com', partner=True)
        self.assertNotIn(associate, Rule.with_user(account_manager).search([]))
        self.assertIn(manager, Rule.with_user(account_manager).search([]))
        self.assertIn(associate, Rule.with_user(partner).search([]))
        self.assertIn(manager, Rule.with_user(partner).search([]))
        # An account manager starts with their own status.
        sheet = self.env['mission.margin'].with_user(account_manager).create({'name': "Du chargé d'affaires"})
        self.assertEqual(sheet.commission_rule_id, manager)

    def test_the_commission_page_has_three_columns_for_a_partner_and_two_for_the_others(self):
        def arch(user):
            return self.env['mission.margin'].with_user(user).get_views([(False, 'form')])['views']['form']['arch']
        plain = arch(self._seller('colonnes_a_zz@example.com'))
        partner = arch(self._seller('colonnes_b_zz@example.com', partner=True))
        self.assertIn('commission_full', plain)
        self.assertNotIn('commission_rate_team', plain)
        self.assertIn('commission_rate_team', partner)
        self.assertNotIn('commission_cap_amount', plain + partner)

    def test_a_consultant_without_a_salary_is_said(self):
        employee = self.env['hr.employee'].create({
            'name': "Sans salaire",
            'work_contact_id': self.env['res.partner'].create({'name': "Sans salaire"}).id})
        new = self.env['mission.margin'].new({'consultant_id': employee.work_contact_id.id})
        result = new._onchange_consultant_id()
        self.assertIn("Sans salaire", result['warning']['message'])
        self.assertAlmostEqual(new.gross_salary, 40000.0)

    def test_an_order_has_one_calculation(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        partner, project, order = self._deal()
        first = self._sheet(order_id=order.id, partner_id=partner.id)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self._sheet(order_id=order.id)
        # In the form, choosing that order says where the calculation is, and leaves the order empty.
        new = self.env['mission.margin'].new({'order_id': order.id})
        result = new._onchange_order_id()
        self.assertIn(first.name, result['warning']['message'])
        self.assertFalse(new.order_id)

    def test_the_billing_of_a_month_is_shared_between_the_consultant_the_costs_and_the_margin(self):
        sheet = self._sheet(igd_lodging=True, igd_lunch=True, other_yearly=1200.0)
        data = sheet.breakdown
        parts = {part['key']: part['value'] for part in data['segments']}
        self.assertAlmostEqual(sum(parts.values()), sheet.revenue / 12, places=2)
        self.assertAlmostEqual(data['total'], sheet.revenue / 12, places=2)
        self.assertAlmostEqual(parts['net'], 40000 * 0.77 / 12, places=2)
        self.assertAlmostEqual(parts['employee'], 40000 * 0.23 / 12, places=2)
        self.assertAlmostEqual(parts['employer'], 40000 * 0.457 / 12, places=2)
        self.assertAlmostEqual(parts['margin'], sheet.margin_month, places=2)
        self.assertEqual(data['deficit'], 0.0)
        loss = self._sheet(daily_rate=100.0)
        self.assertGreater(loss.breakdown['deficit'], 0.0)
        self.assertNotIn('margin', {part['key'] for part in loss.breakdown['segments']})
        freelance = self._sheet(cost_origin='freelance', freelance_daily_rate=400.0, daily_cost_worked=0.0)
        self.assertEqual({part['key'] for part in freelance.breakdown['segments']} - {'margin'},
                         {'pay', 'overhead'})

    def test_the_project_of_a_sheet_is_a_draft_until_the_order_is_confirmed(self):
        partner = self.env['res.partner'].create({'name': "Client brouillon"})
        sheet = self._sheet(partner_id=partner.id)
        sheet.action_create_project()
        self.assertTrue(sheet.project_id.mission_draft)
        sheet.action_create_order()
        self.assertTrue(sheet.project_id.mission_draft, "an order that is only a quote does not end the draft")
        sheet.order_id.action_confirm()
        self.assertFalse(sheet.project_id.mission_draft)
        # The confirmation puts the tasks in the project of the sheet: no second project.
        self.assertEqual(sheet.order_id.project_ids, sheet.project_id)

    def test_the_months_of_the_forecast(self):
        sheet = self._sheet(start_date='2031-05-01', duration_months=3.0)
        sheet.action_generate_months()
        self.assertEqual(len(sheet.month_ids), 3)
        # May 2031 has 19 working days (1 May, 8 May and Ascension out), June 2031 (Whit Monday out) 20.
        self.assertEqual(sheet.month_ids[0].working_days, 19.0)
        sheet.month_ids[1].leave_days = 2.0
        self.assertEqual(sheet.month_ids[1].working_days, 18.0)
        self.assertAlmostEqual(sheet.month_ids[0].revenue, 19 * 500.0, places=2)
        self.assertAlmostEqual(sheet.forecast_revenue, sum(sheet.month_ids.mapped('revenue')), places=2)

    def test_the_project_is_created_from_the_sheet(self):
        sheet = self._sheet()
        sheet.action_create_project()
        self.assertEqual(sheet.project_id.name, "Test")
        self.assertEqual(sheet.project_id.margin_count, 1)

    def test_only_sales_and_managers(self):
        sheet = self._sheet()
        user = self.env['res.users'].create({
            'name': "Simple", 'login': 'simple_marge_zz@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            sheet.with_user(user).read(['name'])
        seller = self.env['res.users'].create({
            'name': "Vendeur", 'login': 'vendeur_marge_zz@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('sales_team.group_sale_salesman').id])]})
        # A salesperson sees the sheets they made, not the ones of the others; a sales manager sees them all.
        with self.assertRaises(AccessError):
            sheet.with_user(seller).read(['name'])
        mine = self.env['mission.margin'].with_user(seller).create({'name': "De Vendeur"})
        self.assertEqual(mine.name, "De Vendeur")
        other = self.env['res.users'].create({
            'name': "Autre vendeur", 'login': 'autre_vendeur_marge_zz@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('sales_team.group_sale_salesman').id])]})
        self.assertEqual(self.env['mission.margin'].with_user(other).search([('id', 'in', (sheet | mine).ids)]),
                         self.env['mission.margin'])
        self.assertEqual(self.env['mission.margin'].with_user(seller).search([('id', 'in', (sheet | mine).ids)]), mine)
        manager = self.env['res.users'].create({
            'name': "Chef des ventes", 'login': 'chef_marge_zz@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('sales_team.group_sale_manager').id])]})
        self.assertEqual(self.env['mission.margin'].with_user(manager).search([('id', 'in', (sheet | mine).ids)]),
                         sheet | mine)
        # The months follow their sheet.
        mine.action_generate_months() if mine.start_date else None
        self.assertEqual(self.env['mission.margin.month'].with_user(other).search_count(
            [('margin_id', 'in', (sheet | mine).ids)]), 0)
