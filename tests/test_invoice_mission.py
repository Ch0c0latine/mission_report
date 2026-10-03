# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from datetime import date

from odoo import Command

from .test_sale_delivery import TestSaleDelivery


class TestInvoiceMission(TestSaleDelivery):
    """Mois concerné, jetons des libellés, courriel d'envoi et pièces jointes."""

    def _invoice(self, invoice_date='2031-06-02'):
        self.report.action_submit()
        self.report.action_validate()
        self.order.order_line = [Command.create({
            'display_type': 'line_note', 'name': "Prestation du mois de /mois"})]
        invoice = self.order._create_invoices()
        invoice.invoice_date = invoice_date
        return invoice

    def test_month_is_the_previous_one_early_in_the_month(self):
        invoice = self._invoice('2031-06-02')
        self.assertEqual(invoice.mission_month, date(2031, 5, 1))
        invoice.invoice_date = '2031-05-30'
        self.assertEqual(invoice.mission_month, date(2031, 5, 1))
        invoice.delivery_date = '2031-04-30'
        self.assertEqual(invoice.mission_month, date(2031, 4, 1))

    def test_token_replaced_at_posting(self):
        invoice = self._invoice()
        note = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'line_note')
        self.assertIn('/mois', note.name, "the draft keeps the token")
        invoice.action_post()
        self.assertNotIn('/mois', note.name)
        self.assertTrue(note.name.startswith("Prestation du mois de "))

    def test_mail_helpers(self):
        invoice = self._invoice()
        self.assertEqual(invoice.mission_mail_days_text(),
                         ["9 jours sur 19 réalisés par Sale Employee."])
        self.assertEqual(invoice.mission_mail_partner_ids(), str(invoice.partner_id.id))
        recipient = self.env['res.partner'].create({'name': 'Comptabilité A', 'email': 'compta@a.example'})
        self.order.mission_invoice_partner_ids = recipient
        self.assertEqual(invoice.mission_mail_partner_ids(), str(recipient.id))

    def test_attachments_of_the_mail(self):
        invoice = self._invoice()
        names = [name for name, _content, _mime in invoice._mission_mail_files()]
        self.assertTrue(any(name.startswith('Commande_') for name in names))
        self.assertIn('CRA_Sale Employee_05-2031.pdf', names)

    def test_mission_template_is_the_default(self):
        invoice = self._invoice()
        template = self.env['account.move.send']._get_default_mail_template_id(invoice)
        self.assertEqual(template, self.env.ref('mission_report.mail_template_invoice_mission'))
