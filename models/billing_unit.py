# -*- coding: utf-8 -*-
"""Facturation au jour ou à l'heure, affaire par affaire.

Une affaire au jour compte des journées (le fonctionnement d'origine) ; une
affaire à l'heure compte les heures pointées sur les journées travaillées :
ses lignes de prestation sont en heures, à un prix horaire, et les heures
validées des comptes rendus en font la quantité livrée. Une même mission peut
changer d'unité d'un volet à l'autre : chaque jour prend l'unité de l'affaire
de sa date.
"""
from odoo import _, api, fields, models

BILLING_UNITS = [('day', "Au jour"), ('hour', "À l'heure")]


class ResCompany(models.Model):
    _inherit = 'res.company'

    mission_billing_unit_default = fields.Selection(
        BILLING_UNITS, string="Facturation par défaut", default='day', required=True,
        help="Unité de facturation proposée pour les nouvelles affaires.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mission_billing_unit_default = fields.Selection(
        related='company_id.mission_billing_unit_default', readonly=False)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mission_billing_unit = fields.Selection(
        BILLING_UNITS, string="Facturation", required=True, tracking=True,
        default=lambda self: self.env.company.mission_billing_unit_default or 'day',
        help="Au jour : les journées validées des comptes rendus font la quantité livrée. "
             "À l'heure : les heures validées, sur des lignes en heures à un prix horaire.")
    mission_unit_warning = fields.Char(
        string="Avertissement sur l'unité", compute='_compute_mission_unit_warning')

    @api.depends('mission_billing_unit', 'order_line.product_uom_id', 'order_line.mission_day_line')
    def _compute_mission_unit_warning(self):
        hour = self.env.ref('uom.product_uom_hour', raise_if_not_found=False)
        for order in self:
            lines = order.order_line.filtered('mission_day_line')
            if order.mission_billing_unit == 'hour':
                wrong = lines.filtered(lambda l: l.product_uom_id != hour)
                text = _("Affaire facturée à l'heure : mettez ces lignes de prestation en heures, "
                         "à un prix horaire : %s.")
            else:
                wrong = lines.filtered(lambda l: hour and l.product_uom_id == hour)
                text = _("Affaire facturée au jour : ces lignes de prestation sont en heures : %s.")
            order.mission_unit_warning = text % ", ".join(wrong.mapped('name')) if wrong else False

    def mission_unit_label(self, plural=False):
        """« jour » ou « jours », « heure » ou « heures », selon l'unité de l'affaire."""
        hourly = self[:1].mission_billing_unit == 'hour'
        if plural:
            return _("heures") if hourly else _("jours")
        return _("heure") if hourly else _("jour")

    def mission_unit_phrase(self):
        """« par jour travaillé » ou « par heure travaillée », pour le devis."""
        if self[:1].mission_billing_unit == 'hour':
            return _("par heure travaillée")
        return _("par jour travaillé")
