# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from openerp import fields, models


class StockWarehouseReturn(models.Model):
    _inherit = 'stock.warehouse.return'

    return_location_id = fields.Many2one(
        'stock.location', 'Return Location', ondelete='restrict')

    expired = fields.Boolean('Time Expired')
    category_id = fields.Many2one(
        'stock.warehouse.return.category', 'Category', required=True)


class StockWarehouseReturnCategory(models.Model):
    _name = 'stock.warehouse.return.category'

    name = fields.Char('Category')
    active = fields.Boolean('Active ?', default=True)
