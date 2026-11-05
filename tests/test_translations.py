# -*- coding: utf-8 -*-
# Copyright 2026 T.T.C. SAS
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""The catalogues are read by Odoo itself: an entry it cannot read stops the whole update."""
import glob
import os

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.translate import PoFileReader


@tagged('post_install', '-at_install', 'mission_report')
class TestTranslations(TransactionCase):

    def test_every_catalogue_is_readable_by_odoo(self):
        folder = os.path.join(os.path.dirname(__file__), '..', 'i18n')
        files = glob.glob(os.path.join(folder, '*.po'))
        self.assertTrue(files)
        for path in files:
            rows = list(PoFileReader(path))
            self.assertTrue(rows, path)

    def test_the_new_texts_are_translated_in_french(self):
        folder = os.path.join(os.path.dirname(__file__), '..', 'i18n')
        sources = {row['src']: row['value'] for row in PoFileReader(os.path.join(folder, 'fr.po'))}
        for source in ("Other calendar costs", "Other costs per day worked", "Other monthly costs",
                       "Other yearly costs", "Pay and charges", "Fixed amount per day worked",
                       "Fixed amount per month", "Breakdown of the monthly revenue", "Margin of the company",
                       "Other mission charges", "Business referral", "Full management, client side"):
            self.assertTrue(sources.get(source), source)
