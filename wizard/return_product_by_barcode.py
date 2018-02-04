# -*- coding: utf-8 -*-
# Copyright 2018 Humanytek - Manuel Marquez <manuel@humanytek.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

from datetime import datetime, timedelta
import hashlib

from openerp import api, fields, models, _
import openerp.addons.decimal_precision as dp
from openerp.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)


class ReturnProductBarcode(models.TransientModel):
    _name = 'return.product.barcode'

    def _get_valid_date(self):
        """Returns min date valid for returns"""

        expiration_days_qty = \
            self.env.user.company_id.sale_return_time_expiration_days

        valid_datetime = datetime.now() - timedelta(days=expiration_days_qty)
        valid_date = valid_datetime.strftime('%Y-%m-%d')

        return valid_date

    def _compute_wizard_hash(self):
        """Computes default value of field wizard hash"""

        wizard_hash = hashlib.md5(
            str(self.id) +
            datetime.now().strftime('%Y-%m-%d %H:%M:%S %f')
        ).hexdigest()

        return wizard_hash

    customer_id = fields.Many2one('res.partner', 'Customer', domain=[
                                  ('customer', '=', True)])
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_barcode = fields.Char(
        'Barcode',
        help="International Article Number used for product identification.")
    product_image_medium = fields.Binary(
        related='product_id.image_medium', readonly=True)
    product_name = fields.Char(related='product_id.name', readonly=True)
    product_attribute_value_ids = fields.Many2many(
        related='product_id.attribute_value_ids', readonly=True)
    product_default_code = fields.Char(
        related='product_id.default_code', readonly=True)
    product_volume = fields.Float(related='product_id.volume', readonly=True)
    product_weight = fields.Float(related='product_id.weight', readonly=True)
    return_reason_qty_ids = fields.One2many(
        'return.product.reason.unit',
        'wizard_id',
        'Quantity by reason',
        required=True)
    wizard_hash = fields.Char('Wizard hash', default=_compute_wizard_hash)

    @api.model
    def _get_picking(self, customer, product, expired=False):
        """Returns stock picking"""

        customer.ensure_one()
        product.ensure_one()

        StockPicking = self.env['stock.picking']

        if expired:
            domain_search = [
                ('company_id', '=', self.env.user.company_id.id),
                ('partner_id', '=', customer.id),
                ('move_lines_related.product_id', '=', product.id),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id.state', 'in', ['sale', 'done']),
                ('state', '=', 'done'),
            ]
            order_search = 'min_date desc'

        else:
            domain_search = [
                ('company_id', '=', self.env.user.company_id.id),
                ('partner_id', '=', customer.id),
                ('sale_id.date_order', '>=', self._get_valid_date()),
                ('move_lines_related.product_id', '=', product.id),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id.state', 'in', ['sale', 'done']),
                ('state', '=', 'done'),
            ]
            order_search = 'min_date'

        pickings = StockPicking.search(domain_search, order=order_search)

        if pickings:

            for picking in pickings:

                pickings_childs_returned = StockPicking.search([
                    ('origin', '=', picking.name),
                    ('move_lines_related.product_id', '=', product.id),
                    ('state', '=', 'done'),
                    ('picking_type_code', '=', 'incoming'),
                ])

                pck_moves_product = picking.move_lines_related.filtered(
                    lambda move: move.product_id.id == product.id
                    and move.state == 'done')

                pck_product_qty_total = sum(
                    pck_moves_product.mapped('product_uom_qty'))

                ReturnReasonProductQty = self.env['return.reason.product.qty']
                # TODO: no more than one instance of the wizard is being considered simultaneously.
                # Fix this.
                picking_taken = ReturnReasonProductQty.search([
                    ('wizard_hash', '=', self.wizard_hash),
                    ('product_id', '=', product.id),
                    ('picking_id', '=', picking.id),
                    ('completed', '=', False),
                ])

                if not pickings_childs_returned:

                    if len(picking_taken) < pck_product_qty_total:
                        return picking

                else:

                    pck_returned_moves_with_product = \
                        pickings_childs_returned.mapped('move_lines_related').filtered(
                            lambda move: move.product_id.id == product.id and
                            move.state == 'done'
                        )

                    pickings_returned_product_qty_total = sum(
                        pck_returned_moves_with_product.mapped(
                            'product_uom_qty')
                    )

                    if (pickings_returned_product_qty_total +
                        len(picking_taken)) < \
                       pck_product_qty_total:

                        return picking
        return False

    @api.model
    def _get_sale_product_price(self, sale_order, product):
        """Returns unit price of product in sale order"""

        line_product = sale_order.order_line.filtered(
            lambda line: line.product_id.id == product.id)

        product_price = line_product[0].price_unit

        for tax in line_product[0].tax_id:

            product_price += tax.amount * line_product[0].price_unit / 100

        return product_price

    @api.model
    def _get_move_product(self, picking, product):
        """Returns the move of product in the picking"""

        picking_product_moves = picking.move_lines.filtered(
            lambda move: not move.scrapped and
            move.product_id.id == product.id)

        return picking_product_moves[0]

    @api.onchange('product_barcode')
    def onchange_product_barcode(self):

        if self.product_barcode:

            ProductProduct = self.env['product.product']
            product = ProductProduct.search(
                [('barcode', '=', self.product_barcode)])

            if product:
                self.product_id = product[0]
                self.product_barcode = False

                return_reason_qty_ids = list()
                ReturnReasonProductQty = self.env['return.reason.product.qty']
                return_reason_product_lines = ReturnReasonProductQty.search([
                    ('wizard_hash', '=', self.wizard_hash),
                ])

                for return_reason_unit in return_reason_product_lines:

                    return_reason_qty_ids.append(
                        (0, 0, {
                            'product_id': return_reason_unit.product_id.id,
                            'product_uom_qty': return_reason_unit.product_uom_qty,
                            'reason_return_id': return_reason_unit.reason_return_id.id,
                            'wizard_hash': return_reason_unit.wizard_hash,
                            'record_hash': return_reason_unit.record_hash,
                            'picking_id': return_reason_unit.picking_id and
                            return_reason_unit.picking_id.id,
                            'sale_product_price':
                            return_reason_unit.sale_product_price,
                            'picking_move_id':
                            return_reason_unit.picking_move_id,
                        })
                    )

                return_reason_unit_hash = hashlib.md5(
                    self.wizard_hash +
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S %f') +
                    str(self.product_id.id)
                ).hexdigest()

                picking = self._get_picking(self.customer_id, product)
                reason_return_id = False

                if not picking:

                    picking = self._get_picking(
                        self.customer_id, product, expired=True)
                    StockWarehouseReturn = self.env['stock.warehouse.return']
                    expired_reason_return = StockWarehouseReturn.search([
                        ('expired', '=', True),
                    ])

                    if expired_reason_return:
                        reason_return_id = expired_reason_return[0].id

                sale_product_price = self._get_sale_product_price(
                    picking.sale_id, product)
                picking_move = self._get_move_product(
                    picking, product)
                picking_move_id = picking_move and picking_move.id

                return_reason_unit_data = {
                    'product_id': self.product_id.id,
                    'product_uom_qty': 1,
                    'wizard_hash': self.wizard_hash,
                    'record_hash': return_reason_unit_hash,
                    'picking_id': picking and picking.id,
                    'sale_product_price': sale_product_price,
                    'reason_return_id': reason_return_id,
                    'picking_move_id': picking_move_id,
                }

                ReturnReasonProductQty.create(return_reason_unit_data)

                return_reason_qty_ids.append(
                    (0, 0, return_reason_unit_data))
                self.return_reason_qty_ids = return_reason_qty_ids

            else:
                raise ValidationError(
                    _('There is no product with that barcode.'))

    @api.model
    def _do_transfer_return(self, picking):
        self.ensure_one()

        for pack in picking.pack_operation_ids:
            if pack.product_qty > 0:
                pack.write({'qty_done': pack.product_qty})
            else:
                pack.unlink()

        picking.do_transfer()

    @api.model
    def _create_return(self, line_return, return_supplier=False):
        """Returns picking of return of product."""

        if line_return.reason_return_cat_type != 'return_supplier' or \
           not return_supplier:
            picking = line_return.picking_id
            pick_type_id = line_return.reason_return_id.return_picking_type_id.id
            location_dest_id = line_return.return_location_id.id
            move = line_return.picking_move_id

        elif return_supplier:
            StockPicking = self.env['stock.picking']
            picking = StockPicking.search([
                ('name', '=', line_return.picking_purchase_name),
            ])
            if not picking:
                raise UserError('The picking receipt %s indicated in product %s does not exist.',
                                line_return.picking_purchase_name, line_return.product_id.name)
            pick_type_id = line_return.reason_return_id.supplier_return_picking_type_id.id
            location_dest_id = line_return.reason_return_id.supplier_return_location_id.id

            picking_move = self._get_move_product(
                picking, line_return.product_id)
            move = picking_move and picking_move.id

        if picking.state != 'done':
            raise UserError(
                _("You may only return pickings that are Done!"))

        StockMove = self.env['stock.move']

        # Cancel assignment of existing chained assigned moves
        moves_to_unreserve = []
        for move in picking.move_lines:
            to_check_moves = [
                move.move_dest_id] if move.move_dest_id.id else []
            while to_check_moves:
                current_move = to_check_moves.pop()
                if current_move.state not in ('done', 'cancel') and \
                   current_move.reserved_quant_ids:

                    moves_to_unreserve.append(current_move.id)

                split_move_ids = StockMove.search([
                    ('split_from', '=', current_move.id),
                ])
                if split_move_ids:
                    to_check_moves += split_move_ids

        if moves_to_unreserve:
            StockMove.do_unreserve(moves_to_unreserve)
            # break the link between moves in order to be able to fix them
            # later if needed
            StockMove.browse(moves_to_unreserve).write({
                'move_orig_ids': False})

        # Create new picking for returned product
        new_picking = picking.copy({
            'move_lines': [],
            'picking_type_id': pick_type_id,
            'state': 'draft',
            'origin': picking.name,
            'location_id': picking.location_dest_id.id,
            'location_dest_id': location_dest_id,
        })

        # The return of a return should be linked with the original's
        # destination move if it was not cancelled
        if move.origin_returned_move_id.move_dest_id.id and \
           move.origin_returned_move_id.move_dest_id.state != 'cancel':

            move_dest_id = move.origin_returned_move_id.move_dest_id.id
        else:
            move_dest_id = False

        move.copy({
            'product_id': line_return.product_id.id,
            'product_uom_qty': line_return.product_uom_qty,
            'picking_id': new_picking.id,
            'state': 'draft',
            'location_id': move.location_dest_id.id,
            'location_dest_id': location_dest_id,
            'picking_type_id': pick_type_id,
            'warehouse_id': picking.picking_type_id.warehouse_id.id,
            'origin_returned_move_id': move.id,
            'procure_method': 'make_to_stock',
            'move_dest_id': move_dest_id,
        })

        new_picking.action_confirm()
        new_picking.action_assign()
        self._do_transfer_return(new_picking)

        return new_picking

    @api.multi
    def return_product(self):
        """Proccess returns of product"""

        self.ensure_one()

        for line_return in self.return_reason_qty_ids:

            return_picking = self._create_return(line_return)

            if line_return.reason_return_cat_type == 'return_supplier':
                self._create_return(line_return, return_supplier=True)

            ReturnReasonProductQty = self.env['return.reason.product.qty']
            line_return_stored = ReturnReasonProductQty.search([
                ('wizard_hash', '=', line_return.wizard_hash),
                ('record_hash', '=', line_return.record_hash),
                ('product_id', '=', line_return.product_id.id),
                ('picking_id', '=', line_return.picking_id.id),
                ('completed', '=', False),
            ])

            if line_return_stored:
                line_return_stored.write({'completed': True})


