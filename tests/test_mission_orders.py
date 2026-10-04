# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import Command
from odoo.exceptions import UserError, ValidationError

from ..models.activity_report import INTERNAL, INTERNAL_KEY
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
                          'project_id': cls.project_a.id})

    def _third(self, **vals):
        return self.env['sale.order'].create({
            'partner_id': self.client_a.id,
            'order_line': [Command.create({'product_id': self.service.id, 'product_uom_qty': 1.0})],
            **vals,
        })

    def test_days_go_to_the_order_of_their_period(self):
        # 5-16 May 2031, 8 May off: 5, 6, 7, 9 and 12 May on the first order, 13-16 on the second.
        self.report.action_submit()
        self.report.action_validate()
        self.assertEqual(self.line.qty_delivered, 5.0)
        self.assertEqual(self.second.order_line.qty_delivered, 4.0)

    def test_periods_are_required_and_must_not_overlap(self):
        third = self._third()
        with self.assertRaises(ValidationError):
            third.project_id = self.project_a  # no dates
        with self.assertRaises(ValidationError):
            third.write({'mission_date_start': '2031-06-01', 'mission_date_end': '2031-06-30',
                         'project_id': self.project_a.id})

    def test_the_start_entered_closes_the_previous_order_without_dates(self):
        quiet = self.env.context.copy()
        quiet[INTERNAL_KEY] = INTERNAL
        (self.order | self.second).with_context(quiet).write(
            {'mission_date_start': False, 'mission_date_end': False})
        self.order.with_context(quiet).write({'mission_date_start': '2031-01-01'})
        self.second.write({'mission_date_start': '2031-03-01'})  # the first order has no end
        self.assertEqual(str(self.order.mission_date_end), '2031-02-28')
        self.assertFalse(self.second.mission_date_end)  # the last one may stay open

    def test_dates_are_read_from_the_volet_title(self):
        third = self._third(note="<h5>Volet&nbsp;3&nbsp;:&nbsp;période du 01/01/2032 au&nbsp;30/06/2032</h5>")
        third.project_id = self.project_a
        self.assertEqual(str(third.mission_date_start), '2032-01-01')
        self.assertEqual(str(third.mission_date_end), '2032-06-30')

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
        # Les points d'accroche sont déclarés ici : leur présence ne dit pas si expense_scan est là.
        if 'expense_scan_invoice_id' not in Expense._fields:
            self.skipTest("expense_scan is not installed")
        self.assertEqual(Expense._expense_scan_orders_of(self.project_a), self.order | self.second)
        self.assertEqual(Expense._expense_scan_projects_of(self.second), self.project_a)
        self.assertEqual(Expense._expense_scan_projects_of(self.order), self.project_a)
        expenses = Expense.search([], limit=0)
        self.assertEqual(Expense._expense_scan_in_period(expenses[:0], self.order), expenses[:0])

    def test_the_end_cannot_precede_the_start(self):
        with self.assertRaises(ValidationError):
            self.second.write({'mission_date_start': '2031-12-31', 'mission_date_end': '2031-12-01'})

    def test_the_volet_number_follows_the_titles(self):
        self.order.note = "<h5>Volet&nbsp;1&nbsp;:&nbsp;période du 01/01/2031 au 12/05/2031</h5>"
        self.second.note = "<h5>Volet&nbsp;4&nbsp;:&nbsp;période du 13/05/2031 au 31/12/2031</h5>"
        wizard = self.env['mission.volet.wizard'].with_context(default_order_id=self.second.id).create({})
        wizard.write({'date_start': '2032-01-01', 'date_end': '2032-01-31'})
        new = self.env['sale.order'].browse(wizard.action_create()['res_id'])
        self.assertEqual(new.mission_volet_number, 5)

    def test_the_project_entries_tab(self):
        action = self.project_a.action_mission_entries()
        self.assertEqual(action['res_model'], 'hr.leave')
        self.assertEqual(action['context']['pivot_measures'], ['number_of_days'])
        entries = self.env['hr.leave'].search(action['domain'])
        self.assertTrue(entries)
        self.assertEqual(entries.mapped('project_id'), self.project_a)
        # A project without any order is counted in days; one billed by the hour in hours.
        self.assertEqual(self.project_b.action_mission_entries()['context']['pivot_measures'],
                         ['number_of_days'])
        (self.order | self.second).write({'mission_billing_unit': 'hour'})
        self.assertEqual(self.project_a.action_mission_entries()['context']['pivot_measures'],
                         ['number_of_hours'])
        self.second.write({'mission_billing_unit': 'day'})
        self.assertEqual(self.project_a.action_mission_entries()['context']['pivot_measures'],
                         ['number_of_days', 'number_of_hours'])
        # Refused and cancelled entries are left out.
        entries[:1].write({'state': 'refuse'})
        self.assertNotIn(entries[:1].id, self.env['hr.leave'].search(action['domain']).ids)

    def _plain_user(self, login, group_xmlids=()):
        user = self.env['res.users'].create({
            'name': login, 'login': login + '@example.com', 'email': login + '@example.com'})
        for xmlid in group_xmlids:
            user.write({'group_ids': [Command.link(self.env.ref(xmlid).id)]})
        return user

    def test_the_project_entries_tab_follows_the_rights(self):
        tabs = self.env['ir.embedded.actions'].search([('python_method', '=', 'action_mission_entries')])
        self.assertEqual(len(tabs), 2)
        plain = self._plain_user('plain_mission_report')
        responsible = self._plain_user('resp_mission_report', ['hr_holidays.group_hr_holidays_responsible'])
        group = self.env.ref('hr_holidays.group_hr_holidays_responsible')
        self.assertEqual(tabs.groups_ids, group)
        self.assertNotIn(group, plain.group_ids)
        self.assertIn(group, responsible.group_ids)
        # Whatever the rights, reading the entries never fails: a plain user sees only his own.
        action = self.project_a.action_mission_entries()
        for user in (plain, responsible):
            count = self.env['hr.leave'].with_user(user).search_count(action['domain'])
            self.assertEqual(count, 0)

    def test_the_project_entries_tab_without_any_entry(self):
        empty = self.env['project.project'].create({'name': 'Empty project'})
        action = empty.action_mission_entries()
        self.assertEqual(action['context']['pivot_measures'], ['number_of_days'])
        self.assertFalse(self.env['hr.leave'].search(action['domain']))
        self.assertEqual(self.env['hr.leave'].read_group(
            action['domain'], ['number_of_days:sum'], ['employee_id']), [])

    def test_the_overview_calendar_colour_field_is_readable_by_every_user(self):
        field = self.env['hr.leave.report.calendar']._fields['holiday_status_id']
        self.assertEqual(field.groups, 'base.group_user')

    def _report_row(self, leave):
        return self.env['hr.leave.report.calendar'].search([('leave_id', '=', leave.id)], limit=1)

    def test_a_refused_entry_can_be_deleted_from_its_dialog(self):
        leaves = self.env['hr.leave'].search([('project_id', '=', self.project_a.id)])
        leave = leaves[0]
        row = self._report_row(leave)
        self.assertTrue(row)
        with self.assertRaises(UserError):  # validated: not deletable from here
            row.action_mission_delete()
        leave.write({'state': 'refuse'})
        row = self._report_row(leave)
        leave_id = leave.id
        row.action_mission_delete()
        self.assertFalse(self.env['hr.leave'].browse(leave_id).exists())

    def test_the_edit_button_opens_the_full_form_of_the_leave(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id)], limit=1)
        action = self._report_row(leave).action_mission_edit()
        self.assertEqual(action['tag'], 'mission_report.edit_leave')
        self.assertEqual(action['params'], {'leave_id': leave.id, 'reopened': False})

    def test_a_leave_can_be_located_in_the_overview(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id)], limit=1)
        action = leave.action_mission_show_overview()
        self.assertEqual(action['res_model'], 'hr.leave.report.calendar')
        self.assertEqual(action['context']['mission_scale'], 'month')
        self.assertTrue(action['context']['initial_date'].startswith(str(leave.request_date_from)))
        self.assertNotIn('search_default_my_team', action['context'])

    def test_reopening_an_approved_entry_puts_it_back_to_approval(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id), ('state', '=', 'validate')], limit=1)
        self.assertTrue(leave)
        action = self._report_row(leave).action_mission_reopen()
        self.assertEqual(leave.state, 'confirm')
        self.assertEqual(action['tag'], 'mission_report.edit_leave')
        # Its dates can now be changed, then it is approved again.
        leave.write({'request_date_to': leave.request_date_to})
        leave.action_approve()
        self.assertEqual(leave.state, 'validate')

    def test_a_submitted_report_locks_the_days_of_its_entries(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id), ('state', '=', 'validate')], limit=1)
        self.assertFalse(leave._mission_lock_reason())
        report = self.env['mission.activity.report'].search([
            ('employee_id', '=', leave.employee_id.id), ('date_from', '<=', leave.request_date_to),
            ('date_to', '>=', leave.request_date_from)], limit=1)
        if not report:
            report = self.env['mission.activity.report'].create({
                'employee_id': leave.employee_id.id, 'date_from': leave.request_date_from.replace(day=1)})
        report.action_submit()
        self.assertTrue(leave._mission_lock_reason())
        with self.assertRaises(UserError):
            leave.write({'request_date_to': leave.request_date_from})
        with self.assertRaises(UserError):
            self._report_row(leave).action_mission_reopen()
        with self.assertRaises(UserError):
            leave.unlink()
        self.assertEqual(leave.state, 'validate')

    def test_a_period_without_working_day_is_refused(self):
        with self.assertRaisesRegex(ValidationError, 'aucun jour travaillé'):
            self.env['hr.leave'].create({
                'employee_id': self.employee.id, 'project_id': self.project_b.id,
                'request_date_from': '2031-06-14', 'request_date_to': '2031-06-15'})  # Saturday, Sunday

    def test_closing_a_reopened_entry_restores_its_approval(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id), ('state', '=', 'validate')], limit=1)
        self._report_row(leave).action_mission_reopen()
        self.assertEqual(leave.state, 'confirm')
        leave.action_mission_restore()
        self.assertEqual(leave.state, 'validate')

    def test_a_half_day_mission_over_several_days_counts_every_half_day(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id)], limit=1)
        full = leave._mission_hours_by_day()
        self.assertGreater(len(full), 1)
        # _write: the billing-unit rule (half days: hourly missions only) is not what is tested here.
        leave._write({'mission_duration': 'half', 'request_date_from_period': 'am', 'request_date_to_period': 'am'})
        leave.invalidate_recordset()
        half = leave._mission_hours_by_day()
        self.assertEqual(set(half), set(full))
        for day, hours in full.items():
            self.assertAlmostEqual(half[day], hours / 2, places=1)

    def test_the_day_span_follows_the_employee_schedule(self):
        leave = self.env['hr.leave'].search([('project_id', '=', self.project_a.id)], limit=1)
        row = self._report_row(leave)
        start, end = row.mission_day_start, row.mission_day_end
        self.assertLess(start, end)
        self.assertTrue(0 <= start < 24 and 0 < end <= 24)
        leave.employee_id.resource_calendar_id = False
        row.invalidate_recordset(['mission_day_start', 'mission_day_end'])
        self.assertEqual((row.mission_day_start, row.mission_day_end), (8.0, 17.0))

    def _trimmed(self, start, end):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id, 'project_id': self.project_b.id,
            'request_date_from': start, 'request_date_to': end})
        return str(leave.request_date_from), str(leave.request_date_to)

    def test_an_entry_does_not_start_or_end_on_a_day_off(self):
        # 2031-06-13 is a Friday, 14-15 the week-end, 16 a Monday.
        self.assertEqual(self._trimmed('2031-06-14', '2031-06-17'), ('2031-06-16', '2031-06-17'))
        self.assertEqual(self._trimmed('2031-06-09', '2031-06-15'), ('2031-06-09', '2031-06-13'))

    def test_a_day_off_in_the_middle_is_kept(self):
        self.assertEqual(self._trimmed('2031-06-23', '2031-06-30'), ('2031-06-23', '2031-06-30'))
        self.assertEqual(self._trimmed('2031-07-04', '2031-07-08'), ('2031-07-04', '2031-07-08'))

