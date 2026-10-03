# -*- coding: utf-8 -*-
"""Validated activity reports feed the sales order lines of their missions.

The days of a validated monthly report, per mission, are added up and set as
the delivered quantity of the order line the project belongs to. Nothing is
typed by hand: the next invoice takes the days delivered since the last one.
A report sent back to draft takes its days back.
"""
import logging

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
        """Lignes de journées de la mission, toutes affaires confondues."""
        lines = project.sale_line_id
        Line = self.env['sale.order.line'].sudo()
        if 'project_id' in Line._fields:
            lines |= Line.search([('project_id', '=', project.id)])
        for order in project.sudo()._mission_all_orders():
            lines |= order.order_line
        return lines.filtered(
            lambda l: not l.display_type and l.is_service and not l.product_id.can_be_expensed
            and l.qty_delivered_method == 'manual' and l.state == 'sale')

    @api.model
    def _sale_sync_delivered(self, project_ids=None):
        """Set the delivered days of the missions' order lines.

        Without ``project_ids``, every mission with a validated report. A day
        goes to the order of the mission whose period contains it; every day
        line of an order takes that order's total.
        """
        days = self._sale_validated_days()
        ids = set(project_ids) if project_ids is not None else set(days)
        for project in self.env['project.project'].sudo().browse(sorted(ids)).exists():
            totals = {}
            for day, value in days.get(project.id, []):
                order = project._mission_order_on(day)
                if order:
                    totals[order.id] = totals.get(order.id, 0.0) + value
            for line in self._sale_lines_of(project):
                share = totals.get(line.order_id.id, 0.0)
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
