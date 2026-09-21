# -*- coding: utf-8 -*-
"""Renomme les enregistrements déjà créés sous l'ancien vocabulaire.

Les noms de l'événement Calendrier et de l'absence du calendrier de ressources
sont figés à la validation de la saisie : les missions enregistrées avant cette
version continuent d'afficher "en congé" tant qu'on ne les réécrit pas.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    missions = env['hr.leave'].search([('project_id', '!=', False)])
    for mission in missions:
        meeting = mission.meeting_id
        if meeting:
            name = mission._get_activity_meeting_name()
            if meeting.name != name:
                meeting.name = name
    resource_leaves = env['resource.calendar.leaves'].search([
        ('holiday_id', 'in', missions.ids),
    ])
    for resource_leave in resource_leaves:
        name = resource_leave.holiday_id._prepare_resource_leave_vals()['name']
        if resource_leave.name != name:
            resource_leave.name = name
