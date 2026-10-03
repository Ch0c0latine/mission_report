# -*- coding: utf-8 -*-
"""Temps de travail d'un salarié d'après son calendrier : heures par jour."""
from collections import defaultdict
from datetime import datetime, time

import pytz

from odoo.tools.intervals import Intervals

from .public_holiday_wizard import mission_timezone


def work_intervals(env, employee, start, end, leaves=False, calendar=None, tz=None):
    """(intervalles, fuseau) de travail de l'employé du jour ``start`` au jour ``end`` inclus.

    Selon son calendrier de travail (ou ``calendar``), jours fériés déduits ; avec
    ``leaves``, les congés posés ou demandés aussi (les saisies de mission, elles, ne
    comptent pas comme absence). Les intervalles sont en heure locale ; sans
    calendrier : (None, fuseau).
    """
    employee = employee.sudo()
    calendar = calendar or employee.resource_calendar_id or employee.company_id.resource_calendar_id
    tz = tz or mission_timezone(employee.company_id, employee)
    if not calendar:
        return None, tz
    start_dt = tz.localize(datetime.combine(start, time.min))
    end_dt = tz.localize(datetime.combine(end, time.max))
    resource = employee.resource_id
    # Hors absences des ressources rattachées à une saisie : les congés sont repris plus bas.
    work = calendar._work_intervals_batch(
        start_dt, end_dt, resources=resource, tz=tz,
        domain=[('time_type', '=', 'leave'), ('holiday_id', '=', False)])[resource.id]
    if not leaves:
        return work, tz
    found = env['hr.leave'].sudo().search([
        ('employee_id', '=', employee.id), ('project_id', '=', False),
        ('state', 'in', ('confirm', 'validate1', 'validate')),
        ('date_from', '<=', end_dt.astimezone(pytz.utc).replace(tzinfo=None)),
        ('date_to', '>=', start_dt.astimezone(pytz.utc).replace(tzinfo=None))])
    cuts = []
    for leave in found:
        first = max(start_dt, pytz.utc.localize(leave.date_from).astimezone(tz))
        last = min(end_dt, pytz.utc.localize(leave.date_to).astimezone(tz))
        if first < last:
            cuts.append((first, last, leave))
    return work - Intervals(cuts), tz


def hours_by_day(intervals):
    """{date: heures} des intervalles."""
    hours = defaultdict(float)
    for first, last, _meta in intervals or []:
        hours[first.date()] += (last - first).total_seconds() / 3600
    return dict(hours)
