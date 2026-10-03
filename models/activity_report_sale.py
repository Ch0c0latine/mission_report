# -*- coding: utf-8 -*-
"""Validated activity reports feed the sales order lines of their missions.

The days of a validated monthly report, per mission, are added up and set as
the delivered quantity of the order line the project belongs to. Nothing is
typed by hand: the next invoice takes the days delivered since the last one.
A report sent back to draft takes its days back.
"""
import logging
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class MissionActivityReport(models.Model):
    _inherit = 'mission.activity.report'

    def action_validate(self):
        result = super().action_validate()
        self._sale_sync_delivered(self._sale_project_ids())
        return result

    def action_reset_to_draft(self):
        # The days leave with the snapshot: note the projects first.
        project_ids = self._sale_project_ids()
        result = super().action_reset_to_draft()
        self._sale_sync_delivered(project_ids)
        return result

    def _sale_project_ids(self):
        """Missions that appear in the figures of these reports."""
        ids = set()
        for report in self:
            data = report.snapshot if report.state == 'validated' and report.snapshot else {}
            ids.update(line.get('project_id') for line in data.get('missions', []) if line.get('project_id'))
        return ids

    @api.model
    def _sale_validated_days(self):
        """{project id: [(date, days)]} over all the validated reports."""
        result = {}
        for report in self.sudo().search([('state', '=', 'validated')]):
            data = report.snapshot or {}
            days = data.get('days', [])
            for line in data.get('missions', []):
                project_id = line.get('project_id')
                if not project_id:
                    continue
                for day, value in zip(days, line.get('values', [])):
                    if value:
                        result.setdefault(project_id, []).append((fields.Date.to_date(day['date']), value))
        return result

    @api.model
    def _sale_lines_of(self, project):
        """Lignes de journées de la mission, toutes affaires confondues.

        Seulement celles sans projet ou de ce projet : une commande peut porter
        plusieurs missions.
        """
        lines = project.sale_line_id
        Line = self.env['sale.order.line'].sudo()
        if 'project_id' in Line._fields:
            lines |= Line.search([('project_id', '=', project.id)])
        for order in project.sudo()._mission_all_orders():
            lines |= order.order_line
        return lines.filtered(
            lambda l: l.mission_day_line and l.qty_delivered_method == 'manual' and l.state == 'sale'
            and (not l.project_id or l.project_id == project))

    @api.model
    def _sale_sync_delivered(self, project_ids=None, days=None):
        """Set the delivered days of the missions' order lines.

        Without ``project_ids``, every mission with a validated report. A day
        goes to the order of the mission whose period contains it, then to the
        day line of that order whose period (one month of the volet) contains
        it, or the nearest one. An order without periods on its lines shares
        the days between its day lines in proportion to their ordered quantity.
        """
        if days is None:
            days = self._sale_validated_days()
        ids = set(project_ids) if project_ids is not None else set(days)
        for project in self.env['project.project'].sudo().browse(sorted(ids)).exists():
            lines = self._sale_lines_of(project)
            # Jours par groupe de lignes qui se les partagent.
            totals = defaultdict(float)
            for day, value in days.get(project.id, []):
                order = project._mission_order_on(day)
                order_lines = lines.filtered(lambda l: l.order_id == order)
                if order_lines:
                    totals[order_lines._mission_lines_on(day)] += value
            delivered = defaultdict(float)
            for group, total in totals.items():
                for line, share in group._mission_prorata(total):
                    delivered[line] += share
            for line in lines:
                share = delivered[line]
                if float_compare(line.qty_delivered, share, precision_digits=2):
                    try:
                        with self.env.cr.savepoint():
                            line.write({'qty_delivered': share})
                    except Exception:  # noqa: BLE001 - never block a validation
                        _logger.warning("Could not set the delivered days of %s", line.display_name,
                                        exc_info=True)

    @api.model
    def _cron_sale_sync_delivered(self):
        """Safety net: every mission with a validated report."""
        self._sale_sync_delivered()


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        result = super().action_confirm()
        # Les journées déjà validées de la période passent sur l'affaire confirmée.
        projects = self.sudo()._mission_projects()
        if projects:
            Report = self.env['mission.activity.report'].sudo()
            days = Report._sale_validated_days()
            project_ids = set(projects.ids) & set(days)
            if project_ids:
                Report._sale_sync_delivered(project_ids, days)
        return result
