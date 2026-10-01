# -*- coding: utf-8 -*-
"""Validated activity reports feed the sales order lines of their missions.

The days of a validated monthly report, per mission, are added up and set as
the delivered quantity of the order line the project belongs to. Nothing is
typed by hand: the next invoice takes the days delivered since the last one.
A report sent back to draft takes its days back.
"""
import logging

from odoo import api, models
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
        """{project id: days} over all the validated reports."""
        days = {}
        for report in self.sudo().search([('state', '=', 'validated')]):
            for line in (report.snapshot or {}).get('missions', []):
                project_id = line.get('project_id')
                if project_id:
                    days[project_id] = days.get(project_id, 0.0) + (line.get('total') or 0.0)
        return days

    @api.model
    def _sale_lines_of(self, project):
        """Order lines billed on the days of a mission."""
        lines = project.sale_line_id
        if 'project_id' in self.env['sale.order.line']._fields:
            lines |= self.env['sale.order.line'].sudo().search([
                ('project_id', '=', project.id),
                ('state', '=', 'sale'),
                ('is_service', '=', True),
            ]).filtered(lambda line: not line.product_id.can_be_expensed)
        return lines.filtered(lambda line: line.qty_delivered_method == 'manual' and not line.display_type)

    @api.model
    def _sale_sync_delivered(self, project_ids=None):
        """Set the delivered days of the missions' order lines.

        Without ``project_ids``, every mission with a validated report.
        """
        days = self._sale_validated_days()
        ids = set(project_ids) if project_ids is not None else set(days)
        for project in self.env['project.project'].sudo().browse(sorted(ids)).exists():
            total = days.get(project.id, 0.0)
            for line in self._sale_lines_of(project):
                if float_compare(line.qty_delivered, total, precision_digits=2):
                    try:
                        with self.env.cr.savepoint():
                            line.write({'qty_delivered': total})
                    except Exception:  # noqa: BLE001 - never block a validation
                        _logger.warning("Could not set the delivered days of %s", line.display_name,
                                        exc_info=True)

    @api.model
    def _cron_sale_sync_delivered(self):
        """Safety net: every mission with a validated report."""
        self._sale_sync_delivered()
