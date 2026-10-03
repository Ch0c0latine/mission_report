# -*- coding: utf-8 -*-
from datetime import date

from odoo import Command
from odoo.exceptions import UserError

from ..models.volet import split_volet_note
from .test_sale_delivery import TestSaleDelivery

# Note d'une affaire d'avant les champs de prestation : tout y est.
LEGACY_NOTE = (
    "<h5>Volet&nbsp;1&nbsp;:&nbsp;période du 01/01/2031 au 30/04/2031</h5>"
    "<p>La présente offre a pour objet des activités de contrôle pour un client test.</p>"
    "<p>Le descriptif détaillé figure au cahier des charges.</p>"
    "<p>Les prestations seront réalisées sur la base d'un fonctionnement en régie pour un montant "
    "journalier de 500EUR HT/jour travaillé. Ce volet concerne la période du 01/01/2031 au 30/04/2031: "
    "42 jours travaillés prévisionnels soit :</p>"
    "<p>janvier 2031 : 22 jours travaillés soit 11 000 €</p>"
    "<p>février 2031 : 20 jours travaillés soit 10 000 €</p>"
    "<p>Les frais de déplacement seront facturés au réel sur présentation des justificatifs.</p>"
    "<p><br></p>"
    "<h5>Principe de facturation</h5>"
    "<p>Facturation mensuelle des jours réalisés.</p>"
    "<h5>Conditions générales de service</h5><p>Article 1.</p>")


