# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestHrLeaveMissionReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.user.company_id
        cls.user = cls.env['res.users'].create({
            'name': 'Test User',
            'login': 'test_user_mission_report@example.com',
            'email': 'test_user_mission_report@example.com',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee',
            'company_id': cls.company.id,
            'user_id': cls.user.id,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Client',
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Test Project',
            'partner_id': cls.partner.id,
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Test Task',
            'project_id': cls.project.id,
            'user_ids': [(6, 0, [cls.user.id])],
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Test Leave Type',
            'requires_allocation': False,
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

    def test_entry_type_defaults_to_mission_for_new_record(self):
        leave = self.env['hr.leave'].new({})
        self.assertEqual(leave.entry_type, 'mission')

    def test_entry_type_reflects_existing_leave(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': '2026-08-29',
            'request_date_to': '2026-08-29',
        })
        self.assertEqual(leave.entry_type, 'leave')

    def test_entry_type_leave_defaults_to_first_leave_type(self):
        first_type = self.env['hr.leave.type'].search([], limit=1)
        leave = self.env['hr.leave'].new({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
        })
        leave.entry_type = 'leave'
        leave._onchange_entry_type()
        self.assertEqual(leave.holiday_status_id, first_type)

    def test_entry_type_mission_defaults_to_first_available_project(self):
        leave = self.env['hr.leave'].new({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': self.leave_type.id,
        })
        leave.entry_type = 'mission'
        leave._onchange_entry_type()
        self.assertEqual(leave.project_id, leave.available_project_ids[:1])
        self.assertEqual(leave.project_id, self.project)

    def test_available_project_ids_limited_to_assigned_tasks(self):
        other_project = self.env['project.project'].create({'name': 'Unassigned Project'})
        leave = self.env['hr.leave'].new({'employee_id': self.employee.id})
        self.assertIn(self.project, leave.available_project_ids)
        self.assertNotIn(other_project, leave.available_project_ids)

    def test_check_employee_assigned_to_project(self):
        other_project = self.env['project.project'].create({'name': 'Unassigned Project'})
        with self.assertRaises(ValidationError):
            self.env['hr.leave'].create({
                'employee_id': self.employee.id,
                'project_id': other_project.id,
                'holiday_status_id': False,
                'request_date_from': '2026-08-29',
                'request_date_to': '2026-08-29',
            })

    def test_default_get_forces_empty_holiday_status(self):
        defaults = self.env['hr.leave'].with_context(
            default_holiday_status_id=self.leave_type.id
        ).default_get(['holiday_status_id'])
        self.assertFalse(defaults.get('holiday_status_id'))

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