class ReturnProductReasonUnit(models.TransientModel):
    _name = 'return.product.reason.unit'

    wizard_id = fields.Many2one(
        'return.product.barcode', 'Wizard', required=True)
    reason_return_id = fields.Many2one(
        'stock.warehouse.return', 'Return Reason')
    reason_return_cat_type = fields.Selection(
        related='reason_return_id.category_type')
    reason_return_expired = fields.Boolean(related='reason_return_id.expired')
    return_location_id = fields.Many2one(
        related='reason_return_id.return_location_id', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_uom_qty = fields.Float(
        'Quantity', required=True, default=1, readonly=True)
    product_attribute_value_ids = fields.Many2many(
        related='product_id.attribute_value_ids', readonly=True)
    product_default_code = fields.Char(
        related='product_id.default_code', readonly=True)
    wizard_hash = fields.Char('Wizard hash', required=True)
    record_hash = fields.Char('Record hash', required=True)
    picking_id = fields.Many2one('stock.picking', 'Transfer')
    sale_id = fields.Many2one(related='picking_id.sale_id')
    sale_date_order = fields.Datetime(related='sale_id.date_order')
    sale_product_price = fields.Float(
        'Amount', digits=dp.get_precision('Product Price'), default=0.0)
    picking_purchase_name = fields.Char('Picking Name of Purchase')
    picking_move_id = fields.Many2one('stock.move', 'Move of product')

    @api.onchange('reason_return_id', 'picking_purchase_name')
    def onchange_fields(self):

        ReturnReasonProductQty = self.env['return.reason.product.qty']

        return_reason_product_rec = ReturnReasonProductQty.search([
            ('wizard_hash', '=', self.wizard_hash),
            ('record_hash', '=', self.record_hash),
        ])

        if return_reason_product_rec:

            if self.reason_return_id:
                return_reason_product_rec.write({
                    'reason_return_id': self.reason_return_id.id})

            if self.picking_purchase_name:
                return_reason_product_rec.write({
                    'picking_purchase_name': self.picking_purchase_name})
