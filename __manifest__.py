# -*- coding: utf-8 -*-
{
    'name': 'Activité',
    'version': '19.0.1.2.1',
    'summary': 'Activity and mission reports by project based on leaves logic',
    'description': """
        Module mission_report adapting hr_holidays logic for activity and mission reporting by project.
    """,
    'category': 'Human Resources',
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_holidays',
        # Pont auto-installé avec hr_holidays. Il patche lui aussi le badge de
        # présence : en dépendre charge notre patch après le sien, sans quoi il
        # affiche l'avion pour toute valeur contenant "holiday".
        'hr_holidays_homeworking',
        'project',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_leave_type_data.xml',
        'views/hr_leave_views.xml',
        'views/menu_views.xml',
        'views/hr_leave_report_calendar_views.xml',
        'views/hr_leave_reporting.xml',
        'views/hr_employee_views.xml',
        'security/activity_report_security.xml',
        'report/activity_report.xml',
        'views/activity_report_views.xml',
        'data/activity_report_template_data.xml',
        'data/wording_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mission_report/static/src/scss/mission_report.scss',
            'mission_report/static/src/js/translation_overrides.js',
            'mission_report/static/src/js/presence_status.js',
            'mission_report/static/src/xml/avatar_card_resource_popover.xml',
        ],
    },
    'installable': True,
    'application': True,
}
