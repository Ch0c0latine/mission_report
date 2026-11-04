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
        self.assertAlmostEqual(sheet.commission_management, 272.52, places=2)
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
                                     igd_lodging=True, igd_meals='2', mileage_monthly=300.0)
        self.assertAlmostEqual(employee_costs.total_cost, sheet.total_cost, places=2)

    def test_the_margin_wanted_gives_the_daily_rate(self):
        # Without a daily rate typed, the 20 % margin wanted by default sets it, rounded up to 5 euros.
        sheet = self.env['mission.margin'].create({'name': "Auto", 'gross_salary': 40000.0, 'daily_cost_worked': 55.0})
        self.assertEqual(sheet.margin_choice, '20')
        self.assertEqual(sheet.daily_rate % 5, 0)
        self.assertGreaterEqual(sheet.margin_rate, 0.20)
        self.assertLess(sheet.margin_rate, 0.21)
        sheet.write({'margin_choice': '30'})
        self.assertGreaterEqual(sheet.margin_rate, 0.30)
        self.assertLess(sheet.margin_rate, 0.31)
        # The costs change: the daily rate follows the margin wanted.
        before = sheet.daily_rate
        sheet.gross_salary = 50000.0
        self.assertGreater(sheet.daily_rate, before)
        self.assertGreaterEqual(sheet.margin_rate, 0.30)
        # A daily rate typed by hand stays.
        sheet.daily_rate = 700.0
        self.assertEqual(sheet.margin_choice, 'custom')
        sheet.gross_salary = 60000.0
        self.assertEqual(sheet.daily_rate, 700.0)

    def test_the_salary_selector(self):
        sheet = self._sheet(gross_salary=42500.0)
        self.assertEqual(sheet.salary_preset, '42500')
        sheet.gross_salary = 41000.0
        self.assertFalse(sheet.salary_preset)

    def test_the_allowances_follow_the_meals_and_the_lodging(self):
        sheet = self._sheet(igd_lodging=True, igd_meals='2', duration_months=3.0)
        self.assertAlmostEqual(sheet.igd_daily, 2 * 21.4 + 56.8, delta=0.01)
        sheet.duration_months = 12.0
        # 3 months at the first rate, 9 at the second: the average per day worked.
        expected = (3 * (2 * 21.4 + 56.8) + 9 * (2 * 18.2 + 48.3)) / 12
        self.assertAlmostEqual(sheet.igd_daily, expected, delta=0.01)
        sheet.igd_meals = '1'
        sheet.igd_lodging = False
        self.assertAlmostEqual(sheet.igd_daily, (3 * 21.4 + 9 * 18.2) / 12, delta=0.01)
        cost = self._sheet(daily_rate=500.0).total_cost
        with_igd = self._sheet(daily_rate=500.0, igd_meals='1')
        self.assertGreater(with_igd.total_cost, cost)
        rebilled = self._sheet(daily_rate=500.0, igd_meals='1', igd_rebilled=True)
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

    def test_igd_defaults_and_total(self):
        sheet = self._sheet()
        self.assertEqual(len(sheet.igd_ids), 3)
        self.assertAlmostEqual(sheet.igd_ids[0].total, 2 * 21.4 + 56.8, places=2)
        self.assertAlmostEqual(sheet.igd_ids[2].total, 69.8, places=2)

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
        self.assertEqual(sheet.with_user(seller).name, "Test")
