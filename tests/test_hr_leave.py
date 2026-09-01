# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestHrLeaveMissionReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee',
            'company_id': cls.company.id,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Client',
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Test Project',
            'partner_id': cls.partner.id,
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Test Leave Type',
            'requires_allocation': 'no',
        })

    def test_create_mission_without_holiday_status(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-29',
            'request_date_to': '2026-08-29',
        })
        self.assertTrue(leave.id)
        self.assertTrue(leave.holiday_status_id)
        self.assertEqual(leave.holiday_status_id.name, 'Activité')

    def test_partner_id_follows_project(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-29',
            'request_date_to': '2026-08-29',
        })
        self.assertEqual(leave.partner_id, self.partner)

        leave.write({'project_id': False, 'holiday_status_id': self.leave_type.id})
        self.assertFalse(leave.partner_id)

    def test_entry_type_default_and_toggle(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-29',
            'request_date_to': '2026-08-29',
        })
        self.assertEqual(leave.entry_type, 'mission')

        leave.entry_type = 'leave'
        self.assertFalse(leave.project_id)
        leave.holiday_status_id = self.leave_type.id
        self.assertEqual(leave.entry_type, 'leave')

    def test_write_with_both_fields_empty_deletes_record(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-29',
            'request_date_to': '2026-08-29',
        })
        leave_id = leave.id
        leave.write({'project_id': False, 'holiday_status_id': False})
        self.assertFalse(self.env['hr.leave'].browse(leave_id).exists())

    def test_onchange_clear_entry_empties_fields(self):
        leave = self.env['hr.leave'].new({
            'project_id': self.project.id,
            'holiday_status_id': False,
        })
        leave.clear_entry = True
        leave._onchange_clear_entry()
        self.assertFalse(leave.project_id)
        self.assertFalse(leave.holiday_status_id)
        self.assertFalse(leave.clear_entry)

    def test_onchange_project_clears_holiday_status(self):
        leave = self.env['hr.leave'].new({
            'holiday_status_id': self.leave_type.id,
            'project_id': self.project.id,
        })
        leave._onchange_project_id()
        self.assertFalse(leave.holiday_status_id)

    def test_onchange_holiday_status_clears_project(self):
        leave = self.env['hr.leave'].new({
            'holiday_status_id': self.leave_type.id,
            'project_id': self.project.id,
        })
        leave._onchange_holiday_status_id()
        self.assertFalse(leave.project_id)

    def test_constrains_exclusivity(self):
        # Test both set with standard leave type -> should raise ValidationError
        with self.assertRaises(ValidationError):
            self.env['hr.leave'].create({
                'employee_id': self.employee.id,
                'project_id': self.project.id,
                'holiday_status_id': self.leave_type.id,
                'request_date_from': '2025-01-01',
                'request_date_to': '2025-01-01',
            })

        # Test only project_id set -> should pass without error
        leave_mission = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2025-01-01',
            'request_date_to': '2025-01-01',
        })
        self.assertTrue(leave_mission.id)

        # Test only holiday_status_id set -> should pass without error
        leave_holiday = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': '2025-01-01',
            'request_date_to': '2025-01-01',
        })
        self.assertTrue(leave_holiday.id)
