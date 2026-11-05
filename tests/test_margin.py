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
        with Form(self.env['mission.margin']) as form:
            form.partner_id = partner
            form.consultant = "Alex"
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
            self.assertEqual(form.margin_wanted, min(max(int(round(form.margin_rate * 100)), 10), 40))
            self.assertGreater(form.margin_wanted, 20)
            # Moving the margin slider gives the control back to the margin.
            form.margin_wanted = 15
            self.assertFalse(form.rate_manual)
            self.assertEqual(form.margin_wanted, 15)

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
