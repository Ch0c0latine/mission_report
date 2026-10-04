# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from datetime import date

from odoo import Command

from ..models.volet import strip_plan, work_days_by_month
from .test_sale_delivery import TestSaleDelivery

NOTE = (
    "<h5>Volet&nbsp;1&nbsp;:&nbsp;période du 01/01/2031 au 30/04/2031</h5>"
    "<div>Les prestations seront réalisées sur la base d'un fonctionnement en régie pour un montant "
    "journalier de 500EUR HT/jour travaillé.</div>"
    "<div>Ce volet concerne la période du 01/01/2031 au 30/04/2031: 80 jours ouvrés soit un prévisionnel de:</div>"
    "<div>janvier 2031\t: 22 jours travaillés soit \t11 000 EUR</div><hr><div>Conditions</div>")


class TestVolet(TestSaleDelivery):
    """Nouveau volet : dates, jours ouvrés, note de l'affaire."""

    def test_working_days_skip_holidays_not_missions(self):
        # May 2031: 22 weekdays, 1, 8 and 22 May are public holidays; the mission days count as worked.
        days = work_days_by_month(self.env, self.employee, date(2031, 5, 1), date(2031, 5, 31))
        self.assertEqual(days, {(2031, 5): 19.0})

    def test_working_days_skip_the_leaves_already_booked(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Congé test', 'requires_allocation': False, 'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create({
            'employee_id': self.employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': '2031-05-19', 'request_date_to': '2031-05-20'})
        days = work_days_by_month(self.env, self.employee, date(2031, 5, 1), date(2031, 5, 31))
        self.assertEqual(days, {(2031, 5): 17.0})

    def _wizard(self):
        self.order.write({'project_id': self.project_a.id, 'note': NOTE})
        return self.env['mission.volet.wizard'].with_context(default_order_id=self.order.id).create({})

    def test_the_wizard_starts_after_the_last_order(self):
        wizard = self._wizard()
        self.assertEqual(str(wizard.date_start), '2031-05-01')
        self.assertEqual(str(wizard.date_end), '2031-10-31')
        self.assertEqual(wizard.employee_ids, self.employee)

    def test_new_volet_copies_the_order_on_the_new_dates(self):
        wizard = self._wizard()
        wizard.write({'date_start': '2031-05-01', 'date_end': '2031-05-31'})
        self.assertEqual(wizard.days, 19.0)
        action = wizard.action_create()
        new = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(new.project_id, self.project_a)
        self.assertEqual(str(new.mission_date_start), '2031-05-01')
        self.assertEqual(str(new.mission_date_end), '2031-05-31')
        line = new._volet_day_lines()
        self.assertEqual(line.product_uom_qty, 19.0)
        self.assertEqual((str(line.mission_period_start), str(line.mission_period_end)), ('2031-05-01', '2031-05-31'))
        self.assertEqual(self.order.mission_date_end, date(2031, 4, 30), "read from the first volet title")
        self.assertEqual(new.mission_volet_number, 2)
        # No "Principe de facturation" in this note: it is not split, but copied as it is.
        self.assertEqual(str(new.note).replace('&nbsp;', ' '), str(strip_plan(self.order.note)).replace('&nbsp;', ' '))
        self.assertEqual(new.state, 'draft')

    def test_the_new_volet_starts_without_expenses(self):
        expenses = self.env['product.product'].create({
            'name': 'Dépenses test', 'type': 'service', 'can_be_expensed': True, 'list_price': 1.0})
        self.order.write({'order_line': [Command.create({
            'product_id': expenses.id, 'product_uom_qty': 300.0, 'price_unit': 1.0})]})
        wizard = self._wizard()
        new = self.env['sale.order'].browse(wizard.action_create()['res_id'])
        line = new.order_line.filtered(lambda l: l.product_id == expenses)
        self.assertEqual(line.product_uom_qty, 0.0)
