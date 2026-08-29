# -*- coding: utf-8 -*-
{
    'name': 'Activité',
    'version': '19.0.1.0.0',
    'summary': "Saisie d'activité et de rapports de mission par projet",
    'description': """
        Module Odoo 19 pour la saisie de rapports d'activité et de missions par projet,
        adaptant la logique du module standard des congés (hr_holidays).
    """,
    'category': 'Productivity',
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
    'auto_install': False,
}
