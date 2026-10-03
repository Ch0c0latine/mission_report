# -*- coding: utf-8 -*-
"""Factures des missions : mois concerné, courriel d'envoi et pièces jointes.

Le mois concerné se déduit des dates de la facture (une facture du début du
mois porte sur le mois précédent) et reste modifiable. À la validation, il
remplace « /mois » et « /mois_annee » dans les libellés de la facture, et sert au courriel
d'envoi : objet, jours réalisés par intervenant, et pièces jointes (commande,
CRA client, tableau des frais refacturés, justificatifs).
"""
import calendar
import logging
import re
from datetime import timedelta

from babel.dates import format_date as babel_format_date

from odoo import api, fields, models
from odoo.tools.misc import get_lang

_logger = logging.getLogger(__name__)

#: Jeton remplacé par le mois concerné dans les libellés (le plus long d'abord).
MONTH_TOKENS = ('/mois_annee', '/mois')


class AccountMove(models.Model):
    _inherit = 'account.move'

    mission_month = fields.Date(
        string="Mois concerné",
        compute='_compute_mission_month', store=True, readonly=False, copy=False,
        help="Premier jour du mois facturé. Par défaut : le mois de la date de livraison, "
             "sinon celui de la date de facture, ou le mois précédent si la facture est "
             "datée de la première quinzaine. Remplace « /mois » et « /mois_annee » dans "
             "les libellés et sert au courriel d'envoi.")

    @api.depends('invoice_date', 'delivery_date', 'date')
    def _compute_mission_month(self):
        for move in self:
            if move.delivery_date:
                day = move.delivery_date
            else:
                day = move.invoice_date or move.date or fields.Date.context_today(move)
                if day.day <= 15:
                    day = day.replace(day=1) - timedelta(days=1)
            move.mission_month = day.replace(day=1)

    # ------------------------------------------------------------------
    # Mois concerné
    # ------------------------------------------------------------------

    def mission_month_label(self, with_year=False):
        """« Septembre » ou « Septembre 2026 », dans la langue du client."""
        self.ensure_one()
        month = self.mission_month or fields.Date.context_today(self).replace(day=1)
        lang = get_lang(self.env, self.partner_id.lang).code
        text = babel_format_date(month, 'MMMM yyyy' if with_year else 'MMMM', locale=lang)
        return text[:1].upper() + text[1:]

    def _mission_fill_month(self):
        """Remplace les jetons du mois dans les libellés des lignes."""
        for move in self.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund')):
            values = {'/mois_annee': move.mission_month_label(with_year=True),
                      '/mois': move.mission_month_label()}
            for line in move.invoice_line_ids:
                name = line.name or ''
                if '/mois' not in name:
                    continue
                for token in MONTH_TOKENS:
                    name = name.replace(token, values[token])
                line.name = name

    def _post(self, soft=True):
        self._mission_fill_month()
        return super()._post(soft=soft)

    # ------------------------------------------------------------------
    # Courriel d'envoi
    # ------------------------------------------------------------------

    def _mission_orders(self):
        return self.invoice_line_ids.sale_line_ids.order_id

    def _mission_projects(self):
        orders = self._mission_orders()
        if not orders:
            return self.env['project.project']
        projects = self.env['project.project'].sudo().search([
            '|', ('sale_order_id', 'in', orders.ids), ('reinvoiced_sale_order_id', 'in', orders.ids)])
        # Le projet de l'affaire elle-même aussi : une mission peut n'y être rattachée que par lui.
        return projects | orders.order_line.project_id.sudo() | orders.sudo().project_id

    def mission_mail_object(self, short=False):
        """Objet de la commande (« Prestation d'assistance technique... »).

        ``short`` ôte « Prestation de » au début, pour la phrase du courriel.
        """
        self.ensure_one()
        order = self._mission_orders()[:1]
        text = (self['x_objet_commande'] if 'x_objet_commande' in self._fields else '') or \
            (order['x_objet_commande'] if order and 'x_objet_commande' in order._fields else '') or \
            order.client_order_ref or order.name or self.ref or ''
        if short:
            text = re.sub(r"^\s*prestation\s+(de\s+|d')?", '', text, flags=re.IGNORECASE)
        return text

    def _mission_reports(self):
        """Rapports d'activité du mois concerné qui portent sur les missions de la facture."""
        self.ensure_one()
        projects = self._mission_projects()
        if not projects or not self.mission_month:
            return self.env['mission.activity.report'], projects
        reports = self.env['mission.activity.report'].sudo().search([
            ('date_from', '=', self.mission_month)])
        reports = reports.filtered(lambda r: any(
            line.get('project_id') in projects.ids for line in r._get_report_data().get('missions', [])))
        return reports, projects

    def mission_mail_days(self, unit='day'):
        """[(jours réalisés, jours ouvrés, intervenant)] du mois concerné.

        ``unit`` 'hour' : [(heures réalisées, heures ouvrées, intervenant)] des missions
        facturées à l'heure. Seuls les intervenants qui ont des lignes de cette unité.
        """
        self.ensure_one()
        reports, projects = self._mission_reports()
        result = []
        for report in reports:
            data = report._get_report_data()
            lines = [line for line in data.get('missions', [])
                     if line.get('project_id') in projects.ids and line.get('unit', 'day') == unit]
            if not lines:
                continue
            done = sum(line.get('total') or 0.0 for line in lines)
            potential = data.get('potential_hours') if unit == 'hour' else data.get('potential_days')
            result.append((done, potential or 0.0, report.employee_id.name))
        return result

    def mission_mail_days_text(self):
        """« 22 jours sur 22 réalisés par Camille Exemple. », une ligne par intervenant ;
        « 63 heures sur 154 réalisées par … » pour une mission facturée à l'heure."""
        lines = []
        for done, potential, name in self.mission_mail_days():
            lines.append("%s jours sur %s réalisés par %s." % (
                self._mission_format_days(done), self._mission_format_days(potential), name))
        for done, potential, name in self.mission_mail_days(unit='hour'):
            lines.append("%s heures sur %s réalisées par %s." % (
                self._mission_format_days(done), self._mission_format_days(potential), name))
        return lines

    @api.model
    def _mission_format_days(self, value):
        return ('%g' % value).replace('.', ',')

    def mission_mail_partner_ids(self):
        """Destinataires : ceux de l'affaire, sinon le client de la facture."""
        self.ensure_one()
        partners = self._mission_orders().mission_invoice_partner_ids
        return ",".join(str(i) for i in (partners or self.partner_id).ids)

    def _mission_mail_files(self):
        """[(nom, contenu, type MIME)] des pièces jointes du courriel d'envoi."""
        self.ensure_one()
        files = []
        orders = self._mission_orders()
        month = self.mission_month
        period = month.strftime('%m-%Y') if month else ''

        # Commande : les PDF déposés sur l'affaire (bon de commande du client),
        # sinon le devis tel qu'Odoo l'imprime.
        for order in orders:
            uploaded = self.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'sale.order'), ('res_id', '=', order.id),
                ('mimetype', '=', 'application/pdf')], order='id desc')
            if uploaded:
                files += [(a.name, a.raw, 'application/pdf') for a in uploaded]
            else:
                pdf, _kind = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
                    'sale.action_report_saleorder', res_ids=order.ids)
                files.append(("Commande_%s.pdf" % order.name.replace('/', '-'), pdf, 'application/pdf'))

        # CRA client : la page du client de la facture, pour chaque intervenant.
        reports, projects = self._mission_reports()
        partner_ids = list(set(projects.partner_id.ids))
        for report in reports:
            pdf, _kind = self.env['ir.actions.report'].sudo().with_context(
                mission_report_partner_ids=partner_ids)._render_qweb_pdf(
                'mission_report.action_report_activity_client', res_ids=report.ids)
            files.append(("CRA_%s_%s.pdf" % (report.employee_id.name, period), pdf, 'application/pdf'))

        # Frais refacturés portés par la facture (à défaut, ceux du mois sur ses missions) : le tableau
        # Excel et les justificatifs, quand le module expense_scan est installé.
        if hasattr(self, 'expense_scan_sheet_files'):
            Expense = self.env['hr.expense'].sudo()
            expenses = Expense.search([('expense_scan_invoice_id', '=', self.id)])
            if not expenses and month and projects:
                last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
                expenses = Expense.search([
                    ('project_id', 'in', projects.ids), ('reinvoice_mode', '=', 'project'),
                    ('approval_state', '=', 'approved'), ('date', '>=', month), ('date', '<=', last)])
            files += self.expense_scan_sheet_files(expenses, projects)
        return files

    def _mission_mail_attachments(self):
        """Les pièces jointes, enregistrées sur la facture (une seule fois par envoi préparé)."""
        self.ensure_one()
        Attachment = self.env['ir.attachment'].sudo()
        attachments = Attachment
        for name, content, mimetype in self._mission_mail_files():
            attachments |= Attachment.create({
                'name': name,
                'raw': content,
                'mimetype': mimetype,
                'res_model': 'mail.compose.message',
                'res_id': 0,
            })
        return attachments


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    @api.model
    def _get_default_mail_attachments_widget(self, move, mail_template, invoice_edi_format=None,
                                             extra_edis=None, pdf_report=None):
        result = super()._get_default_mail_attachments_widget(
            move, mail_template, invoice_edi_format=invoice_edi_format, extra_edis=extra_edis,
            pdf_report=pdf_report)
        ours = self.env.ref('mission_report.mail_template_invoice_mission', raise_if_not_found=False)
        if ours and mail_template == ours and move._mission_orders():
            try:
                attachments = move._mission_mail_attachments()
            except Exception:  # noqa: BLE001 - the invoice is sent without them
                _logger.warning("Could not prepare the attachments of %s", move.name, exc_info=True)
                attachments = self.env['ir.attachment']
            result += [{
                'id': attachment.id,
                'name': attachment.name,
                'mimetype': attachment.mimetype,
                'placeholder': False,
            } for attachment in attachments]
        return result

    @api.model
    def _get_default_mail_template_id(self, move):
        ours = self.env.ref('mission_report.mail_template_invoice_mission', raise_if_not_found=False)
        if ours and move.move_type == 'out_invoice' and move._mission_orders():
            return ours
        return super()._get_default_mail_template_id(move)