class TestVoletsMensuels(TestSaleDelivery):
    """Une ligne de journées par mois, jours livrés ventilés, textes de la prestation."""

    def _second(self, start, end, lines, confirm=True, **vals):
        """Une deuxième affaire de la mission A : ``lines`` = [(début, fin, quantité)]."""
        order = self.env['sale.order'].create({
            'partner_id': self.client_a.id,
            'order_line': [Command.create({
                'product_id': self.service.id, 'product_uom_qty': quantity,
                'mission_period_start': first, 'mission_period_end': last,
            }) for first, last, quantity in lines],
            **vals,
        })
        if confirm:
            order.action_confirm()
        order.write({'project_id': self.project_a.id, 'mission_date_start': start, 'mission_date_end': end})
        return order

    def _wizard(self, order, start, end):
        wizard = self.env['mission.volet.wizard'].with_context(default_order_id=order.id).create({})
        wizard.write({'date_start': start, 'date_end': end})
        return wizard

    def _create(self, wizard):
        return self.env['sale.order'].browse(wizard.action_create()['res_id'])

    # -- Nouveau volet ----------------------------------------------------------

    def test_new_volet_makes_one_day_line_per_month(self):
        self.line.price_unit = 635.0
        self.order.write({'project_id': self.project_a.id, 'note': LEGACY_NOTE})
        # 14 May - 10 July 2031: the first and the last months are cut to the dates of the volet.
        # May: 13 weekdays from the 14th, 22 May off. June: 21 weekdays, 2 June (Whit Monday) off.
        new = self._create(self._wizard(self.order, '2031-05-14', '2031-07-10'))
        lines = new._volet_day_lines()
        self.assertEqual(lines.mapped('product_uom_qty'), [12.0, 20.0, 8.0])
        self.assertEqual(lines.mapped('price_unit'), [635.0] * 3)
        self.assertEqual(lines.product_id, self.service)
        self.assertEqual(lines.mapped('mission_period_start'),
                         [date(2031, 5, 14), date(2031, 6, 1), date(2031, 7, 1)])
        self.assertEqual(lines.mapped('mission_period_end'),
                         [date(2031, 5, 31), date(2031, 6, 30), date(2031, 7, 10)])
        self.assertEqual(lines[0].name, "Assistance jours\n14/05/2031 – 31/05/2031")
        self.assertEqual(lines[0].mission_period_label(), "14/05/2031 – 31/05/2031")
        self.assertEqual(new.amount_untaxed, 40 * 635.0)

    def test_monthly_lines_keep_their_place_among_the_others(self):
        expenses = self.env['product.product'].create({
            'name': 'Dépenses test', 'type': 'service', 'can_be_expensed': True, 'list_price': 1.0})
        self.order.write({'project_id': self.project_a.id, 'order_line': [
            Command.create({'product_id': expenses.id, 'product_uom_qty': 300.0, 'price_unit': 1.0}),
            Command.create({'display_type': 'line_note', 'name': "Objet de la commande"}),
        ]})
        new = self._create(self._wizard(self.order, '2031-05-14', '2031-06-30'))
        kinds = [(line.mission_day_line, line.product_id == expenses, bool(line.display_type))
                 for line in new.order_line]
        self.assertEqual(kinds, [(True, False, False), (True, False, False),
                                 (False, True, False), (False, False, True)])
        self.assertEqual(new.order_line.filtered(lambda l: l.product_id == expenses).product_uom_qty, 0.0)

    def test_the_monthly_lines_of_the_origin_make_one_line_per_month(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-04-30'})
        second = self._second('2031-05-01', '2031-06-30', [
            ('2031-05-01', '2031-05-31', 19.0), ('2031-06-01', '2031-06-30', 20.0)])
        new = self._create(self._wizard(second, '2031-07-01', '2031-07-31'))
        self.assertEqual(new._volet_day_lines().mapped('product_uom_qty'), [22.0])

    def test_description_and_expenses_are_copied(self):
        self.order.write({
            'project_id': self.project_a.id, 'mission_volet_number': 3,
            'mission_date_start': '2031-01-01', 'mission_date_end': '2031-04-30',
            'mission_description': "<p>Activités de contrôle sur site.</p>",
            'mission_expenses_text': "<p>Les frais seront facturés au réel.</p>",
            'note': "<p>Principe de facturation : mensuel.</p>",
        })
        wizard = self._wizard(self.order, '2031-05-01', '2031-05-31')
        self.assertFalse(wizard.note_warning)
        new = self._create(wizard)
        self.assertEqual(new.mission_volet_number, 4)
        self.assertEqual(str(new.mission_date_start), '2031-05-01')
        self.assertEqual(str(new.mission_date_end), '2031-05-31')
        self.assertIn("Activités de contrôle sur site.", new.mission_description)
        self.assertIn("Les frais seront facturés au réel.", new.mission_expenses_text)
        self.assertEqual(new.note, self.order.note)
        self.assertNotIn("Volet", new.note)

    def test_a_legacy_note_is_split(self):
        self.order.write({'project_id': self.project_a.id, 'note': LEGACY_NOTE})
        wizard = self._wizard(self.order, '2031-05-01', '2031-05-31')
        self.assertFalse(wizard.note_warning)
        new = self._create(wizard)
        self.assertEqual(new.mission_volet_number, 2)
        self.assertIn("activités de contrôle pour un client test", new.mission_description)
        self.assertIn("cahier des charges", new.mission_description)
        self.assertNotIn("Volet", new.mission_description)
        self.assertNotIn("Les prestations seront réalisées", new.mission_description)
        self.assertIn("Les frais de déplacement seront facturés au réel", new.mission_expenses_text)
        self.assertNotIn("janvier 2031", new.mission_expenses_text)
        self.assertTrue(new.note.startswith("<h5>Principe de facturation</h5>"), new.note)
        self.assertIn("Conditions générales de service", new.note)
        for old in ("Volet", "Ce volet concerne", "janvier 2031", "Les prestations", "Les frais"):
            self.assertNotIn(old, new.note)

    def test_split_of_a_note(self):
        description, expenses, terms = split_volet_note(LEGACY_NOTE)
        self.assertEqual(description, "<p>La présente offre a pour objet des activités de contrôle pour un "
                                      "client test.</p><p>Le descriptif détaillé figure au cahier des charges.</p>")
        self.assertEqual(expenses, "<p>Les frais de déplacement seront facturés au réel sur présentation "
                                   "des justificatifs.</p>")
        self.assertTrue(terms.startswith("<h5>Principe de facturation</h5><p>Facturation mensuelle"))
        # The same note held in one block, without title and without expenses.
        wrapped = ("<div><p>Description.</p><p>Les prestations seront réalisées en régie.</p>"
                   "<p>Principe de facturation</p></div>")
        self.assertEqual(split_volet_note(wrapped), ("<p>Description.</p>", "", "<p>Principe de facturation</p>"))
        # Unknown text between the rate and the terms, no terms, nothing before the rate: not split.
        self.assertIsNone(split_volet_note(LEGACY_NOTE.replace("<p><br></p>", "<p>Autre chose.</p>")))
        self.assertIsNone(split_volet_note(LEGACY_NOTE.replace("Principe de facturation", "Facturation")))
        self.assertIsNone(split_volet_note("<p>Les prestations seront réalisées.</p><p>Principe de facturation</p>"))
        self.assertIsNone(split_volet_note(False))

    def test_an_old_order_takes_its_service_fields_from_its_note(self):
        self.order.write({'project_id': self.project_a.id, 'note': LEGACY_NOTE})
        self.order.action_mission_fill_from_note()
        self.assertEqual(self.order.mission_volet_number, 1)
        self.assertIn("activités de contrôle", self.order.mission_description)
        self.assertIn("frais de déplacement", self.order.mission_expenses_text)
        self.assertTrue(self.order.note.startswith("<h5>Principe de facturation</h5>"))
        # Already filled: nothing more to take, and a note that cannot be split is refused.
        with self.assertRaises(UserError):
            self.order.action_mission_fill_from_note()
        self.order.write({'mission_description': False, 'mission_expenses_text': False,
                          'note': "<p>Rien à découper.</p>"})
        with self.assertRaises(UserError):
            self.order.action_mission_fill_from_note()

    def test_a_legacy_note_that_cannot_be_split_is_copied(self):
        note = LEGACY_NOTE.replace("Principe de facturation", "Facturation")
        self.order.write({'project_id': self.project_a.id, 'note': note})
        wizard = self._wizard(self.order, '2031-05-01', '2031-05-31')
        self.assertTrue(wizard.note_warning)
        new = self._create(wizard)
        self.assertEqual(new.note, self.order.note)
        self.assertFalse(new.mission_description)
        self.assertFalse(new.mission_expenses_text)
        self.assertEqual(new.mission_volet_number, 2)

    def test_the_number_follows_every_order_of_the_mission(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-05-12',
                          'mission_volet_number': 7})
        second = self._second('2031-05-13', '2031-12-31', [(False, False, 20.0)],
                              note="<h5>Volet&nbsp;4&nbsp;:&nbsp;période du 13/05/2031 au 31/12/2031</h5>")
        # An order of the mission by its lines only, with the greatest number.
        third = self.env['sale.order'].create({
            'partner_id': self.client_a.id, 'mission_volet_number': 9,
            'order_line': [Command.create({'product_id': self.service.id, 'product_uom_qty': 1.0})]})
        third.write({'mission_date_start': '2032-01-01', 'mission_date_end': '2032-03-31'})
        third.order_line.project_id = self.project_a
        new = self._create(self._wizard(second, '2032-04-01', '2032-04-30'))
        self.assertEqual(new.mission_volet_number, 10)

    # -- Jours livrés ----------------------------------------------------------

    def test_validated_days_go_to_the_line_of_their_month(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-04-30'})
        second = self._second('2031-05-01', '2031-06-30', [
            ('2031-05-01', '2031-05-31', 19.0), ('2031-06-01', '2031-06-30', 20.0)])
        june = self.env['mission.activity.report'].create({
            'employee_id': self.employee.id, 'date_from': '2031-06-01'})
        self._entry(self.project_a, '2031-06-03', '2031-06-05')
        self._validate(self.report)
        self._validate(june)
        self.assertEqual(second.order_line.mapped('qty_delivered'), [9.0, 3.0])
        self.assertEqual(self.line.qty_delivered, 0.0)

    def test_a_day_outside_the_periods_goes_to_the_nearest_line(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-04-30'})
        second = self._second('2031-05-01', '2031-06-30', [
            ('2031-05-01', '2031-05-07', 5.0), ('2031-05-15', '2031-06-30', 30.0)])
        self._validate(self.report)
        # 5, 6, 7 May in the first period; 9 May is nearer to it, 12-14 May to the second.
        self.assertEqual(second.order_line.mapped('qty_delivered'), [4.0, 5.0])

    def test_undated_lines_share_the_days_without_counting_them_twice(self):
        self.line.product_uom_qty = 40.0
        self.order.order_line = [Command.create({'product_id': self.service.id, 'product_uom_qty': 30.0})]
        self._validate(self.report)
        first, second = self.order.order_line
        # 9 days, 40/70 and 30/70 of them, the rest on the last line.
        self.assertEqual(first.qty_delivered, 5.14)
        self.assertEqual(second.qty_delivered, 3.86)

    def test_an_order_with_two_missions(self):
        self.order.order_line = [Command.create({'product_id': self.service.id, 'product_uom_qty': 10.0})]
        line_b = self.order.order_line - self.line
        self.line.project_id = self.project_a
        line_b.project_id = self.project_b
        self.project_b.sale_line_id = line_b
        self._validate(self.report)
        self.assertEqual(self.line.qty_delivered, 9.0)
        self.assertEqual(line_b.qty_delivered, 2.0)

    def test_a_day_between_two_orders_goes_to_the_previous_one(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-05-07'})
        second = self._second('2031-05-14', '2031-12-31', [(False, False, 20.0)])
        self._validate(self.report)
        # 5, 6, 7 May on the first order, and 9, 12, 13 May between both; 14-16 May on the second.
        self.assertEqual(self.line.qty_delivered, 6.0)
        self.assertEqual(second.order_line.qty_delivered, 3.0)
        self.assertEqual(self.project_a._mission_order_on(date(2031, 5, 10)), self.order)
        self.assertEqual(self.project_a._mission_order_on(date(2030, 12, 1)), self.order)
        self.assertEqual(self.project_a._mission_order_on(date(2032, 6, 1)), second)

    def test_confirming_an_order_takes_its_days(self):
        self.order.write({'mission_date_start': '2031-01-01', 'mission_date_end': '2031-05-12'})
        second = self._second('2031-05-13', '2031-12-31', [(False, False, 20.0)], confirm=False)
        self._validate(self.report)
        self.assertEqual(self.line.qty_delivered, 9.0, "only the confirmed orders count")
        second.action_confirm()
        self.assertEqual(self.line.qty_delivered, 5.0)
        self.assertEqual(second.order_line.qty_delivered, 4.0)

    # -- Impression ------------------------------------------------------------

    def test_the_quote_counts_days(self):
        expenses = self.env['product.product'].create({
            'name': 'Dépenses test', 'type': 'service', 'can_be_expensed': True, 'list_price': 1.0})
        self.order.order_line = [
            Command.create({'product_id': expenses.id, 'product_uom_qty': 300.0, 'price_unit': 1.0}),
            Command.create({'display_type': 'line_note', 'name': "Objet"})]
        day, expense, note = self.order.order_line.sorted('id')
        self.assertEqual(self.line.mission_quantity_label(), "40 jours")
        day.product_uom_qty = 1.0
        self.assertEqual(day.mission_quantity_label(), "1 jour")
        day.product_uom_qty = 10.5
        self.assertEqual(day.mission_quantity_label(), "10,5 jours")
        self.order.order_line = [Command.create({'product_id': self.service.id, 'product_uom_qty': 12.0})]
        self.assertEqual(self.order._volet_day_lines().mission_quantity_label(), "22,5 jours")
        self.assertEqual((day.mission_day_line, expense.mission_day_line, note.mission_day_line),
                         (True, False, False))
        self.assertFalse(day.mission_period_label())
