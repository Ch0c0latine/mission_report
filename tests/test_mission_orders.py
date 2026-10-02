# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import ValidationError

from .test_sale_delivery import TestSaleDelivery


class TestMissionOrders(TestSaleDelivery):
    """Plusieurs affaires pour une même mission."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.line.product_uom_qty = 5.0
        cls.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-05-12'})
        cls.second = cls.env['sale.order'].create({
            'partner_id': cls.client_a.id,
            'order_line': [Command.create({'product_id': cls.service.id, 'product_uom_qty': 20.0})],
        })
        cls.second.action_confirm()
        cls.second.write({'mission_date_start': '2031-05-13', 'mission_date_end': '2031-12-31',
                          'mission_project_ids': [(4, cls.project_a.id)]})

    def test_days_go_to_the_order_of_their_period(self):
        # 5-16 May 2031, 8 May off: 5, 6, 7, 9 and 12 May on the first order, 13-16 on the second.
        self.report.action_submit()
        self.report.action_validate()
        self.assertEqual(self.line.qty_delivered, 5.0)
        self.assertEqual(self.second.order_line.qty_delivered, 4.0)

    def test_periods_are_required_and_must_not_overlap(self):
        third = self.env['sale.order'].create({
            'partner_id': self.client_a.id,
            'order_line': [Command.create({'product_id': self.service.id, 'product_uom_qty': 1.0})],
        })
        with self.assertRaises(ValidationError):
            third.mission_project_ids = self.project_a  # no dates
        with self.assertRaises(ValidationError):
            third.write({'mission_date_start': '2031-06-01', 'mission_date_end': '2031-06-30',
                         'mission_project_ids': [(4, self.project_a.id)]})

    def test_the_task_assignees_are_interveners(self):
        names = self.second.mission_employee_names
        self.assertIn('Sale Employee', names)

    def test_the_people_appear_on_both_orders(self):
        self.report.action_submit()
        self.report.action_validate()
        self.assertIn('Sale Employee', self.second.mission_employee_names)
        self.assertIn('Sale Employee', self.order.mission_employee_names)

    def test_expenses_go_to_the_current_order(self):
        Expense = self.env['hr.expense']
        self.assertEqual(Expense._expense_scan_orders_of(self.project_a), self.order | self.second)
        self.assertEqual(Expense._expense_scan_projects_of(self.second), self.project_a)
        self.assertEqual(Expense._expense_scan_projects_of(self.order), self.project_a)
        expenses = Expense.search([], limit=0)
        self.assertEqual(Expense._expense_scan_in_period(expenses[:0], self.order), expenses[:0])
