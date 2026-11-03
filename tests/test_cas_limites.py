# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Cas limites du compte rendu mensuel et des quantités livrées."""
from odoo.exceptions import UserError

from .test_sale_delivery import TestSaleDelivery


class TestCasLimites(TestSaleDelivery):

    def _report(self, month):
        return self.env['mission.activity.report'].create({'employee_id': self.employee.id, 'date_from': month})

    def test_une_saisie_a_cheval_sur_deux_mois_est_comptee_une_fois(self):
        """29 mai - 3 juin 2031 : chaque mois porte ses jours, la somme est celle de la saisie."""
        entry = self._entry(self.project_a, '2031-05-29', '2031-06-03')
        self.assertEqual(entry.number_of_days, 3.0, "29 et 30 mai, 3 juin (le 2 juin est férié, Pentecôte)")
        may, june = self.report, self._report('2031-06-01')
        self._validate(may)
        self._validate(june)
        self.assertEqual(self.line.qty_delivered, 9.0 + 3.0, "les neuf jours de mai et les trois de la saisie")
        june.action_reset_to_draft()
        self.assertEqual(self.line.qty_delivered, 9.0 + 2.0, "juin repris : il reste ses jours de mai")

    def test_un_compte_rendu_valide_ne_se_supprime_pas(self):
        self._validate(self.report)
        with self.assertRaises(UserError):
            self.report.unlink()
        self.assertEqual(self.line.qty_delivered, 9.0)

    def test_valider_deux_fois_ne_double_pas_les_jours(self):
        self._validate(self.report)
        self.report.action_reset_to_draft()
        self._validate(self.report)
        self.env['mission.activity.report']._cron_sale_sync_delivered()
        self.assertEqual(self.line.qty_delivered, 9.0)

    def test_un_mois_sans_jours_feries_le_dit(self):
        """Une année sans jours fériés saisis : le compte rendu avertit, et les génère d'un clic."""
        self.assertFalse(self.report.holidays_warning, "2031 a ses jours fériés")
        report = self._report('2034-03-01')
        self.assertIn("2034", report.holidays_warning)
        report.action_generate_holidays()
        report.invalidate_recordset(['holidays_warning'])
        self.assertFalse(report.holidays_warning)

    def test_les_lignes_portant_le_projet_cree_par_la_commande_sont_alimentees(self):
        """Une ligne dont le projet est celui que la commande a créé (sans saisie) suit la mission de sa commande."""
        auto = self.env['project.project'].create({'name': "Projet créé par la commande"})
        self.order.project_id = self.project_a
        self.line.project_id = auto
        self._validate(self.report)
        self.assertEqual(self.line.qty_delivered, 9.0)

    def test_une_ligne_d_une_autre_mission_reste_a_elle(self):
        """Le projet de la ligne porte des saisies : c'est une autre mission de la commande."""
        self.order.project_id = self.project_a
        self.line.project_id = self.project_b
        self._validate(self.report)
        self.assertEqual(self.line.qty_delivered, 2.0, "the two days of mission B, not the nine of A")

    def test_la_rentabilite_compte_les_salaires_des_journees_validees(self):
        """Le panneau de rentabilité du projet porte le coût des journées : salaire × coefficient ÷ jours ouvrés."""
        self.employee.version_id.wage = 3800.0
        self.company.mission_cost_coefficient = 1.0
        self._validate(self.report)
        project = self.project_a
        data = project._get_profitability_items(with_action=False)
        costs = {item['id']: item for item in data['costs']['data']}
        # May 2031 holds 19 working days: 200 a day, nine days validated on the mission.
        self.assertAlmostEqual(costs['mission_salaries']['billed'], -1800.0, places=2)
        self.company.mission_cost_coefficient = 1.5
        costs = {item['id']: item for item in project._get_profitability_items(with_action=False)['costs']['data']}
        self.assertAlmostEqual(costs['mission_salaries']['billed'], -2700.0, places=2)
        self.assertLessEqual(data['costs']['total']['billed'], -1800.0)

    def test_les_salaires_ne_sont_montres_qu_aux_responsables(self):
        self.employee.version_id.wage = 3800.0
        self._validate(self.report)
        user = self.env['res.users'].create({
            'name': "Simple utilisateur", 'login': 'simple_rentabilite_zz@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.assertFalse(self.project_a.with_user(user)._mission_show_costs())
        self.assertTrue(self.project_a._mission_show_costs())
