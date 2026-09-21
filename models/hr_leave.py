# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


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

    @api.depends('employee_id')
    def _compute_available_project_ids(self):
        for record in self:
            user = record.employee_id.user_id
            if user:
                tasks = self.env['project.task'].search([('user_ids', 'in', user.id)])
                record.available_project_ids = tasks.project_id
            else:
                record.available_project_ids = self.env['project.project']

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
        for vals in vals_list:
            if vals.get('project_id') and not vals.get('holiday_status_id'):
                vals['holiday_status_id'] = activity_type.id
        return super().create(vals_list)

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
        return super().write(vals)

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.holiday_status_id = False

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
            has_task = user and self.env['project.task'].search_count([
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

    def message_post(self, **kwargs):
        body = kwargs.get('body')
        if body:
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
