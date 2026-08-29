# -*- coding: utf-8 -*-
{
    'name': 'Mission Report',
    'version': '19.0.1.0.0',
    'summary': 'Activity and mission reports by project based on leaves logic',
    'description': """
        Module mission_report adapting hr_holidays logic for activity and mission reporting by project.
    """,
    'category': 'Human Resources / Attendance',
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
        'views/hr_leave_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}
