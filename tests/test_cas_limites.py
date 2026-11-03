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
