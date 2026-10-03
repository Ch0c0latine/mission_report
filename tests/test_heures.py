# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Facturation à l'heure : saisie en heures, compte rendu, quantités livrées, volets, courriel."""
import io
from datetime import date

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase

from ..models.activity_report import INTERNAL, INTERNAL_KEY
from .test_independence import _migration

# Mai 2031 : 1er, 8 et 22 (Ascension) fériés, 19 jours ouvrés de 8 heures (calendrier de 40 heures).
YEAR = 2031


class TestHeures(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.user = cls.env['res.users'].create({
            'name': 'Employé Heures', 'login': 'heures_employee_mission_report@example.com',
            'email': 'heures_employee_mission_report@example.com'})
        manager = cls.env['res.users'].create({
            'name': 'Responsable Heures', 'login': 'heures_manager_mission_report@example.com',
            'email': 'heures_manager_mission_report@example.com'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Employé Heures', 'company_id': cls.company.id,
            'user_id': cls.user.id, 'leave_manager_id': manager.id})
        cls.client_h = cls.env['res.partner'].create({'name': 'Client Heures'})
        cls.client_d = cls.env['res.partner'].create({'name': 'Client Jours'})
        cls.project_h = cls._project('Mission H', cls.client_h)
        cls.project_h2 = cls._project('Mission H2', cls.client_h)
        cls.project_d = cls._project('Mission D', cls.client_d)
        cls.env['mission.public.holiday.wizard'].create({'year': YEAR, 'company_id': cls.company.id})._generate()
        cls.hour = cls.env.ref('uom.product_uom_hour')
        cls.service = cls.env['product.product'].create({
            'name': 'Assistance', 'type': 'service', 'list_price': 600.0, 'invoice_policy': 'delivery'})
        cls.order_h = cls._order(cls.project_h, 'hour', [(150.0, 80.0, cls.hour)])
        cls.order_h2 = cls._order(cls.project_h2, 'hour', [(50.0, 90.0, cls.hour)])
        cls.order_d = cls._order(cls.project_d, 'day', [(40.0, 600.0, None)])

    @classmethod
    def _project(cls, name, partner):
        project = cls.env['project.project'].create({'name': name, 'partner_id': partner.id})
        cls.env['project.task'].create({'name': 'Tâche', 'project_id': project.id, 'user_ids': [(6, 0, cls.user.ids)]})
        return project

    @classmethod
    def _order(cls, project, unit, lines, confirm=True, **vals):
        """Une affaire de la mission : ``lines`` = [(quantité, prix, unité de mesure)]."""
        order = cls.env['sale.order'].create({
            'partner_id': project.partner_id.id, 'mission_billing_unit': unit,
            'order_line': [Command.create(dict({
                'product_id': cls.service.id, 'product_uom_qty': quantity, 'price_unit': price,
            }, **({'product_uom_id': uom.id} if uom else {}))) for quantity, price, uom in lines],
            **vals,
        })
        if confirm:
            order.action_confirm()
        order.project_id = project
        return order

    def _entry(self, project, date_from, date_to=None, env=None, **vals):
        return (env or self.env)['hr.leave'].create(dict({
            'employee_id': self.employee.id, 'project_id': project.id,
            'request_date_from': date_from, 'request_date_to': date_to or date_from}, **vals))

    def _report(self, month):
        return self.env['mission.activity.report'].create({'employee_id': self.employee.id, 'date_from': month})

    def _validate(self, report):
        report.action_submit()
        report.action_validate()

    def _index(self, day):
        return int(day[-2:]) - 1

    # -- Saisie -----------------------------------------------------------------

    def test_journee_entiere_en_heures(self):
        entry = self._entry(self.project_h, '2031-05-05')
        self.assertTrue(entry.mission_hourly)
        self.assertEqual(entry.mission_duration, 'day')
        self.assertFalse(entry.request_unit_hours)
        self.assertEqual(entry.number_of_hours, 8.0)
        self.assertEqual(entry.duration_display, "8:00 heures")
        self.assertEqual(entry._mission_hours_by_day(), {date(2031, 5, 5): 8.0})
        # Plusieurs jours : les heures de chacun, jour férié exclu.
        week = self._entry(self.project_h, '2031-05-12', '2031-05-14')
        self.assertEqual(week.number_of_hours, 24.0)
        self.assertEqual(sum(week._mission_hours_by_day().values()), 24.0)

    def test_demi_journee_compte_la_moitie(self):
        entry = self._entry(self.project_h, '2031-05-05', mission_duration='half',
                            request_date_from_period='am', request_date_to_period='am')
        self.assertTrue(entry.request_unit_half)
        self.assertEqual(entry.number_of_hours, 4.0)
        self.assertEqual(entry._mission_hours_by_day(), {date(2031, 5, 5): 4.0})
        # La moitié des heures du jour, même quand le matin et l'après-midi ne sont pas égaux.
        calendar = self.env['resource.calendar'].create({
            'name': 'Sept heures', 'tz': self.employee.tz or 'UTC', 'attendance_ids': [
                Command.create({'name': 'Matin %s' % day, 'dayofweek': str(day), 'hour_from': 8.0,
                                'hour_to': 12.0, 'day_period': 'morning'}) for day in range(5)] + [
                Command.create({'name': 'Après-midi %s' % day, 'dayofweek': str(day), 'hour_from': 13.0,
                                'hour_to': 16.0, 'day_period': 'afternoon'}) for day in range(5)]})
        self.employee.resource_calendar_id = calendar
        afternoon = self._entry(self.project_h, '2031-05-06', mission_duration='half',
                                request_date_from_period='pm', request_date_to_period='pm')
        self.assertEqual(afternoon.number_of_hours, 3.5)
        self.assertEqual(afternoon._mission_hours_by_day(), {date(2031, 5, 6): 3.5})

    def test_heures_personnalisees(self):
        entry = self._entry(self.project_h, '2031-05-05', mission_duration='hours',
                            request_hour_from=9.0, request_hour_to=11.5)
        self.assertTrue(entry.request_unit_hours)
        self.assertEqual(entry.number_of_hours, 2.5)
        self.assertEqual(entry.duration_display, "2:30 heures")
        self.assertEqual(entry._mission_hours_by_day(), {date(2031, 5, 5): 2.5})

    def test_deux_missions_le_meme_jour(self):
        self._entry(self.project_h, '2031-05-05', mission_duration='hours', request_hour_from=8.0, request_hour_to=12.0)
        self._entry(self.project_h2, '2031-05-05', mission_duration='hours', request_hour_from=13.0, request_hour_to=17.0)
        # Des plages qui se chevauchent sont refusées, comme pour toute saisie.
        with self.assertRaises(ValidationError):
            self._entry(self.project_h2, '2031-05-05', mission_duration='hours',
                        request_hour_from=11.0, request_hour_to=14.0)
        lines = self._report('2031-05-01')._get_report_data()['missions']
        self.assertEqual([(line['project'], line['unit'], line['total']) for line in lines],
                         [('Mission H', 'hour', 4.0), ('Mission H2', 'hour', 4.0)])

    def test_formulaire_de_saisie(self):
        """Le formulaire d'une mission à l'heure propose la durée en heures ; une mission au jour, non."""
        form = Form(self.env['hr.leave'].with_user(self.user).with_context(
            default_employee_id=self.employee.id, default_request_date_from='2031-05-05',
            default_request_date_to='2031-05-05'), view='hr_holidays.hr_leave_view_form')
        form.project_id = self.project_h
        self.assertTrue(form.mission_hourly)
        self.assertEqual(form.duration_display, "8:00 heures")
        form.mission_duration = 'hours'
        self.assertTrue(form.request_unit_hours)
        form.request_hour_from = 14.0
        form.request_hour_to = 16.0
        self.assertEqual(form.duration_display, "2:00 heures")
        entry = form.save()
        self.assertEqual((entry.mission_duration, entry.number_of_hours), ('hours', 2.0))
        form = Form(self.env['hr.leave'].with_context(
            default_employee_id=self.employee.id, default_request_date_from='2031-05-06',
            default_request_date_to='2031-05-06'), view='hr_holidays.hr_leave_view_form')
        form.project_id = self.project_h
        form.mission_duration = 'half'
        form.project_id = self.project_d
        self.assertFalse(form.mission_hourly)
        self.assertEqual(form.mission_duration, 'day')
        self.assertEqual(form.duration_display, "1 jours")

    def test_une_mission_au_jour_se_saisit_en_journees(self):
        with self.assertRaises(ValidationError):
            self._entry(self.project_d, '2031-05-05', mission_duration='half',
                        request_date_from_period='am', request_date_to_period='am')
        # Un créneau du calendrier en vue semaine, sur une mission au jour : une journée entière.
        entry = self._entry(self.project_d, '2031-05-06', request_unit_hours=True,
                            request_hour_from=9.0, request_hour_to=10.0)
        self.assertEqual((entry.mission_duration, entry.request_unit_hours), ('day', False))
        self.assertEqual(entry.number_of_days, 1.0)
        self.assertEqual(entry.duration_display, "1 jours")
        # Le même créneau sur une mission à l'heure : des heures.
        slot = self._entry(self.project_h, '2031-05-07', request_unit_hours=True,
                           request_hour_from=9.0, request_hour_to=10.0)
        self.assertEqual((slot.mission_duration, slot.number_of_hours), ('hours', 1.0))

    def test_un_salarie_sans_droit_rh_pointe_en_heures(self):
        self.assertFalse(self.user.has_group('hr_holidays.group_hr_holidays_user'))
        self.assertFalse(self.user.has_group('sales_team.group_sale_salesman'))
        env = self.env(user=self.user)
        defaults = env['hr.leave'].with_context(default_project_id=self.project_h.id).default_get(
            ['mission_duration', 'project_id'])
        self.assertEqual(defaults['mission_duration'], 'day')
        entry = self._entry(self.project_h, '2031-05-20', env=env, mission_duration='hours',
                            request_hour_from=9.0, request_hour_to=12.0)
        self.assertTrue(entry.mission_hourly)
        self.assertEqual(entry.number_of_hours, 3.0)
        report = env['mission.activity.report'].create({'employee_id': self.employee.id, 'date_from': '2031-05-01'})
        self.assertEqual(report.mission_hours, 3.0)
        with self.assertRaises(ValidationError):
            self._entry(self.project_d, '2031-05-21', env=env, mission_duration='hours',
                        request_hour_from=9.0, request_hour_to=12.0)

    # -- Compte rendu -------------------------------------------------------------

    def test_compte_rendu_unite_par_ligne_et_totaux_separes(self):
        self._entry(self.project_h, '2031-05-05', '2031-05-07')
        self._entry(self.project_h, '2031-05-09', mission_duration='hours', request_hour_from=9.0, request_hour_to=11.5)
        self._entry(self.project_d, '2031-05-12', '2031-05-13')
        report = self._report('2031-05-01')
        data = report._get_report_data()
        self.assertEqual([(line['project'], line['unit'], line['total']) for line in data['missions']],
                         [('Mission H', 'hour', 26.5), ('Mission D', 'day', 2.0)])
        self.assertEqual(data['potential_days'], 19.0)
        self.assertEqual(data['potential_hours'], 152.0)
        self.assertEqual(data['mission_total'], 2.0, "days only")
        self.assertEqual(data['mission_hours_total'], 26.5)
        self.assertEqual(data['missions'][0]['values'][self._index('2031-05-05')], 8.0)
        self.assertEqual(data['missions'][0]['values'][self._index('2031-05-09')], 2.5)
        self.assertEqual(data['mission_hour_totals'][self._index('2031-05-09')], 2.5)
        self.assertEqual(data['mission_totals'][self._index('2031-05-12')], 1.0)
        self.assertEqual(data['mission_totals'][self._index('2031-05-05')], 0.0, "no hours among the days")
        self.assertEqual(data['totals'][self._index('2031-05-05')], 0.0)
        self.assertIsNone(data['mission_hour_totals'][self._index('2031-05-08')], "public holiday")
        self.assertEqual((report.mission_days, report.mission_hours, report.potential_hours), (2.0, 26.5, 152.0))
        # Une IGD : un jour de présence est un jour qui porte une durée, en heures comme en jours.
        self.assertEqual(len(report._igd_presence_days(data, self.project_h)), 4)

    def test_une_mission_qui_change_d_unite_dans_le_mois(self):
        project = self._project('Mission S', self.client_d)
        first = self._order(project, 'day', [(10.0, 600.0, None)])
        first.write({'mission_date_start': '2031-06-01', 'mission_date_end': '2031-06-15'})
        second = self._order(project, 'hour', [(80.0, 75.0, self.hour)],
                             mission_date_start='2031-06-16', mission_date_end='2031-07-31')
        self._entry(project, '2031-06-11', '2031-06-18')
        june = self._report('2031-06-01')
        lines = june._get_report_data()['missions']
        self.assertEqual([(line['unit'], line['total']) for line in lines], [('day', 3.0), ('hour', 24.0)])
        self._validate(june)
        self.assertEqual(first.order_line.qty_delivered, 3.0)
        self.assertEqual(second.order_line.qty_delivered, 24.0)

    def test_un_compte_rendu_valide_avant_les_heures_se_lit_en_jours(self):
        self._entry(self.project_d, '2031-05-12', '2031-05-13')
        report = self._report('2031-05-01')
        self._validate(report)
        old = dict(report.snapshot)
        for key in ('mission_hours_total', 'mission_hour_totals', 'potential_hours'):
            old.pop(key)
        old['missions'] = [{k: v for k, v in line.items() if k != 'unit'} for line in old['missions']]
        report.with_context(**{INTERNAL_KEY: INTERNAL}).write({'snapshot': old})
        data = report._get_report_data()
        self.assertEqual([line['unit'] for line in data['missions']], ['day'])
        self.assertEqual((data['mission_total'], data['mission_hours_total']), (2.0, 0.0))
        self.assertIsNone(data['potential_hours'])
        self.assertNotIn('unit', report.snapshot['missions'][0], "the snapshot itself is left as it is")
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'mission_report.action_report_activity_internal', report.ids)
        self.assertNotIn('Heures ouvrées'.encode(), html)
        # Ses jours restent livrés en jours.
        self.env['mission.activity.report']._sale_sync_delivered()
        self.assertEqual(self.order_d.order_line.qty_delivered, 2.0)

    def test_pdf_et_excel(self):
        import openpyxl
        self._entry(self.project_h, '2031-05-05')
        self._entry(self.project_d, '2031-05-12')
        report = self._report('2031-05-01')
        Report = self.env['ir.actions.report']
        html, _kind = Report._render_qweb_html('mission_report.action_report_activity_internal', report.ids)
        for text in ('Heures ouvrées', 'Unité', '<td>heures</td>', '<td>jours</td>', '<span>152</span>'):
            self.assertIn(text.encode(), html)
        # Rapport client : la page du client à l'heure dit les heures, celle du client au jour reste comme avant.
        html, _kind = Report._render_qweb_html('mission_report.action_report_activity_client', report.ids)
        self.assertEqual(html.count('Heures ouvrées'.encode()), 1)
        self.assertIn(b'<td>heures</td>', html)
        self.assertNotIn(b'<td>jours</td>', html)
        template = self.env.ref('mission_report.activity_report_template_internal')
        template.action_generate_file()
        sheet = openpyxl.load_workbook(io.BytesIO(template._export(report))).worksheets[0]
        # Jours : la mission au jour, puis la ligne de congés vide ; leur total ne prend pas les heures.
        self.assertEqual(sheet['B10'].value, 'Mission D')
        self.assertEqual(sheet['A13'].value, 'Total (jours)')
        self.assertEqual(sheet['D13'].value, '=SUM(D10:D10)+SUM(D12:D12)')
        # Heures : sous le total des jours, avec leur propre total.
        self.assertIn('152', sheet['A14'].value)
        self.assertEqual(sheet['B15'].value, 'Mission H')
        self.assertEqual(sheet['H15'].value, 8.0)
        self.assertEqual(sheet['A16'].value, 'Total (heures)')
        self.assertEqual(sheet['H16'].value, '=SUM(H15:H15)')
        self.assertEqual(sheet['C16'].value, '=SUM(C15:C15)')
        cells = {cell.value: cell for cell in template.cell_ids}
        self.assertTrue(cells)
        self.assertEqual(template._line_value(report._get_report_data()['missions'][0], 'unit'), 'heures')
        self.assertEqual(template._header_value(report, report._get_render_data(), 'potential_hours'), 152.0)

    # -- Quantités livrées --------------------------------------------------------

    def test_heures_livrees_sur_les_lignes_mensuelles(self):
        project = self._project('Mission M', self.client_h)
        order = self.env['sale.order'].create({
            'partner_id': self.client_h.id, 'mission_billing_unit': 'hour',
            'order_line': [Command.create({
                'product_id': self.service.id, 'product_uom_id': self.hour.id, 'product_uom_qty': 100.0,
                'price_unit': 80.0, 'mission_period_start': first, 'mission_period_end': last,
            }) for first, last in (('2031-05-01', '2031-05-31'), ('2031-06-01', '2031-06-30'))]})
        order.action_confirm()
        order.project_id = project
        self._entry(project, '2031-05-12', '2031-05-13')
        self._entry(project, '2031-06-03', mission_duration='hours', request_hour_from=9.0, request_hour_to=12.0)
        self._validate(self._report('2031-05-01'))
        self._validate(self._report('2031-06-01'))
        self.assertEqual(order.order_line.mapped('qty_delivered'), [16.0, 3.0])

    def test_heures_livrees_au_prorata(self):
        self.order_h.order_line = [Command.create({
            'product_id': self.service.id, 'product_uom_id': self.hour.id, 'product_uom_qty': 50.0,
            'price_unit': 80.0})]
        self._entry(self.project_h, '2031-05-05', '2031-05-07')
        report = self._report('2031-05-01')
        self._validate(report)
        self.assertEqual(self.order_h.order_line.mapped('qty_delivered'), [18.0, 6.0])
        report.action_reset_to_draft()
        self.assertEqual(self.order_h.order_line.mapped('qty_delivered'), [0.0, 0.0])

    # -- Volets -------------------------------------------------------------------

    def _wizard(self, order, start, end, **vals):
        wizard = self.env['mission.volet.wizard'].with_context(default_order_id=order.id).create({})
        wizard.write(dict({'date_start': start, 'date_end': end}, **vals))
        return wizard

    def test_nouveau_volet_en_heures(self):
        self.order_h.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-05-31'})
        wizard = self._wizard(self.order_h, '2031-06-01', '2031-06-30')
        self.assertEqual(wizard.mission_billing_unit, 'hour')
        self.assertFalse(wizard.unit_warning)
        # Juin 2031 : 21 jours de semaine, le lundi de Pentecôte (2 juin) chômé, 20 jours de 8 heures.
        self.assertEqual(wizard.days, 160.0)
        self.assertIn("Heures", wizard.plan)
        new = self.env['sale.order'].browse(wizard.action_create()['res_id'])
        line = new._volet_day_lines()
        self.assertEqual(new.mission_billing_unit, 'hour')
        self.assertEqual((line.product_uom_qty, line.product_uom_id, line.price_unit), (160.0, self.hour, 80.0))
        self.assertFalse(new.mission_unit_warning)
        self.assertEqual(line.mission_quantity_label(), "160 heures")

    def test_une_mission_passe_du_jour_a_l_heure_entre_deux_volets(self):
        self.order_d.write({'mission_date_start': '2031-05-01', 'mission_date_end': '2031-05-31'})
        wizard = self._wizard(self.order_d, '2031-06-01', '2031-06-30', mission_billing_unit='hour')
        self.assertTrue(wizard.unit_warning)
        new = self.env['sale.order'].browse(wizard.action_create()['res_id'])
        line = new._volet_day_lines()
        self.assertEqual(new.mission_billing_unit, 'hour')
        # L'unité et le prix de l'affaire d'origine : à revoir, l'affaire le signale sans bloquer.
        self.assertEqual((line.product_uom_qty, line.price_unit), (160.0, 600.0))
        self.assertTrue(new.mission_unit_warning)
        line.write({'product_uom_id': self.hour.id, 'price_unit': 75.0})
        self.assertFalse(new.mission_unit_warning)
        new.action_confirm()
        self._entry(self.project_d, '2031-05-12', '2031-05-13')
        self._entry(self.project_d, '2031-06-03')
        self._validate(self._report('2031-05-01'))
        june = self._report('2031-06-01')
        self.assertEqual([line['unit'] for line in june._get_report_data()['missions']], ['hour'])
        self._validate(june)
        self.assertEqual(self.order_d.order_line.qty_delivered, 2.0)
        self.assertEqual(line.qty_delivered, 8.0)

    # -- Documents ----------------------------------------------------------------

    def test_libelles_du_devis(self):
        line_h, line_d = self.order_h.order_line, self.order_d.order_line
        self.assertEqual(line_h.mission_quantity_label(), "150 heures")
        self.assertEqual(line_d.mission_quantity_label(), "40 jours")
        line_h.product_uom_qty = 1.0
        self.assertEqual(line_h.mission_quantity_label(), "1 heure")
        self.assertEqual((self.order_h.mission_unit_label(), self.order_h.mission_unit_label(plural=True)),
                         ("heure", "heures"))
        self.assertEqual((self.order_d.mission_unit_label(), self.order_d.mission_unit_label(plural=True)),
                         ("jour", "jours"))
        self.assertEqual(self.order_h.mission_unit_phrase(), "par heure travaillée")
        self.assertEqual(self.order_d.mission_unit_phrase(), "par jour travaillé")

    def test_avertissement_sur_l_unite_des_lignes(self):
        self.assertFalse(self.order_h.mission_unit_warning)
        self.assertFalse(self.order_d.mission_unit_warning)
        self.order_d.mission_billing_unit = 'hour'
        self.assertIn('Assistance', self.order_d.mission_unit_warning)
        self.order_h.mission_billing_unit = 'day'
        self.assertTrue(self.order_h.mission_unit_warning)

    def test_facturation_par_defaut_de_la_societe(self):
        self.assertEqual(self.env['sale.order'].new({}).mission_billing_unit, 'day')
        settings = self.env['res.config.settings'].create({'mission_billing_unit_default': 'hour'})
        settings.execute()
        self.assertEqual(self.company.mission_billing_unit_default, 'hour')
        order = self.env['sale.order'].create({'partner_id': self.client_h.id})
        self.assertEqual(order.mission_billing_unit, 'hour')

    def test_courriel_de_facture_en_heures(self):
        self._entry(self.project_h, '2031-05-05', '2031-05-07')
        self._entry(self.project_h, '2031-05-09', mission_duration='hours', request_hour_from=9.0, request_hour_to=11.5)
        self._validate(self._report('2031-05-01'))
        invoice = self.order_h._create_invoices()
        invoice.invoice_date = '2031-06-02'
        self.assertEqual(invoice.mission_mail_days_text(),
                         ["26,5 heures sur 152 réalisées par Employé Heures."])
        self.assertEqual(invoice.mission_mail_days(), [], "no day line on this mission")

    # -- Migration ----------------------------------------------------------------

    def test_migration_affaires_au_jour(self):
        self.env.flush_all()
        # Comme avant la mise à jour : des colonnes vides.
        self.env.cr.execute("ALTER TABLE sale_order ALTER COLUMN mission_billing_unit DROP NOT NULL")
        self.env.cr.execute("ALTER TABLE res_company ALTER COLUMN mission_billing_unit_default DROP NOT NULL")
        self.env.cr.execute("UPDATE sale_order SET mission_billing_unit = NULL WHERE id = %s", (self.order_d.id,))
        self.env.cr.execute("UPDATE res_company SET mission_billing_unit_default = NULL WHERE id = %s",
                            (self.company.id,))
        _migration('19.0.2.3.0', 'pre-migrate.py').migrate(self.env.cr, '19.0.2.2.1')
        self.env.invalidate_all()
        self.assertEqual(self.order_d.mission_billing_unit, 'day')
        self.assertEqual(self.order_h.mission_billing_unit, 'hour', "an order already set keeps its unit")
        self.assertEqual(self.company.mission_billing_unit_default, 'day')

    def test_migration_type_activite_existant(self):
        activity = self.env.ref('mission_report.hr_leave_type_activite')
        self.assertEqual(activity.request_unit, 'hour')
        self.env.flush_all()
        self.env.cr.execute("UPDATE hr_leave_type SET request_unit = 'day' WHERE id = %s", (activity.id,))
        self.env.invalidate_all()
        entry = self._entry(self.project_d, '2031-05-12', '2031-05-13')
        self.assertEqual(entry.holiday_status_id, activity)
        self.env.flush_all()
        before = entry.read(['date_from', 'date_to', 'number_of_days', 'number_of_hours',
                             'duration_display', 'request_unit_hours', 'request_unit_half'])[0]
        _migration('19.0.2.3.0', 'post-migrate.py').migrate(self.env.cr, '19.0.2.2.1')
        self.env.invalidate_all()
        self.assertEqual(activity.request_unit, 'hour')
        self.assertEqual(entry.read(list(before) [1:])[0], before)
        # Recalculée, une journée de mission au jour reste une journée.
        entry._compute_duration()
        self.assertEqual((entry.number_of_days, entry.number_of_hours), (2.0, 16.0))
        report = self._report('2031-05-01')
        self.assertEqual([(line['unit'], line['total']) for line in report._get_report_data()['missions']],
                         [('day', 2.0)])
