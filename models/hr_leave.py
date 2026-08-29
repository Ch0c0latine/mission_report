# -*- coding: utf-8 -*-
from odoo import models, fields


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    project_id = fields.Many2one(
        'project.project',
        string='Projet',
        required=True,
        ondelete='restrict',
        help='Projet associé à la saisie de rapport de mission.'
    )
