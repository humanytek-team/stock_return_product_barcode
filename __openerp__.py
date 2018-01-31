# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

{
    'name': 'Manager of returns of product by barcode',
    'version': '9.0.0.1.0',
    'category': 'Stock',
    'author': 'Humanytek',
    'website': "http://www.humanytek.com",
    'license': 'AGPL-3',
    'depends': [
        'stock',
        'sale_stock',
        'stock_warehouse_returns',
        'sale_stock_restrict_return_picking_expiration_time',
    ],
    'data': [
        'views/stock_warehouse_return_view.xml',
        'wizard/return_product_by_barcode_view.xml',
    ],
    'installable': True,
    'auto_install': False
}
