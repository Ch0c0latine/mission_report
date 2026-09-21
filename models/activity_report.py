# -*- coding: utf-8 -*-
"""Monthly activity reports.

One report per employee and month. It is computed from the entries of the
month: missions (hr.leave with a project) on one side, time off on the
other, day by day, against the employee's working days and the public
holidays. The employee submits it, a manager validates it; a validated
report keeps the figures it was validated with.

Two renderings share the same data: the internal report (missions and time
off) and the client report (the missions of one client only).
"""
import calendar
from datetime import date, datetime, time, timedelta

import pytz
from babel.dates import format_date as babel_format_date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_date
from odoo.tools.misc import formatLang, get_lang


class MissionActivityReport(models.Model):
    _name = 'mission.activity.report'
    _description = "Monthly activity report"
    _inherit = ['mail.thread']
    _order = 'date_from desc, employee_id'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Employee", required=True, index=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    user_id = fields.Many2one(related='employee_id.user_id', store=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    date_from = fields.Date(
        string="Month", required=True, index=True,
        default=lambda self: fields.Date.today().replace(day=1),
        help="Any day of the month: the report covers the whole month.")
    date_to = fields.Date(compute='_compute_date_to', store=True)
    state = fields.Selection([
        ('draft', "Draft"),
        ('submitted', "Submitted"),
        ('validated', "Validated"),
    ], string="Status", default='draft', required=True, tracking=True, copy=False)
    submit_date = fields.Date(string="Submitted on", readonly=True, copy=False)
    submitted_by_id = fields.Many2one('res.users', string="Submitted by", readonly=True, copy=False)
    validate_date = fields.Date(string="Validated on", readonly=True, copy=False)
    validated_by_id = fields.Many2one('res.users', string="Validated by", readonly=True, copy=False)
    # Figures at validation time: later changes to the entries do not alter
    # a validated report.
    snapshot = fields.Json(readonly=True, copy=False)

    potential_days = fields.Float(string="Working days", compute='_compute_totals')
    mission_days = fields.Float(string="Mission days", compute='_compute_totals')
    absence_days = fields.Float(string="Time off days", compute='_compute_totals')
    preview_html = fields.Html(compute='_compute_preview_html', sanitize=False)

    _employee_month_unique = models.Constraint(
        'UNIQUE(employee_id, date_from)',
        "An employee has a single activity report per month.",
    )

    @api.depends('employee_id', 'date_from')
    def _compute_name(self):
        for report in self:
            if report.employee_id and report.date_from:
                report.name = "%s - %s" % (report.employee_id.name,
                                           report.date_from.strftime('%Y-%m'))
            else:
                report.name = _("New activity report")

    @api.depends('date_from')
    def _compute_date_to(self):
        for report in self:
            if report.date_from:
                last = calendar.monthrange(report.date_from.year, report.date_from.month)[1]
                report.date_to = report.date_from.replace(day=last)
            else:
                report.date_to = False

    def _compute_totals(self):
        for report in self:
            if not (report.employee_id and report.date_from):
                report.potential_days = report.mission_days = report.absence_days = 0.0
                continue
            data = report._get_report_data()
            report.potential_days = data['potential_days']
            report.mission_days = data['mission_total']
            report.absence_days = data['absence_total']

    def _compute_preview_html(self):
        for report in self:
            if not (report.employee_id and report.date_from):
                report.preview_html = False
                continue
            report.preview_html = self.env['ir.qweb']._render(
                'mission_report.activity_report_grid',
                {'data': report._get_render_data(), 'lines': 'all',
                 'format_days': report._format_days})

    def _creation_message(self):
        # The native one is "<model description> created", with no agreement
        # in French.
        self.ensure_one()
        return _("Activity report created")

    # ------------------------------------------------------------------
    # The month is always stored as its first day.
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_from'):
                vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('date_from'):
            vals['date_from'] = fields.Date.to_date(vals['date_from']).replace(day=1)
        protected = {'state', 'snapshot', 'submit_date', 'submitted_by_id',
                     'validate_date', 'validated_by_id'}
        if protected & set(vals) and not self.env.context.get('mission_report_workflow'):
            raise UserError(_("Use the Submit, Validate and Reset buttons to change the status."))
        if {'employee_id', 'date_from'} & set(vals) and self.filtered(lambda r: r.state != 'draft'):
            raise UserError(_("Reset the report to draft before changing its employee or month."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_drafts(self):
        if self.filtered(lambda report: report.state != 'draft'):
            raise UserError(_("Only draft activity reports can be deleted."))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def _can_validate(self):
        """HR officers, and the employee's time off approver or manager."""
        self.ensure_one()
        user = self.env.user
        if user.has_group('hr_holidays.group_hr_holidays_user'):
            return True
        # sudo: approver and manager are not readable by every employee.
        employee = self.employee_id.sudo()
        return user in (employee.leave_manager_id | employee.parent_id.user_id)

    def _workflow_write(self, vals):
        return self.with_context(mission_report_workflow=True).write(vals)

    def action_submit(self):
        for report in self:
            if report.state != 'draft':
                raise UserError(_("Only a draft report can be submitted."))
            if report.employee_id.sudo().user_id != self.env.user and not report._can_validate():
                raise AccessError(_("Only %s or a manager can submit this report.",
                                    report.employee_id.name))
            report._workflow_write({
                'state': 'submitted',
                'submit_date': fields.Date.context_today(report),
                'submitted_by_id': self.env.user.id,
            })
        return True

    def action_validate(self):
        for report in self:
            if report.state != 'submitted':
                raise UserError(_("Only a submitted report can be validated."))
            if not report._can_validate():
                raise AccessError(_("You are not allowed to validate the report of %s.",
                                    report.employee_id.name))
            report._workflow_write({
                'state': 'validated',
                'validate_date': fields.Date.context_today(report),
                'validated_by_id': self.env.user.id,
                'snapshot': report._compute_report_data(),
            })
        return True

    def action_reset_to_draft(self):
        """Back to draft: a refused submission, or a validated report to redo."""
        for report in self:
            if report.state == 'draft':
                continue
            if not report._can_validate():
                raise AccessError(_("You are not allowed to reset the report of %s.",
                                    report.employee_id.name))
            report._workflow_write({
                'state': 'draft',
                'submit_date': False,
                'submitted_by_id': False,
                'validate_date': False,
                'validated_by_id': False,
                'snapshot': False,
            })
        return True

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _get_report_data(self):
        """The month's figures: frozen once validated, computed otherwise."""
        self.ensure_one()
        if self.state == 'validated' and self.snapshot:
            return self.snapshot
        return self._compute_report_data()

    def _compute_report_data(self):
        """Day-by-day figures of the month, JSON-serialisable.

        Every value is a number of days. A day holds a value only if it is
        a working day of the employee (neither a weekend nor a public
        holiday); other days stay empty.
        """
        self.ensure_one()
        employee = self.employee_id.sudo()
        date_from, date_to = self.date_from.replace(day=1), self.date_to
        days = [date_from + timedelta(days=offset)
                for offset in range((date_to - date_from).days + 1)]
        working_weekdays = self._get_working_weekdays(employee)
        holidays = self._get_public_holidays(employee, date_from, date_to)

        entries = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ], order='request_date_from, id')

        def is_working(day):
            return day.weekday() in working_weekdays and day not in holidays

        missions, absences = {}, {}
        absence_days = set()
        for entry in entries:
            if entry.request_unit_half:
                per_day = 0.5
            elif entry.request_unit_hours:
                per_day = entry.number_of_days
            else:
                per_day = 1.0
            if entry.project_id:
                key = entry.project_id.id
                line = missions.setdefault(key, {
                    'partner_id': entry.project_id.partner_id.id or False,
                    'partner': entry.project_id.partner_id.display_name or '',
                    'project_id': entry.project_id.id,
                    'project': entry.project_id.display_name,
                    'label': entry.project_id.partner_id.display_name or entry.project_id.display_name,
                    'values': {},
                })
            else:
                key = entry.holiday_status_id.id
                line = absences.setdefault(key, {
                    'leave_type_id': entry.holiday_status_id.id,
                    'label': entry.holiday_status_id.display_name,
                    'values': {},
                })
            day = max(entry.request_date_from, date_from)
            while day <= min(entry.request_date_to, date_to):
                if is_working(day):
                    line['values'][day.day] = line['values'].get(day.day, 0.0) + per_day
                    if not entry.project_id:
                        absence_days.add(day)
                day += timedelta(days=1)

        def finish(line):
            # Working days without an entry hold 0, as on a paper report.
            values = [line['values'].get(day.day, 0.0) if is_working(day) else None
                      for day in days]
            line['values'] = values
            line['total'] = sum(value for value in values if value)
            return line

        mission_lines = [finish(line) for line in missions.values()]
        mission_lines.sort(key=lambda line: (line['partner'].lower(), line['project'].lower()))
        absence_lines = sorted((finish(line) for line in absences.values()),
                               key=lambda line: line['label'].lower())

        def column_sum(lines):
            return [sum(line['values'][index] or 0.0 for line in lines) if is_working(day) else None
                    for index, day in enumerate(days)]

        return {
            'employee': employee.name,
            'company': employee.company_id.name,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'days': [{
                'day': day.day,
                'date': fields.Date.to_string(day),
                'weekday': day.weekday(),
                'week': day.isocalendar()[1],
                'weekend': day.weekday() not in working_weekdays,
                'holiday': holidays.get(day, False),
                'absence': day in absence_days,
            } for day in days],
            'potential_days': float(sum(1 for day in days if is_working(day))),
            'missions': mission_lines,
            'absences': absence_lines,
            'mission_totals': column_sum(mission_lines),
            'totals': column_sum(mission_lines + absence_lines),
            'mission_total': sum(line['total'] for line in mission_lines),
            'absence_total': sum(line['total'] for line in absence_lines),
        }

    @api.model
    def _get_working_weekdays(self, employee):
        """Weekdays (0 = Monday) the employee's working schedule works."""
        calendar_ = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        attendances = calendar_.attendance_ids.filtered(lambda att: not att.display_type) \
            if calendar_ else False
        if not attendances:
            # Flexible hours or no schedule: Monday to Friday.
            return {0, 1, 2, 3, 4}
        return {int(att.dayofweek) for att in attendances}

    @api.model
    def _get_public_holidays(self, employee, date_from, date_to):
        """{date: name} of the public holidays over the period.

        Public holidays are resource.calendar.leaves without a resource,
        for the employee's company and schedule (or for all schedules),
        read in the schedule's timezone.
        """
        calendar_ = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        tz = pytz.timezone((calendar_ and calendar_.tz) or employee.tz or 'UTC')
        start = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = tz.localize(datetime.combine(date_to, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        leaves = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
            ('company_id', 'in', [employee.company_id.id, False]),
            ('calendar_id', 'in', [calendar_.id if calendar_ else False, False]),
            ('date_from', '<=', end),
            ('date_to', '>=', start),
        ])
        holidays = {}
        for leave in leaves:
            first = pytz.utc.localize(leave.date_from).astimezone(tz).date()
            last = pytz.utc.localize(leave.date_to).astimezone(tz).date()
            day = max(first, date_from)
            while day <= min(last, date_to):
                holidays[day] = leave.name or _("Public holiday")
                day += timedelta(days=1)
        return holidays

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _get_render_data(self, partner_id=None):
        """Report data plus labels in the current language.

        ``partner_id``: keep the missions of this client only (client report).
        """
        self.ensure_one()
        data = dict(self._get_report_data())
        locale = get_lang(self.env).code
        month = fields.Date.to_date(data['date_from'])
        data['month_label'] = babel_format_date(month, 'MMMM yyyy', locale=locale)
        weekday_labels = [babel_format_date(date(2024, 1, 1) + timedelta(days=index), 'EEEEE', locale=locale)
                          for index in range(7)]
        data['days'] = [dict(day, weekday_label=weekday_labels[day['weekday']]) for day in data['days']]
        weeks = []
        for day in data['days']:
            if weeks and weeks[-1]['week'] == day['week']:
                weeks[-1]['span'] += 1
            else:
                weeks.append({'week': day['week'], 'span': 1})
        data['weeks'] = weeks
        data['status'] = self._get_status_label()
        if partner_id is not None:
            missions = [line for line in data['missions'] if line['partner_id'] == partner_id]
            data['missions'] = missions
            data['partner'] = missions[0]['partner'] if missions else ''
            data['mission_totals'] = [
                sum(line['values'][index] or 0.0 for line in missions)
                if day['holiday'] is False and not day['weekend'] else None
                for index, day in enumerate(data['days'])]
            data['mission_total'] = sum(line['total'] for line in missions)
        return data

    def _get_status_label(self):
        self.ensure_one()
        if self.state == 'validated':
            return _("Validated on %s", format_date(self.env, self.validate_date))
        if self.state == 'submitted':
            return _("Submitted for validation on %s", format_date(self.env, self.submit_date))
        return _("Draft")

    def _get_client_partner_ids(self):
        """Clients of the report's missions, in report order (False: no client)."""
        self.ensure_one()
        partner_ids = []
        for line in self._get_report_data()['missions']:
            if line['partner_id'] not in partner_ids:
                partner_ids.append(line['partner_id'])
        return partner_ids

    @api.model
    def _format_days(self, value):
        """1 -> "1", 0.5 -> "0.5" (in the current language), None -> ""."""
        if value is None:
            return ''
        if float(value).is_integer():
            return str(int(value))
        return formatLang(self.env, value, digits=2).rstrip('0')

    def action_open_export(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Export to Excel"),
            'res_model': 'mission.activity.report.export',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_report_ids': self.ids},
        }
