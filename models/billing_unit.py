# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Facturation au jour ou à l'heure, affaire par affaire.

Une affaire au jour compte des journées (le fonctionnement d'origine) ; une
affaire à l'heure compte les heures pointées sur les journées travaillées :
ses lignes de prestation sont en heures, à un prix horaire, et les heures
validées des comptes rendus en font la quantité livrée. Une même mission peut
changer d'unité d'un volet à l'autre : chaque jour prend l'unité de l'affaire
de sa date.
"""
from odoo import _, api, fields, models

BILLING_UNITS = [('day', "Per day"), ('hour', "Per hour")]


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_billing_unit_default = fields.Selection(
        BILLING_UNITS, string="Default billing", default='day', required=True,
        help="Billing unit proposed for new orders.")
    mission_hours_outside_schedule = fields.Boolean(
        string="Count hours outside working hours",
        help="An entry in hours counts the hours entered, even outside the working schedule "
             "of the employee (from 7 am to 8 pm for a 9 am to 5 pm schedule). Otherwise only "
             "the hours within the schedule count.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_billing_unit_default = fields.Selection(
        related='company_id.mission_billing_unit_default', readonly=False)
    mission_hours_outside_schedule = fields.Boolean(
        related='company_id.mission_hours_outside_schedule', readonly=False)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_billing_unit = fields.Selection(
        BILLING_UNITS, string="Billing", required=True, tracking=True,
        default=lambda self: self.env.company.mission_billing_unit_default or 'day',
        help="Per day: the validated days of the reports make the delivered quantity. Per "
             "hour: the validated hours, on lines in hours at an hourly price.")
    mission_unit_warning = fields.Char(
        string="Unit warning", compute='_compute_mission_unit_warning')

    @api.depends('mission_billing_unit', 'order_line.product_uom_id', 'order_line.mission_day_line')
    def _compute_mission_unit_warning(self):
        hour = self.env.ref('uom.product_uom_hour', raise_if_not_found=False)
        for order in self:
            lines = order.order_line.filtered('mission_day_line')
            if order.mission_billing_unit == 'hour':
                wrong = lines.filtered(lambda l: l.product_uom_id != hour)
                text = _("Order billed per hour: put these service lines in hours, at an hourly price: %s.")
            else:
                wrong = lines.filtered(lambda l: hour and l.product_uom_id == hour)
                text = _("Order billed per day: these service lines are in hours: %s.")
            order.mission_unit_warning = text % ", ".join(wrong.mapped('name')) if wrong else False

    def mission_unit_label(self, plural=False):
        """« jour » ou « jours », « heure » ou « heures », selon l'unité de l'affaire."""
        hourly = self[:1].mission_billing_unit == 'hour'
        if plural:
            return _("hours") if hourly else _("days")
        return _("hour") if hourly else _("day")

    def mission_unit_phrase(self):
        """« par jour travaillé » ou « par heure travaillée », pour le devis."""
        if self[:1].mission_billing_unit == 'hour':
            return _("per hour worked")
        return _("per day worked")
