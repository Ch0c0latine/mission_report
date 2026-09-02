# -*- coding: utf-8 -*-
{
    'name': 'Activité',
    'version': '19.0.1.0.0',
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
        'hr',
        'hr_holidays',
        'project',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_leave_type_data.xml',
        'views/hr_leave_views.xml',
        'views/menu_views.xml',
        'views/hr_leave_reporting.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mission_report/static/src/scss/mission_report.scss',
            'mission_report/static/src/views/view_dialog/form_view_dialog.xml',
            'mission_report/static/src/js/translation_overrides.js',
        ],
    },
    'installable': True,
    'application': True,
}
