# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import re

import pytz
from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_round, format_date
from odoo.tools.intervals import Intervals
from odoo.tools.safe_eval import safe_eval
from odoo.tools.translate import code_translations

from .activity_report import INTERNAL, INTERNAL_KEY
from .work_time import hours_by_day, work_intervals


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    # "Type de saisie" : le type vaut "Activité" pour une mission. Le formulaire,
    # où le champ n'apparaît qu'en mode congé, affiche "Congé".
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Type de saisie',
        required=False,
        default=False,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Mission',
        required=False,
        ondelete='restrict',
        help='Projet associé à la saisie de rapport de mission.'
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        related='project_id.partner_id',
        store=True,
        readonly=True,
        help='Client associé à la mission, dérivé du projet.'
    )
    available_project_ids = fields.Many2many(
        'project.project',
        compute='_compute_available_project_ids',
        help="Projets ayant au moins une tâche assignée à l'employé de cette saisie."
    )
    entry_type = fields.Selection(
        [('mission', 'Mission'), ('leave', 'Congé')],
        string='Nature de la saisie',
        compute='_compute_entry_type',
        readonly=False,
        help="Bascule entre une saisie de Mission (par défaut) et une saisie de Congé."
    )
    # Mission facturée à l'heure : la saisie compte des heures. Le type « Activité » est en
    # heures, mais une mission prend par défaut des journées entières ; la durée choisie ici
    # donne la demi-journée ou les heures personnalisées d'Odoo (request_unit_half/hours).
    mission_hourly = fields.Boolean(
        string="Mission à l'heure", compute='_compute_mission_hourly',
        help="La mission est facturée à l'heure à la date de la saisie.")
    mission_duration = fields.Selection(
        [('day', "Journée entière"), ('half', "Demi-journée"), ('hours', "Heures")],
        string="Durée", default='day',
        help="Mission facturée à l'heure : une journée entière compte les heures de travail du "
             "jour, une demi-journée la moitié, des heures choisies exactement leurs heures.")

    @api.depends('project_id', 'request_date_from')
    def _compute_mission_hourly(self):
        for leave in self:
            leave.mission_hourly = bool(leave.project_id) and \
                leave.project_id.sudo()._mission_billing_unit_on(leave.request_date_from) == 'hour'

    @api.depends('leave_type_request_unit', 'project_id', 'mission_duration')
    def _compute_request_unit_half(self):
        missions = self.filtered('project_id')
        super(HrLeave, self - missions)._compute_request_unit_half()
        for leave in missions:
            leave.request_unit_half = leave.mission_duration == 'half'

    @api.depends('leave_type_request_unit', 'project_id', 'mission_duration')
    def _compute_request_unit_hours(self):
        missions = self.filtered('project_id')
        super(HrLeave, self - missions)._compute_request_unit_hours()
        for leave in missions:
            leave.request_unit_hours = leave.mission_duration == 'hours'

    @api.depends('number_of_hours', 'number_of_days', 'leave_type_request_unit', 'project_id',
                 'request_date_from')
    def _compute_duration_display(self):
        # Le type « Activité » est en heures : une mission au jour s'affiche tout de même en jours.
        super()._compute_duration_display()
        for leave in self.filtered('project_id'):
            if leave.mission_hourly:
                hours, minutes = divmod(round(abs(leave.number_of_hours) * 60), 60)
                leave.duration_display = "%d:%02d %s" % (hours, minutes, _("heures"))
            else:
                leave.duration_display = "%g %s" % (
                    float_round(leave.number_of_days, precision_digits=2), _("jours"))

    def _get_durations(self, check_leave_type=True, resource_calendar=None):
        # Une demi-journée de mission compte la moitié des heures du jour, quelle que soit la
        # coupure du calendrier entre le matin et l'après-midi.
        result = super()._get_durations(check_leave_type=check_leave_type, resource_calendar=resource_calendar)
        for leave in self.filtered(lambda l: l.project_id and l.mission_duration == 'half'
                                   and l.employee_id and l.date_from and l.date_to):
            days, _hours = result[leave.id]
            result[leave.id] = (days, sum(leave._mission_hours_by_day().values()))
        return result

    def _mission_hours_by_day(self):
        """{date: heures} de la saisie, jour par jour, selon le calendrier du salarié.

        Journée entière : les heures de travail du jour ; demi-journée : la moitié
        (le premier jour pris l'après-midi, le dernier le matin, ou le jour seul pris
        le matin ou l'après-midi) ; heures personnalisées : les heures de travail
        comprises entre le début et la fin. Jours fériés exclus.
        """
        self.ensure_one()
        employee = self.employee_id.sudo()
        if not (employee and self.request_date_from and self.request_date_to):
            return {}
        if self.mission_duration == 'hours' and self.request_date_from == self.request_date_to:
            # Un seul jour : les heures calculées par Odoo, celles qu'affiche la saisie.
            return {self.request_date_from: round(self.number_of_hours, 2)} if self.number_of_hours else {}
        tz = pytz.timezone(employee.tz or self.tz or 'UTC')
        work, tz = work_intervals(self.env, employee, self.request_date_from, self.request_date_to,
                                  calendar=self.resource_calendar_id, tz=tz)
        if work is None:
            return {}
        if self.mission_duration == 'hours' and self.date_from and self.date_to:
            work = work & Intervals([(pytz.utc.localize(self.date_from).astimezone(tz),
                                      pytz.utc.localize(self.date_to).astimezone(tz),
                                      self.env['resource.calendar.attendance'])])
        result = hours_by_day(work)
        if self.mission_duration == 'half':
            first, last = self.request_date_from, self.request_date_to
            start, stop = self.request_date_from_period, self.request_date_to_period

            def halved(day):
                if first == last:
                    return start == stop
                return (day == first and start == 'pm') or (day == last and stop == 'am')

            result = {day: hours / 2 if halved(day) else hours for day, hours in result.items()}
        return {day: round(hours, 2) for day, hours in result.items() if hours}

    @api.depends('employee_id')
    def _compute_available_project_ids(self):
        for record in self:
            user = record.employee_id.user_id
            if user:
                # sudo : la règle de visibilité des tâches cacherait celles de l'employé
                # à un responsable qui saisit pour lui ; seuls les projets sont gardés.
                tasks = self.env['project.task'].sudo().search([('user_ids', 'in', user.id)])
                record.available_project_ids = self.env['project.project'].browse(tasks.project_id.ids)
            else:
                record.available_project_ids = self.env['project.project']

    @api.model
    def _mission_projects_for_period(self, employee, date_from, date_to):
        """Missions de l'employé (une tâche lui est assignée) actives sur la période.

        Une mission est écartée quand ses dates, ou celles de toutes ses affaires
        datées, ne touchent pas la période. Dans l'ordre de la liste des missions.
        """
        user = employee.user_id
        if not user:
            return self.env['project.project']
        # sudo : voir _compute_available_project_ids ; seuls les projets sont gardés.
        tasks = self.env['project.task'].sudo().search([('user_ids', 'in', user.id)])
        projects = self.env['project.project'].browse(tasks.project_id.ids)
        date_from = date_from or fields.Date.context_today(self)
        date_to = date_to or date_from

        def active(project):
            project = project.sudo()
            if (project.date_start and project.date_start > date_to) or                     (project.date and project.date < date_from):
                return False
            dated = project.sudo()._mission_all_orders().filtered(
                lambda o: o.mission_date_start and o.mission_date_end)
            return not dated or any(
                o.mission_date_start <= date_to and o.mission_date_end >= date_from for o in dated)

        return projects.filtered(active)

    @api.onchange('employee_id')
    def _onchange_employee_id_mission(self):
        """Une autre personne : sa première mission de la période, si la mission choisie n'est pas la sienne."""
        if self.entry_type == 'leave' or not self.employee_id:
            return
        projects = self._mission_projects_for_period(
            self.employee_id, self.request_date_from, self.request_date_to)
        if self.project_id not in projects:
            self.project_id = projects[:1]

    @api.depends('project_id', 'holiday_status_id')
    def _compute_entry_type(self):
        for record in self:
            if record.holiday_status_id and not self._is_activity_leave_type(record.holiday_status_id):
                record.entry_type = 'leave'
            else:
                record.entry_type = 'mission'

    @api.onchange('entry_type')
    def _onchange_entry_type(self):
        if self.entry_type == 'leave':
            self.project_id = False
            if not self.holiday_status_id or self._is_activity_leave_type(self.holiday_status_id):
                self.holiday_status_id = self.env['hr.leave.type'].search([], limit=1)
        else:
            self.holiday_status_id = False
            if not self.project_id:
                self.project_id = self.available_project_ids[:1]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'holiday_status_id' in res:
            res['holiday_status_id'] = False
        if 'project_id' in fields_list and not res.get('project_id')                 and not self.env.context.get('default_holiday_status_id'):
            employee = self.env['hr.employee'].browse(res.get('employee_id'))                 or self.env.user.employee_id
            res['project_id'] = self._mission_projects_for_period(
                employee, res.get('request_date_from'), res.get('request_date_to'))[:1].id or False
        if res.get('project_id') and 'mission_duration' in fields_list:
            # Un créneau horaire du calendrier (vue semaine ou jour) : des heures, sur une mission
            # à l'heure seulement.
            hourly = self.env['project.project'].browse(res['project_id']).sudo()._mission_billing_unit_on(
                fields.Date.to_date(res.get('request_date_from'))) == 'hour'
            res['mission_duration'] = 'hours' if hourly and res.get('request_unit_hours') else 'day'
            for name, duration in (('request_unit_hours', 'hours'), ('request_unit_half', 'half')):
                if name in res:
                    res[name] = res['mission_duration'] == duration
        return res

    @api.model
    def _get_default_activity_leave_type(self):
        # requires_allocation is a Boolean (hr_leave_type.py:88), so it must be
        # False - not 'no', which is a truthy string and made every mission
        # entry fail hr_holidays' allocation check.
        # The type normally comes from data/hr_leave_type_data.xml. That record
        # is noupdate, so a pre-existing one created with the wrong value never
        # gets corrected by a module update: check it here and fall back to a
        # correctly configured type instead. Never write to an existing type -
        # Odoo forbids changing a leave type's allocation policy once any leave
        # uses it.
        leave_type = self.env.ref('mission_report.hr_leave_type_activite', raise_if_not_found=False)
        if leave_type and not leave_type.requires_allocation:
            return leave_type
        leave_type = self.env['hr.leave.type'].with_context(active_test=False).search(
            [('name', '=', 'Activité'), ('requires_allocation', '=', False)], limit=1)
        if not leave_type:
            leave_type = self.env['hr.leave.type'].create({
                'name': 'Activité',
                'requires_allocation': False,
                'leave_validation_type': 'no_validation',
                'request_unit': 'hour',
                'active': False,
            })
        return leave_type

    def _is_activity_leave_type(self, leave_type):
        return bool(leave_type) and leave_type.name == 'Activité'

    def _get_mission_only_employees(self):
        """Parmi ces saisies, les employés qui n'ont que des missions.

        Un congé l'emporte sur une mission : il reste le motif d'absence à
        afficher. Le critère mission est project_id : entry_type est calculé
        et non stocké.
        """
        on_mission = self.filtered('project_id').employee_id
        on_leave = self.filtered(lambda leave: not leave.project_id).employee_id
        return on_mission - on_leave

    @api.model_create_multi
    def create(self, vals_list):
        activity_type = self._get_default_activity_leave_type()
        Project = self.env['project.project'].sudo()
        for vals in vals_list:
            if vals.get('project_id'):
                self._mission_prepare_duration(vals, Project.browse(vals['project_id']))
            if vals.get('project_id') and not vals.get('holiday_status_id'):
                vals['holiday_status_id'] = activity_type.id
            elif 'project_id' not in vals and vals.get('holiday_status_id') and                     not self._is_activity_leave_type(self.env['hr.leave.type'].browse(vals['holiday_status_id'])):
                # Un congé créé par code (congé groupé, import) : pas de mission par défaut.
                vals['project_id'] = False
        return super().create(vals_list)

    @api.model
    def _mission_prepare_duration(self, vals, project):
        """La durée d'une mission : demi-journée et heures pour une mission à l'heure seulement.

        Les cases d'Odoo (request_unit_half/hours) se déduisent de la durée : passées par un
        créneau du calendrier, elles la donnent quand la durée n'est pas fournie.
        """
        hours, half = vals.pop('request_unit_hours', False), vals.pop('request_unit_half', False)
        hourly = project._mission_billing_unit_on(fields.Date.to_date(vals.get('request_date_from'))) == 'hour'
        if not hourly:
            if vals.get('mission_duration', 'day') == 'day':
                vals['mission_duration'] = 'day'
        elif 'mission_duration' not in vals and (hours or half):
            vals['mission_duration'] = 'hours' if hours else 'half'

    # Champs qui décident des journées d'une saisie : figés une fois la saisie reprise dans un
    # compte rendu soumis ou validé, ou facturée.
    MISSION_LOCK_FIELDS = (
        'request_date_from', 'request_date_to', 'date_from', 'date_to', 'request_hour_from',
        'request_hour_to', 'request_unit_half', 'request_unit_hours', 'mission_duration',
        'project_id', 'employee_id')

    def _mission_lock_reason(self):
        """Le motif qui interdit de modifier les journées de la saisie, sinon False."""
        self.ensure_one()
        start = self.request_date_from
        end = self.request_date_to or start
        if not start or not self.employee_id:
            return False
        Report = self.env['mission.activity.report'].sudo()
        report = Report.search([
            ('employee_id', '=', self.employee_id.id), ('state', 'in', ('submitted', 'validated')),
            ('date_from', '<=', end), ('date_to', '>=', start)], limit=1)
        if report:
            return _("Cette saisie figure dans le compte rendu « %(report)s » (%(state)s) : ses journées "
                     "ne peuvent plus être modifiées.", report=report.display_name,
                     state=dict(report._fields['state'].selection)[report.state].lower())
        if self.project_id:
            first, last = start.replace(day=1), end.replace(day=1)
            invoices = self.project_id.sudo()._mission_all_orders().invoice_ids.filtered(
                lambda m: m.state != 'cancel' and m.mission_month and first <= m.mission_month <= last)
            if invoices:
                return _("Cette saisie a été facturée (%(invoices)s) : ses journées ne peuvent plus être "
                         "modifiées.", invoices=", ".join(invoices.mapped('name')))
        return False

    def _mission_check_unlocked(self):
        for leave in self:
            reason = leave._mission_lock_reason()
            if reason:
                raise UserError(reason)

    def action_back_to_approval(self):
        self._mission_check_unlocked()
        return super().action_back_to_approval()

    def action_mission_restore(self):
        """Fin d'une réouverture sans ré-approbation : la saisie retrouve son approbation."""
        pending = self.exists().filtered(lambda leave: leave.state == 'confirm')
        if pending:
            pending.action_approve()
        return True

    def unlink(self):
        self._mission_check_unlocked()
        return super().unlink()

    @api.constrains('date_from', 'date_to', 'employee_id', 'request_unit_hours', 'request_unit_half')
    def _check_mission_working_day(self):
        """Odoo accepte une demande sans aucun jour travaillé (un dimanche, un jour férié) : une
        durée de 0 jour. Ici elle est refusée."""
        for leave in self:
            if leave.state in ('refuse', 'cancel') or not leave.employee_id:
                continue
            if not (leave.request_date_from and leave.request_date_to):
                continue
            if leave.request_unit_hours or leave.mission_duration == 'hours':
                continue  # heures saisies : leur durée n'est connue qu'une fois l'enregistrement fait
            # Les heures travaillées selon le calendrier du salarié, jours fériés exclus : la même
            # base que les comptes rendus (Odoo ne calcule pas de durée pour une saisie neuve).
            if float_is_zero(sum(leave._mission_hours_by_day().values()), precision_digits=2):
                raise ValidationError(_(
                    "Cette période ne compte aucun jour travaillé (week-end ou jour férié) : "
                    "choisissez d'autres dates."))

    def write(self, vals):
        # Self-heal records still pointing at a stale/misconfigured Activité type
        # (e.g. created before _get_default_activity_leave_type started avoiding
        # writes to existing types) *before* the real write, so Odoo's own
        # validation logic (which runs on every save, not just when
        # holiday_status_id itself changes) doesn't see the stale value.
        if 'holiday_status_id' not in vals:
            activity_type = self._get_default_activity_leave_type()
            for record in self:
                project_id = vals.get('project_id', record.project_id.id)
                if project_id and record.holiday_status_id != activity_type:
                    super(HrLeave, record).write({'holiday_status_id': activity_type.id})
        if self.env.context.get(INTERNAL_KEY) != INTERNAL and any(f in vals for f in self.MISSION_LOCK_FIELDS):
            self.filtered(lambda leave: leave.state not in ('refuse', 'cancel'))._mission_check_unlocked()
        return super().write(vals)

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.holiday_status_id = False

    @api.onchange('request_unit_half', 'mission_duration', 'request_date_from', 'request_date_from_period')
    def _onchange_mission_single_half_day(self):
        """Une demi-journée tient sur un seul jour : la fin suit le début, et l'une comme l'autre
        sont du même moment (matin ou après-midi)."""
        if self.request_unit_half and self.request_date_from:
            self.request_date_to = self.request_date_from
            self.request_date_to_period = self.request_date_from_period

    @api.onchange('project_id', 'request_date_from')
    def _onchange_mission_duration(self):
        # Une mission au jour se saisit en journées entières.
        if self.project_id and not self.mission_hourly:
            self.mission_duration = 'day'

    @api.constrains('project_id', 'mission_duration')
    def _check_mission_duration(self):
        for record in self:
            if record.project_id and record.mission_duration != 'day' and not record.mission_hourly:
                raise ValidationError(_(
                    "La mission %s est facturée au jour : saisissez des journées entières.",
                    record.project_id.display_name))

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        if self.holiday_status_id and not self._is_activity_leave_type(self.holiday_status_id):
            self.project_id = False

    @api.constrains('project_id', 'holiday_status_id')
    def _check_mission_or_leave_exclusive(self):
        for record in self:
            is_mission = bool(record.project_id)
            is_leave = bool(record.holiday_status_id) and not self._is_activity_leave_type(record.holiday_status_id)
            if is_mission == is_leave:
                raise ValidationError(
                    _("Une saisie doit posséder soit une Mission soit un Congé, mais pas les deux ni aucun des deux.")
                )

    @api.constrains('project_id', 'employee_id')
    def _check_employee_assigned_to_project(self):
        for record in self:
            if not record.project_id or not record.employee_id:
                continue
            user = record.employee_id.user_id
            has_task = user and self.env['project.task'].sudo().search_count([
                ('project_id', '=', record.project_id.id),
                ('user_ids', 'in', user.id),
            ])
            if not has_task:
                raise ValidationError(
                    _("%(employee)s n'est assigné(e) à aucune tâche du projet %(project)s.",
                      employee=record.employee_id.name, project=record.project_id.name)
                )

    # --- Vocabulaire : "congé" -> "activité" dans les textes produits par hr_holidays ---
    #
    # Ces chaînes viennent du code Python d'hr_holidays. Un module ne peut pas
    # traduire les chaînes de code d'un autre module (chaque catalogue est chargé
    # depuis le .po du module qui le déclare), et ce ne sont ni des vues ni des
    # libellés de champs : on réécrit donc le texte une fois produit.
    #
    # Les substitutions portent sur le français, seule langue de ce module. Dans
    # une autre langue elles ne trouvent rien et sont sans effet - le texte
    # d'origine reste affiché, rien ne casse.
    _ACTIVITY_WORDING = {
        # Posté par create() quand le type ne demande aucune validation, ce qui
        # est le cas de toutes les missions.
        "Le congé a été automatiquement approuvé":
            "La saisie a été automatiquement approuvée",
        # Bandeau de chevauchement. Fragment commun aux deux variantes du
        # message ("Vous avez déjà..." et "Un employé a déjà...").
        "réservé un congé": "saisi une activité",
    }

    def _apply_activity_wording(self, text):
        for source, replacement in self._ACTIVITY_WORDING.items():
            text = text.replace(source, replacement)
        return text

    def _creation_message(self):
        # Chatter : le message natif est "<nom du modèle> créé", soit
        # "Congés créé" - mauvais vocabulaire et mauvais genre.
        self.ensure_one()
        return _("Activité créée")

    # Posté par _validate_leave_request() à la validation, immédiate pour une
    # mission. En français : "Votre Activité planifié le 2026-09-28 08:00:00 a
    # été accepté" - accord masculin écrit pour un nom de congé, date brute.
    _ACCEPTED_MESSAGE = 'Your %(leave_type)s planned on %(date)s has been accepted'

    def _is_accepted_message(self, text):
        # Le gabarit est lu dans le catalogue d'hr_holidays, dans la langue du
        # message : la reconnaissance vaut quelle que soit la langue.
        template = code_translations.get_python_translations('hr_holidays', self.env.lang or 'en_US').get(
            self._ACCEPTED_MESSAGE, self._ACCEPTED_MESSAGE)
        pattern = ''
        for index, part in enumerate(re.split(r'%\((leave_type|date)\)s', template)):
            if index % 2 == 0:
                pattern += re.escape(part)
            elif part == 'leave_type':
                pattern += re.escape(self.holiday_status_id.display_name or '')
            else:
                pattern += '.+?'
        return bool(re.fullmatch(pattern, text.strip()))

    def _get_accepted_mission_message(self):
        self.ensure_one()
        date_from = format_date(self.env, self.request_date_from)
        if self.request_date_to and self.request_date_to != self.request_date_from:
            return _("Votre activité du %(date_from)s au %(date_to)s a été enregistrée",
                     date_from=date_from, date_to=format_date(self.env, self.request_date_to))
        return _("Votre activité du %(date)s a été enregistrée", date=date_from)

    def message_post(self, **kwargs):
        body = kwargs.get('body')
        if body:
            if len(self) == 1 and self.project_id and self._is_accepted_message(str(body)):
                kwargs['body'] = self._get_accepted_mission_message()
                return super().message_post(**kwargs)
            rewritten = self._apply_activity_wording(str(body))
            if rewritten != str(body):
                kwargs['body'] = Markup(rewritten) if isinstance(body, Markup) else rewritten
        return super().message_post(**kwargs)

    def _compute_dashboard_warning_message(self):
        super()._compute_dashboard_warning_message()
        for record in self:
            if record.dashboard_warning_message:
                record.dashboard_warning_message = self._apply_activity_wording(
                    record.dashboard_warning_message
                )

    # --- Vocabulaire : "congé" -> "activité" dans les autres applications ---
    #
    # À la validation, hr_holidays crée pour chaque saisie un événement dans
    # l'application Calendrier et une absence dans le calendrier de ressources.
    # Leurs noms sont construits en Python par hr_holidays : ils disent "congé"
    # même pour une mission. On les renomme plutôt que de recopier les méthodes
    # d'origine - si leur signature changeait, seul le nom resterait celui
    # d'hr_holidays, sans rien casser.
    #
    # Le critère est project_id : entry_type est calculé et non stocké.

    def _get_activity_meeting_name(self):
        self.ensure_one()
        return _(
            "%(employee)s en activité : %(duration)s",
            employee=self.employee_id.name,
            duration=self.duration_display,
        )

    def _prepare_holidays_meeting_values(self):
        values_by_user = super()._prepare_holidays_meeting_values()
        missions = {leave.id: leave for leave in self if leave.project_id}
        for meeting_values in values_by_user.values():
            for values in meeting_values:
                # res_id porte l'identifiant de la saisie d'origine.
                leave = missions.get(values.get('res_id'))
                if leave:
                    values['name'] = leave._get_activity_meeting_name()
        return values_by_user

    def _prepare_resource_leave_vals(self):
        values = super()._prepare_resource_leave_vals()
        if self.project_id:
            values['name'] = _("%s : activité", self.employee_id.name)
        return values

    # --- Vocabulaire : menus, actions et champs d'hr_holidays renommés par ce module ---
    #
    # Redéfinir en XML le nom d'un menu ou d'une action d'un autre module n'écrit
    # que la valeur anglaise : la traduction française d'hr_holidays reste en
    # place et l'emporte ("Mes congés", "Tous les congés" dans les menus et le
    # fil d'Ariane). Même chose pour le libellé d'un champ redéfini en Python.
    # On recopie donc, à chaque mise à jour du module, notre valeur vers les
    # autres langues installées.
    #
    # Seuls les champs traduits d'un bloc sont concernés : les vues et les textes
    # d'aide sont traduits par fragments, et nos textes n'y ont pas de traduction.
    _RENAMED_RECORDS = (
        # views/menu_views.xml
        'hr_holidays.menu_hr_holidays_my_leaves',
        'hr_holidays.menu_hr_holidays_dashboard',
        'hr_holidays.menu_hr_holidays_management',
        'hr_holidays.menu_hr_holidays_report',
        'hr_holidays.menu_hr_holidays_configuration',
        'hr_holidays.hr_leave_menu_my',
        'hr_holidays.menu_open_department_leave_approve',
        # views/activity_report_views.xml
        'mission_report.menu_mission_activity_report_all',
        # views/hr_leave_views.xml
        'hr_holidays.hr_leave_action_my',
        'hr_holidays.hr_leave_action_action_approve_department',
        # views/hr_leave_report_calendar_views.xml
        'hr_holidays.action_hr_holidays_dashboard',
    )
    _RENAMED_FIELDS = (
        # Titre du filtre du calendrier de saisie, qui ne lit que le libellé du
        # champ : "Type de congés" d'hr_holidays.
        ('hr.leave', 'holiday_status_id'),
    )

    @api.model
    def _sync_renamed_records_translations(self):
        langs = [code for code, _name in self.env['res.lang'].get_installed() if code != 'en_US']
        if not langs:
            return
        for xmlid in self._RENAMED_RECORDS:
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if not record:
                continue
            name = record.with_context(lang='en_US').name
            record.update_field_translations('name', {lang: name for lang in langs})
        for model_name, field_name in self._RENAMED_FIELDS:
            field = self.env['ir.model.fields']._get(model_name, field_name)
            description = field.with_context(lang='en_US').field_description
            field.update_field_translations('field_description', {lang: description for lang in langs})
        # Les libellés de champs sont mis en cache par le registre.
        self.env.registry.clear_cache()

    def action_mission_show_overview(self):
        """Situe la saisie dans la vue d'ensemble : le mois de son début, tout le monde affiché.

        L'approbateur la voit parmi les autres saisies et la valide, en contexte, avec la
        fenêtre du calendrier.
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('hr_holidays.action_hr_holidays_dashboard')
        context = safe_eval(action.get('context') or '{}', {'uid': self.env.uid})
        context.pop('search_default_my_team', None)
        context.update({
            'initial_date': "%s 00:00:00" % self.request_date_from,
            'mission_scale': 'month',
        })
        action['context'] = context
        return action
