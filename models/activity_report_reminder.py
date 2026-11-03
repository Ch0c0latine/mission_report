# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Relances du compte rendu mensuel.

Une fois le mois fini, le salarié qui a saisi des journées sur une mission reçoit une
tâche « Soumettre le compte rendu » tant qu'il ne l'a pas soumis ; son responsable
reçoit « Valider le compte rendu » quand un compte rendu reste soumis. La tâche part
une seule fois par compte rendu et disparaît quand le compte rendu avance. La société
choisit le jour du mois où la relance part ; sans jour, il n'y en a pas.
"""
from datetime import timedelta

from odoo import _, api, fields, models

#: Jours laissés au responsable avant de lui rappeler un compte rendu soumis.
VALIDATION_DELAY_DAYS = 3


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_reminder_day = fields.Integer(
        string="Jour de relance des comptes rendus", default=0,
        help="Jour du mois où les comptes rendus du mois écoulé sont réclamés : 3 pour le 3. "
             "0 : pas de relance.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_reminder_day = fields.Integer(related='company_id.mission_reminder_day', readonly=False)


class MissionActivityReport(models.Model):
    _inherit = ['mission.activity.report', 'mail.activity.mixin']

    holidays_warning = fields.Char(compute='_compute_holidays_warning')

    @api.depends('date_from', 'company_id')
    def _compute_holidays_warning(self):
        """Une année sans aucun jour férié saisi : le compte rendu compterait les fériés comme des jours travaillés."""
        Leaves = self.env['resource.calendar.leaves'].sudo()
        for report in self:
            report.holidays_warning = False
            if not report.date_from:
                continue
            year = report.date_from.year
            if not Leaves.search_count([
                    ('resource_id', '=', False), ('holiday_id', '=', False),
                    ('date_from', '>=', '%s-01-01 00:00:00' % year), ('date_from', '<=', '%s-12-31 23:59:59' % year)]):
                report.holidays_warning = _(
                    "Aucun jour férié n'est saisi pour %s : ils compteraient comme des jours travaillés.", year)

    def action_generate_holidays(self):
        """Les jours fériés français de l'année du compte rendu."""
        self.ensure_one()
        company = self.company_id or self.env.company
        self.env['mission.public.holiday.wizard'].create(
            {'year': self.date_from.year, 'company_id': company.id})._generate()
        return True

    def _reminder_type(self):
        return self.env.ref('mission_report.mail_activity_type_report', raise_if_not_found=False)

    def _reminder_clear(self):
        """Le compte rendu a avancé : ses relances n'ont plus lieu d'être."""
        kind = self._reminder_type()
        if kind:
            self.sudo().activity_ids.filtered(lambda a: a.activity_type_id == kind).unlink()

    def action_submit(self):
        result = super().action_submit()
        self._reminder_clear()
        return result

    def action_validate(self):
        result = super().action_validate()
        self._reminder_clear()
        return result

    @api.model
    def _cron_remind(self, today=None):
        """Les relances du jour ; ``today`` pour les tests."""
        today = today or fields.Date.context_today(self)
        for company in self.env['res.company'].sudo().search([('mission_reminder_day', '>', 0)]):
            if today.day < company.mission_reminder_day:
                continue
            self._remind_employees(company, today)
            self._remind_managers(company, today)

    @api.model
    def _remind_employees(self, company, today):
        """Le mois écoulé : les salariés qui ont saisi une mission sans soumettre leur compte rendu."""
        last = today.replace(day=1) - timedelta(days=1)
        month = last.replace(day=1)
        entries = self.env['hr.leave'].sudo().search([
            ('project_id', '!=', False), ('employee_id.company_id', '=', company.id),
            ('state', 'not in', ('refuse', 'cancel')),
            ('request_date_from', '<=', last), ('request_date_to', '>=', month)])
        for employee in entries.employee_id.filtered('user_id'):
            report = self.sudo().search([('employee_id', '=', employee.id), ('date_from', '=', month)])
            if report and report.state != 'draft':
                continue
            report = report or self.sudo().create({'employee_id': employee.id, 'date_from': month})
            report._remind(employee.user_id, _(
                "Soumettre votre compte rendu d'activité de %s", report.month_label),
                deadline=today + timedelta(days=VALIDATION_DELAY_DAYS))

    @api.model
    def _remind_managers(self, company, today):
        """Un compte rendu soumis depuis quelques jours : à valider par le responsable."""
        limit = today - timedelta(days=VALIDATION_DELAY_DAYS)
        for report in self.sudo().search([
                ('state', '=', 'submitted'), ('company_id', '=', company.id), ('submit_date', '<=', limit)]):
            employee = report.employee_id
            approver = employee.leave_manager_id or employee.parent_id.user_id
            if approver:
                report._remind(approver, _(
                    "Valider le compte rendu d'activité de %(employee)s (%(month)s)",
                    employee=employee.name, month=report.month_label),
                    deadline=today + timedelta(days=VALIDATION_DELAY_DAYS))

    def _remind(self, user, summary, deadline):
        """Une relance par compte rendu et par personne, jamais deux."""
        self.ensure_one()
        kind = self._reminder_type()
        if not kind or self.sudo().activity_ids.filtered(
                lambda a: a.activity_type_id == kind and a.user_id == user):
            return
        self.sudo().activity_schedule(
            act_type_xmlid='mission_report.mail_activity_type_report', user_id=user.id,
            summary=summary, date_deadline=deadline)
