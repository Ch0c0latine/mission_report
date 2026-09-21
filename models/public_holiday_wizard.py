# -*- coding: utf-8 -*-
"""Generate the French public holidays of a year.

Odoo stores public holidays as resource.calendar.leaves without a resource,
entered by hand under Configuration > Public Holidays. Nothing is entered
out of the box: missions then count 14 July or 25 December as worked days,
and activity reports cannot show them.
"""
from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def easter_sunday(year):
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def french_public_holidays(env, year, alsace_moselle=False):
    """[(date, name)] of the French public holidays of a year, by date."""
    easter = easter_sunday(year)
    holidays = [
        (date(year, 1, 1), env._("New Year's Day")),
        (easter + timedelta(days=1), env._("Easter Monday")),
        (date(year, 5, 1), env._("Labour Day")),
        (date(year, 5, 8), env._("Victory in Europe Day")),
        (easter + timedelta(days=39), env._("Ascension Day")),
        (easter + timedelta(days=50), env._("Whit Monday")),
        (date(year, 7, 14), env._("Bastille Day")),
        (date(year, 8, 15), env._("Assumption Day")),
        (date(year, 11, 1), env._("All Saints' Day")),
        (date(year, 11, 11), env._("Armistice Day")),
        (date(year, 12, 25), env._("Christmas Day")),
    ]
    if alsace_moselle:
        holidays += [
            (easter - timedelta(days=2), env._("Good Friday")),
            (date(year, 12, 26), env._("St. Stephen's Day")),
        ]
    return sorted(holidays)


class MissionPublicHolidayWizard(models.TransientModel):
    _name = 'mission.public.holiday.wizard'
    _description = "Generate French public holidays"

    year = fields.Integer(required=True, default=lambda self: fields.Date.today().year)
    company_id = fields.Many2one(
        'res.company', string="Company", required=True, default=lambda self: self.env.company)
    alsace_moselle = fields.Boolean(
        string="Alsace-Moselle",
        help="Adds Good Friday and St. Stephen's Day (26 December).")

    @api.constrains('year')
    def _check_year(self):
        for wizard in self:
            if not 1900 <= wizard.year <= 2999:
                raise UserError(_("Enter a year between 1900 and 2999."))

    def action_generate(self):
        self.ensure_one()
        created = self._generate()
        message = _("%(count)s public holiday(s) created for %(year)s.",
                    count=len(created), year=self.year) if created \
            else _("The public holidays of %s were already entered.", self.year)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'success' if created else 'info',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _generate(self):
        """Create the missing holidays; return the created records.

        Days already covered by a public holiday of the company are skipped:
        hr_holidays forbids two overlapping public holidays, and a second
        run of the wizard must not fail.

        Creating a public holiday makes hr_holidays re-evaluate the entries
        it overlaps: their duration shrinks, and an entry left with no day
        at all is refused.
        """
        self.ensure_one()
        tz = pytz.timezone(self.company_id.resource_calendar_id.tz or self.env.user.tz or 'UTC')
        Leaves = self.env['resource.calendar.leaves']
        vals_list = []
        for day, name in french_public_holidays(self.env, self.year, self.alsace_moselle):
            date_from = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
            date_to = tz.localize(datetime.combine(day, time(23, 59, 59))).astimezone(pytz.utc).replace(tzinfo=None)
            if Leaves.search_count([
                ('resource_id', '=', False),
                ('company_id', '=', self.company_id.id),
                ('date_from', '<=', date_to),
                ('date_to', '>=', date_from),
            ]):
                continue
            vals_list.append({
                'name': name,
                'company_id': self.company_id.id,
                'calendar_id': False,
                'date_from': date_from,
                'date_to': date_to,
                'time_type': 'leave',
            })
        return Leaves.create(vals_list) if vals_list else Leaves
