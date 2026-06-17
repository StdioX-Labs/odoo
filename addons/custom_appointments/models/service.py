from odoo import models, fields, api


class CompanyService(models.Model):
    _name = 'company.service'
    _description = 'Company Service'
    _rec_name = 'name'

    name = fields.Char(string='Service Name', required=True)
    code = fields.Char(string='Service Code')
    description = fields.Text(string='Description')
    image = fields.Image(string='Service Image', help='Image representing this service')
    
    category_id = fields.Many2one('service.category', string='Category', required=True)
    
    price = fields.Float(string='Price', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', 
                                  default=lambda self: self.env.company.currency_id)
    
    fee_type = fields.Selection([
        ('full', 'Full Price'),
        ('partial', 'Booking Fee (Partial Payment)')
    ], string='Payment Type', default='full', required=True,
       help='Choose whether to charge full price or a booking fee upfront')
    booking_fee = fields.Float(string='Booking Fee', default=0.0,
                               help='Amount to charge as booking fee (if partial payment is selected)')
    booking_fee_percentage = fields.Float(string='Booking Fee %', compute='_compute_booking_fee_percentage', store=True,
                                         help='Booking fee as a percentage of full price')
    
    duration = fields.Float(string='Duration (Hours)', default=1.0, help='Service duration in hours')
    duration_minutes = fields.Integer(string='Duration (Minutes)', compute='_compute_duration_minutes', store=True)
    
    is_bookable = fields.Boolean(string='Bookable Online', default=True)
    requires_approval = fields.Boolean(string='Requires Approval', default=False)
    max_advance_booking = fields.Integer(string='Max Advance Booking (Days)', default=30)
    
    requires_specific_staff = fields.Boolean(string='Requires Specific Staff', default=False)
    allowed_staff_ids = fields.Many2many('custom.staff.member', string='Allowed Staff Members')
    
    active = fields.Boolean(string='Active', default=True)
    published = fields.Boolean(string='Published', default=True)
    sequence = fields.Integer(string='Sequence', default=10)
    
    preparation_time = fields.Float(string='Preparation Time (Hours)', default=0.0)
    cleanup_time = fields.Float(string='Cleanup Time (Hours)', default=0.0)
    notes = fields.Text(string='Internal Notes')
    customer_notes = fields.Text(string='Customer Instructions')
    
    @api.depends('duration')
    def _compute_duration_minutes(self):
        for record in self:
            record.duration_minutes = int(record.duration * 60)
    
    @api.depends('price', 'booking_fee')
    def _compute_booking_fee_percentage(self):
        for record in self:
            if record.price > 0:
                record.booking_fee_percentage = (record.booking_fee / record.price) * 100
            else:
                record.booking_fee_percentage = 0.0
    
    def get_amount_to_charge(self):
        """Get the amount to charge based on fee type"""
        self.ensure_one()
        if self.fee_type == 'partial' and self.booking_fee > 0:
            return self.booking_fee
        return self.price
    
    def get_remaining_amount(self):
        """Get the remaining amount after booking fee"""
        self.ensure_one()
        if self.fee_type == 'partial' and self.booking_fee > 0:
            return self.price - self.booking_fee
        return 0.0
    
    @api.depends('name', 'price', 'currency_id')
    def _compute_display_name(self):
        for record in self:
            if record.currency_id:
                record.display_name = f"{record.name} - {record.currency_id.symbol}{record.price}"
            else:
                record.display_name = f"{record.name} - ${record.price}"
    
    display_name = fields.Char(compute='_compute_display_name', store=True)
    
    @api.model
    def get_available_services(self, category_id=None):
        """Get services available for booking"""
        domain = [
            ('active', '=', True),
            ('is_bookable', '=', True),
            ('published', '=', True)
        ]
        if category_id:
            domain.append(('category_id', '=', category_id))
        
        return self.search(domain, order='sequence, name')

    def is_staff_allowed(self, staff):
        """Return True if `staff` may provide this service."""
        self.ensure_one()
        if not self.requires_specific_staff:
            return True
        return staff in self.allowed_staff_ids
