# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests.common import TransactionCase

# Same year as the activity report tests: it holds no real entry.
YEAR = 2031


class TestSaleDelivery(TransactionCase):
    """Validated reports set the delivered days of the mission's order line."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        user = cls.env['res.users'].create({
            'name': 'Sale Employee', 'login': 'sale_employee_mission_report@example.com',
            'email': 'sale_employee_mission_report@example.com'})
        manager = cls.env['res.users'].create({
            'name': 'Sale Manager', 'login': 'sale_manager_mission_report@example.com',
            'email': 'sale_manager_mission_report@example.com'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Sale Employee', 'company_id': cls.company.id,
            'user_id': user.id, 'leave_manager_id': manager.id})
        cls.client_a = cls.env['res.partner'].create({'name': 'A Client'})
        cls.client_b = cls.env['res.partner'].create({'name': 'B Client'})
        cls.project_a = cls.env['project.project'].create({'name': 'Project A', 'partner_id': cls.client_a.id})
        cls.project_b = cls.env['project.project'].create({'name': 'Project B', 'partner_id': cls.client_b.id})
        for project in (cls.project_a, cls.project_b):
            cls.env['project.task'].create({
                'name': 'Task', 'project_id': project.id, 'user_ids': [(6, 0, user.ids)]})
        cls.env['mission.public.holiday.wizard'].create({
            'year': YEAR, 'company_id': cls.company.id})._generate()
        # May 2031: 9 working days for A (8 May is off), 2 for B.
        cls._entry(cls.project_a, '2031-05-05', '2031-05-16')
        cls._entry(cls.project_b, '2031-05-26', '2031-05-27')
        cls.report = cls.env['mission.activity.report'].create({
            'employee_id': cls.employee.id, 'date_from': '2031-05-17'})
        cls.service = cls.env['product.product'].create({
            'name': 'Assistance jours', 'type': 'service', 'list_price': 500.0,
            'invoice_policy': 'delivery'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.client_a.id,
            'order_line': [Command.create({'product_id': cls.service.id, 'product_uom_qty': 40.0})],
        })
        cls.order.action_confirm()
        cls.line = cls.order.order_line
        cls.project_a.sale_line_id = cls.line

    @classmethod
    def _entry(cls, project, date_from, date_to):
        return cls.env['hr.leave'].create({
            'employee_id': cls.employee.id, 'project_id': project.id,
            'request_date_from': date_from, 'request_date_to': date_to})

    def _validate(self, report):
        report.action_submit()
        report.action_validate()

    def test_validated_days_become_delivered(self):
        self.assertEqual(self.line.qty_delivered, 0.0)
        self._validate(self.report)
        self.assertEqual(self.line.qty_delivered, 9.0)

    def test_reset_takes_the_days_back(self):
        self._validate(self.report)
        self.report.action_reset_to_draft()
        self.assertEqual(self.line.qty_delivered, 0.0)

    def test_other_missions_are_left_alone(self):
        order = self.env['sale.order'].create({
            'partner_id': self.client_b.id,
            'order_line': [Command.create({'product_id': self.service.id, 'product_uom_qty': 10.0})],
        })
        order.action_confirm()
        self.project_b.sale_line_id = order.order_line
        self._validate(self.report)
        self.assertEqual(order.order_line.qty_delivered, 2.0)
        self.assertEqual(self.line.qty_delivered, 9.0)

    def test_invoice_takes_the_new_days_only(self):
        self._validate(self.report)
        invoice = self.order._create_invoices()
        invoice.action_post()
        self.assertEqual(self.line.qty_invoiced, 9.0)
        other = self.env['mission.activity.report'].create({
            'employee_id': self.employee.id, 'date_from': '2031-06-01'})
        self._entry(self.project_a, '2031-06-03', '2031-06-05')
        self._validate(other)
        self.assertEqual(self.line.qty_delivered, 12.0)
        self.assertEqual(self.line.qty_to_invoice, 3.0)
