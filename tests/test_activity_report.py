# -*- coding: utf-8 -*-
import io
from datetime import date

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase

from odoo.addons.mission_report.models.public_holiday_wizard import easter_sunday

# Tests run on a copy of real data: 2031 holds no real entry, and creating
# public holidays re-evaluates every entry they overlap.
YEAR = 2031


class TestActivityReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.user = cls.env['res.users'].create({
            'name': 'Report Employee',
            'login': 'report_employee_mission_report@example.com',
            'email': 'report_employee_mission_report@example.com',
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'Report Manager',
            'login': 'report_manager_mission_report@example.com',
            'email': 'report_manager_mission_report@example.com',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Report Employee',
            'company_id': cls.company.id,
            'user_id': cls.user.id,
            'leave_manager_id': cls.manager.id,
        })
        cls.client_a = cls.env['res.partner'].create({'name': 'A Client'})
        cls.client_b = cls.env['res.partner'].create({'name': 'B Client'})
        cls.project_a = cls.env['project.project'].create({'name': 'Project A', 'partner_id': cls.client_a.id})
        cls.project_b = cls.env['project.project'].create({'name': 'Project B', 'partner_id': cls.client_b.id})
        for project in (cls.project_a, cls.project_b):
            cls.env['project.task'].create({
                'name': 'Task', 'project_id': project.id, 'user_ids': [(6, 0, cls.user.ids)]})
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Report test time off',
            'requires_allocation': False,
            'leave_validation_type': 'no_validation',
        })
        cls.env['mission.public.holiday.wizard'].create({
            'year': YEAR, 'company_id': cls.company.id})._generate()
        # May 2031: 1st, 8th and 22nd (Ascension) are public holidays, all
        # on Thursdays. 22 weekdays - 3 = 19 working days.
        cls._entry(cls.project_a, '2031-05-05', '2031-05-16')   # 9 days: 8 May is off
        cls._entry(cls.project_b, '2031-05-26', '2031-05-27')   # 2 days
        cls._entry(False, '2031-05-19', '2031-05-19')           # 1 day off
        cls.report = cls.env['mission.activity.report'].create({
            'employee_id': cls.employee.id, 'date_from': '2031-05-17'})

    @classmethod
    def _entry(cls, project, date_from, date_to):
        return cls.env['hr.leave'].create({
            'employee_id': cls.employee.id,
            'project_id': project.id if project else False,
            'holiday_status_id': False if project else cls.leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        })

    def test_easter(self):
        self.assertEqual(easter_sunday(2024), date(2024, 3, 31))
        self.assertEqual(easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(easter_sunday(2031), date(2031, 4, 13))

    def test_public_holidays_generated_once(self):
        holidays = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False), ('company_id', '=', self.company.id),
            ('date_from', '>=', '%s-01-01' % (YEAR - 1)), ('date_to', '<=', '%s-01-02' % (YEAR + 1))])
        self.assertEqual(len(holidays), 11)
        again = self.env['mission.public.holiday.wizard'].create({'year': YEAR})._generate()
        self.assertFalse(again)
        alsace = self.env['mission.public.holiday.wizard'].create(
            {'year': YEAR + 1, 'alsace_moselle': True})._generate()
        self.assertEqual(len(alsace), 13)

    def test_month_is_stored_as_first_day(self):
        self.assertEqual(self.report.date_from, date(YEAR, 5, 1))
        self.assertEqual(self.report.date_to, date(YEAR, 5, 31))

    def test_report_data(self):
        data = self.report._get_report_data()
        self.assertEqual(data['potential_days'], 19)
        self.assertEqual([line['project'] for line in data['missions']], ['Project A', 'Project B'])
        line_a = data['missions'][0]
        self.assertEqual(line_a['total'], 9)
        self.assertIsNone(line_a['values'][0], "1 May is a public holiday")
        self.assertIsNone(line_a['values'][2], "3 May is a Saturday")
        self.assertEqual(line_a['values'][4], 1, "5 May is a mission day")
        self.assertEqual(line_a['values'][1], 0, "2 May is a working day without mission")
        self.assertEqual(data['mission_total'], 11)
        self.assertEqual(data['absence_total'], 1)
        self.assertEqual(data['absences'][0]['label'], 'Report test time off')
        self.assertTrue(data['days'][0]['holiday'])
        self.assertTrue(data['days'][18]['absence'])
        self.assertEqual(data['totals'][18], 1)
        self.assertEqual(data['totals'][19], 0)
        self.assertEqual(self.report.mission_days, 11)

    def test_client_data_keeps_one_client(self):
        self.assertEqual(self.report._get_client_partner_ids(), [self.client_a.id, self.client_b.id])
        data = self.report._get_render_data(partner_id=self.client_b.id)
        self.assertEqual([line['project'] for line in data['missions']], ['Project B'])
        self.assertEqual(data['mission_total'], 2)
        self.assertEqual(data['partner'], 'B Client')

    def test_workflow(self):
        report = self.report.with_user(self.user)
        with self.assertRaises(UserError):
            report.write({'state': 'validated'})
        report.action_submit()
        self.assertEqual(report.state, 'submitted')
        self.assertTrue(report.submit_date)
        with self.assertRaises(AccessError):
            report.action_validate()
        self.report.with_user(self.manager).action_validate()
        self.assertEqual(self.report.state, 'validated')
        # A validated report keeps its figures.
        self._entry(self.project_a, '2031-05-28', '2031-05-28')
        self.assertEqual(self.report._get_report_data()['mission_total'], 11)
        self.report.with_user(self.manager).action_reset_to_draft()
        self.assertEqual(self.report.state, 'draft')
        self.assertEqual(self.report._get_report_data()['mission_total'], 12)

    def test_one_report_per_employee_and_month(self):
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env['mission.activity.report'].create({
                'employee_id': self.employee.id, 'date_from': '2031-05-02'})

    def test_excel_export(self):
        import openpyxl
        template = self.env.ref('mission_report.activity_report_template_internal')
        template.action_generate_file()
        book = openpyxl.load_workbook(io.BytesIO(template._export(self.report)))
        sheet = book.worksheets[0]
        self.assertEqual(sheet['B3'].value, 'Report Employee')
        self.assertEqual(sheet['D8'].value, 1)
        # Missions: two lines from row 10; 5 May is column H.
        self.assertEqual(sheet['B10'].value, 'Project A')
        self.assertEqual(sheet['H10'].value, 1)
        self.assertEqual(sheet['B11'].value, 'Project B')
        # Time off: one line, pulled up to row 13; the total line follows.
        self.assertEqual(sheet['A13'].value, 'Report test time off')
        self.assertEqual(sheet['D14'].value, '=SUM(D10:D11)+SUM(D13:D13)')

    def test_client_excel_export_per_client(self):
        template = self.env.ref('mission_report.activity_report_template_client')
        template.action_generate_file()
        wizard = self.env['mission.activity.report.export'].create({
            'report_ids': [(6, 0, self.report.ids)], 'template_id': template.id})
        action = wizard.action_export()
        attachment = self.env['ir.attachment'].browse(int(action['url'].split('/')[3].split('?')[0]))
        self.assertEqual(attachment.mimetype, 'application/zip')

    def test_pdf_html(self):
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'mission_report.action_report_activity_internal', self.report.ids)
        self.assertIn(b'Report Employee', html)
        self.assertIn(b'Report test time off', html)
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'mission_report.action_report_activity_client', self.report.ids)
        self.assertNotIn(b'Report test time off', html)
        self.assertIn(b'B Client', html)

    def test_employee_downloads_own_reports(self):
        # An employee without any HR right prints and exports their own report.
        report = self.report.with_user(self.user)
        for xmlid in ('mission_report.action_report_activity_internal',
                      'mission_report.action_report_activity_client'):
            html, _kind = self.env['ir.actions.report'].with_user(self.user)._render_qweb_html(
                xmlid, report.ids)
            self.assertIn(b'Report Employee', html)
        template = self.env.ref('mission_report.activity_report_template_internal')
        template.action_generate_file()
        wizard = self.env['mission.activity.report.export'].with_user(self.user).create({
            'report_ids': [(6, 0, report.ids)], 'template_id': template.id})
        self.assertEqual(wizard.action_export()['type'], 'ir.actions.act_url')
        self.assertTrue(report.preview_html)
