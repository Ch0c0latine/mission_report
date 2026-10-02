# -*- coding: utf-8 -*-
from odoo import Command

from .test_sale_delivery import TestSaleDelivery


class TestMissionOrders(TestSaleDelivery):
    """Plusieurs affaires pour une même mission."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.line.product_uom_qty = 5.0
        cls.second = cls.env['sale.order'].create({
            'partner_id': cls.client_a.id,
            'order_line': [Command.create({'product_id': cls.service.id, 'product_uom_qty': 20.0})],
        })
        cls.second.action_confirm()
        cls.second.mission_project_ids = cls.project_a

    def test_days_fill_the_orders_in_turn(self):
        self.report.action_submit()
        self.report.action_validate()
        self.assertEqual(self.line.qty_delivered, 5.0, "the first order up to its quantity")
        self.assertEqual(self.second.order_line.qty_delivered, 4.0, "the rest on the extension")

    def test_the_people_appear_on_both_orders(self):
        self.report.action_submit()
        self.report.action_validate()
        self.assertEqual(self.second.mission_employee_names, 'Sale Employee')
        self.assertEqual(self.order.mission_employee_names, 'Sale Employee')

    def test_expenses_go_to_the_current_order(self):
        Expense = self.env['hr.expense']
        self.assertEqual(Expense._expense_scan_orders_of(self.project_a), self.second)
        self.assertEqual(Expense._expense_scan_projects_of(self.second), self.project_a)
        self.assertFalse(Expense._expense_scan_projects_of(self.order))
