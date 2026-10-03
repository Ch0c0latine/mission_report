# -*- coding: utf-8 -*-
from datetime import date

from .test_sale_delivery import TestSaleDelivery


class TestIgd(TestSaleDelivery):
    """IGD du mois d'après le montant moyen prévu sur la mission."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Product = cls.env['product.product']
        cls.lodging = Product.create({'name': 'IGD logement test', 'can_be_expensed': True,
                                      'standard_price': 48.30})
        cls.meal = Product.create({'name': 'IGD repas test', 'can_be_expensed': True,
                                   'standard_price': 36.40})
        cls.real_meal = Product.create({'name': 'Repas réel test', 'can_be_expensed': True})
        cls.company.write({
            'igd_lodging_product_id': cls.lodging.id, 'igd_meal_product_id': cls.meal.id,
            'igd_real_meal_product_ids': [(6, 0, cls.real_meal.ids)]})
        cls.project_a.igd_monthly_budget = 500.0

    def _generated(self):
        self.env['mission.igd.wizard'].create({
            'employee_ids': [(6, 0, self.employee.ids)],
            'report_month': '5', 'report_year': '2031'}).action_generate()
        return self.env['hr.expense'].search([
            ('employee_id', '=', self.employee.id), ('igd_generated', '=', True)], order='date, id')

    def test_lodging_first_then_meals_up_to_the_budget(self):
        expenses = self._generated()
        lodging = expenses.filtered(lambda e: e.product_id == self.lodging)
        meals = expenses.filtered(lambda e: e.product_id == self.meal)
        self.assertEqual(len(lodging), 9, "one lodging per day of presence")
        self.assertEqual(len(meals), 2, "meals top up to approach 500")
        self.assertAlmostEqual(sum(expenses.mapped('total_amount')), 9 * 48.30 + 2 * 36.40)
        self.assertEqual(set(expenses.project_id.ids), {self.project_a.id})

    def test_no_meal_on_a_day_with_a_real_meal(self):
        self.env['hr.expense'].create({
            'name': 'Déjeuner', 'employee_id': self.employee.id, 'product_id': self.real_meal.id,
            'date': date(2031, 5, 5), 'total_amount_currency': 20.0})
        meals = self._generated().filtered(lambda e: e.product_id == self.meal)
        self.assertNotIn(date(2031, 5, 5), meals.mapped('date'))
        self.assertEqual(len(meals), 2)

    def test_generating_again_replaces_the_drafts(self):
        first = self._generated()
        again = self._generated()
        self.assertEqual(len(first), len(again))
        self.assertFalse(first.exists() & again - again)


    def test_missions_without_budget_get_nothing_and_say_so(self):
        self.project_a.igd_monthly_budget = 0.0
        wizard = self.env['mission.igd.wizard'].create({
            'employee_ids': [(6, 0, self.employee.ids)], 'report_month': '5', 'report_year': '2031'})
        wizard.action_generate()
        self.assertEqual(wizard.state, 'done')
        self.assertFalse(wizard.created_expense_ids)
        self.assertTrue(wizard.result)

    def test_a_month_without_presence_says_why_and_links_to_the_entries(self):
        wizard = self.env['mission.igd.wizard'].create({
            'employee_ids': [(6, 0, self.employee.ids)], 'report_month': '8', 'report_year': '2031'})
        wizard.action_generate()
        self.assertEqual(wizard.state, 'done')
        self.assertIn("aucune journée", wizard.result)
        self.assertEqual(wizard.missing_employee_ids, self.employee)
        action = wizard.action_open_entries()
        self.assertEqual(action['context']['mission_scale'], 'month')
        self.assertEqual(action['context']['initial_date'], '2031-08-01 00:00:00')

    def test_the_wizard_reports_what_was_created(self):
        wizard = self.env['mission.igd.wizard'].create({
            'employee_ids': [(6, 0, self.employee.ids)], 'report_month': '5', 'report_year': '2031'})
        wizard.action_generate()
        self.assertEqual(len(wizard.created_expense_ids), 11)
        self.assertIn("9 IGD logement et 2 IGD repas", wizard.result)
        self.assertIn("pour ce mois", wizard.result)
        self.assertEqual(wizard.action_open_expenses()['domain'], [('id', 'in', wizard.created_expense_ids.ids)])

    def test_the_expat_category_counts_as_igd(self):
        expat = self.env['product.product'].create({'name': 'Forfait expat test', 'can_be_expensed': True})
        self.company.igd_expat_product_id = expat
        self.assertIn(expat.id, self.env['product.product']._igd_product_ids())

    def test_the_igd_filter_keeps_only_igd(self):
        Expense = self.env['hr.expense']
        igd = Expense.create({'name': 'IGD', 'employee_id': self.employee.id, 'product_id': self.lodging.id,
                              'date': date(2031, 5, 5), 'total_amount_currency': 48.3})
        other = Expense.create({'name': 'Repas', 'employee_id': self.employee.id, 'product_id': self.real_meal.id,
                                'date': date(2031, 5, 5), 'total_amount_currency': 20.0})
        both = igd | other
        for domain in ([('product_id.igd_category', '=', True)], [('product_id.igd_category', 'in', [True])],
                       [('product_id.igd_category', '!=', False)]):
            self.assertEqual(Expense.search(domain + [('id', 'in', both.ids)]), igd, domain)
        for domain in ([('product_id.igd_category', '=', False)], [('product_id.igd_category', 'not in', [True])],
                       [('product_id.igd_category', '!=', True)]):
            self.assertEqual(Expense.search(domain + [('id', 'in', both.ids)]), other, domain)

    def test_a_month_without_any_igd_is_not_caught_up(self):
        # April has presence on the mission but no IGD was ever entered for it: nothing to catch up.
        self._entry(self.project_a, '2031-04-07', '2031-04-11')
        meals = self._generated().filtered(lambda e: e.product_id == self.meal)
        self.assertEqual(len(meals), 2, "one month due only")

    def test_a_month_with_igd_but_no_report_counts_for_the_catch_up(self):
        # April has presence and one IGD entered, nobody opened its report: the rest is due in May.
        self._entry(self.project_a, '2031-04-07', '2031-04-11')
        self.env['hr.expense'].create({
            'name': 'IGD', 'employee_id': self.employee.id, 'product_id': self.lodging.id,
            'date': date(2031, 4, 7), 'project_id': self.project_a.id})
        meals = self._generated().filtered(lambda e: e.product_id == self.meal)
        self.assertEqual(len(meals), 9, "two months due: meals on every day of presence")
