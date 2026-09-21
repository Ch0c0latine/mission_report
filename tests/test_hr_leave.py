# -*- coding: utf-8 -*-
from freezegun import freeze_time

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
            'request_date_from': '2026-08-26',
            'request_date_to': '2026-08-26',
        })
        self.assertTrue(leave.id)
        self.assertTrue(leave.holiday_status_id)
        self.assertEqual(leave.holiday_status_id.name, 'Activité')

    def test_partner_id_follows_project(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-26',
            'request_date_to': '2026-08-26',
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
            'request_date_from': '2026-08-26',
            'request_date_to': '2026-08-26',
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
        self.assertEqual(leave.project_id._origin, self.project)

    def test_available_project_ids_limited_to_assigned_tasks(self):
        other_project = self.env['project.project'].create({'name': 'Unassigned Project'})
        leave = self.env['hr.leave'].new({'employee_id': self.employee.id})
        # available_project_ids porte des NewId sur un enregistrement virtuel :
        # _origin ramène les projets réels.
        self.assertIn(self.project, leave.available_project_ids._origin)
        self.assertNotIn(other_project, leave.available_project_ids._origin)

    def test_check_employee_assigned_to_project(self):
        other_project = self.env['project.project'].create({'name': 'Unassigned Project'})
        with self.assertRaises(ValidationError):
            self.env['hr.leave'].create({
                'employee_id': self.employee.id,
                'project_id': other_project.id,
                'holiday_status_id': False,
                'request_date_from': '2026-08-26',
                'request_date_to': '2026-08-26',
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
                'request_date_from': '2025-01-08',
                'request_date_to': '2025-01-08',
            })

        # Test only project_id set -> should pass without error
        leave_mission = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2025-01-08',
            'request_date_to': '2025-01-08',
        })
        self.assertTrue(leave_mission.id)

        # Test only holiday_status_id set -> should pass without error.
        # Un autre jour que la mission ci-dessus : deux saisies qui se
        # chevauchent sont refusées par hr_holidays.
        leave_holiday = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': '2025-01-09',
            'request_date_to': '2025-01-09',
        })
        self.assertTrue(leave_holiday.id)

    def test_mission_meeting_speaks_of_activite(self):
        # L'événement Calendrier est créé à la validation, immédiate pour une
        # mission : c'est lui qui affichait "<salarié> en congé".
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-26',
            'request_date_to': '2026-08-26',
        })
        self.assertTrue(leave.meeting_id, "La saisie de mission doit créer un événement Calendrier.")
        self.assertIn('en activité', leave.meeting_id.name)
        self.assertNotIn('congé', leave.meeting_id.name)

    def test_leave_meeting_keeps_the_native_wording(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Congé de test sans validation',
            'requires_allocation': False,
            'leave_validation_type': 'no_validation',
        })
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': leave_type.id,
            'request_date_from': '2026-08-27',
            'request_date_to': '2026-08-27',
        })
        self.assertTrue(leave.meeting_id)
        self.assertNotIn('activité', leave.meeting_id.name)

    def test_mission_resource_leave_speaks_of_activite(self):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-08-28',
            'request_date_to': '2026-08-28',
        })
        resource_leave = self.env['resource.calendar.leaves'].search([('holiday_id', '=', leave.id)])
        self.assertTrue(resource_leave)
        self.assertIn('activité', resource_leave.name)

    @freeze_time('2026-09-23 12:00:00')
    def test_presence_badge_says_activite_during_a_mission(self):
        # Mercredi, en pleine journée de travail : le badge de présence passe à
        # "En congé" chez hr_holidays dès qu'une saisie est en cours.
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': self.project.id,
            'holiday_status_id': False,
            'request_date_from': '2026-09-23',
            'request_date_to': '2026-09-23',
        })
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.is_absent)
        self.assertEqual(self.employee.hr_icon_display, 'presence_holiday_activity')

    @freeze_time('2026-09-23 12:00:00')
    def test_presence_badge_unchanged_during_a_leave(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Congé de test sans validation',
            'requires_allocation': False,
            'leave_validation_type': 'no_validation',
        })
        self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'project_id': False,
            'holiday_status_id': leave_type.id,
            'request_date_from': '2026-09-23',
            'request_date_to': '2026-09-23',
        })
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.is_absent)
        self.assertNotEqual(self.employee.hr_icon_display, 'presence_holiday_activity')
