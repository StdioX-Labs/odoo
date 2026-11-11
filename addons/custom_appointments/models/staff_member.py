from odoo import models, fields, api


class StaffMember(models.Model):
    _name = 'custom.staff.member'
    _description = 'Staff Member for Appointments'
    _rec_name = 'name'

    name = fields.Char(string='Full Name', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', help='Link to HR Employee if available', ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Related User', 
                              help='User account linked to this staff member. Set manually or click "Link User by Email"')
    image = fields.Image(string='Photo', help='Staff member photo')
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    branch_id = fields.Many2one('custom.branch', string='Branch', required=True)
    
    is_bookable = fields.Boolean(string='Available for Booking', default=True)
    specialization = fields.Char(string='Specialization/Role')
    hourly_rate = fields.Float(string='Hourly Rate', help='Rate per hour for services')
    
    monday_available = fields.Boolean(string='Monday', default=True)
    tuesday_available = fields.Boolean(string='Tuesday', default=True)
    wednesday_available = fields.Boolean(string='Wednesday', default=True)
    thursday_available = fields.Boolean(string='Thursday', default=True)
    friday_available = fields.Boolean(string='Friday', default=True)
    saturday_available = fields.Boolean(string='Saturday', default=False)
    sunday_available = fields.Boolean(string='Sunday', default=False)
    
    start_time = fields.Float(string='Start Time', default=9.0, help='Daily start time (24h format)')
    end_time = fields.Float(string='End Time', default=17.0, help='Daily end time (24h format)')
    
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    
    appointment_count = fields.Integer(string='Total Appointments', compute='_compute_appointment_stats', store=False)
    confirmed_appointment_count = fields.Integer(string='Confirmed Appointments', compute='_compute_appointment_stats', store=False)
    completed_appointment_count = fields.Integer(string='Completed Appointments', compute='_compute_appointment_stats', store=False)
    this_month_appointments = fields.Integer(string='This Month Appointments', compute='_compute_appointment_stats', store=False)
    
    @api.depends('name', 'specialization')
    def _compute_display_name(self):
        for record in self:
            if record.specialization:
                record.display_name = f"{record.name} ({record.specialization})"
            else:
                record.display_name = record.name
    
    display_name = fields.Char(compute='_compute_display_name', store=True)

    booking_url = fields.Char(
        string='Booking Link', compute='_compute_booking_url',
        help='Share this link so clients can book this staff member directly')

    def _compute_booking_url(self):
        for staff in self:
            if staff.id:
                slug = self.env['ir.http']._slug(staff)
                staff.booking_url = f"{staff.get_base_url()}/book/{slug}"
            else:
                staff.booking_url = False

    @api.model
    def _from_booking_slug(self, staff_slug):
        """Staff member a /book/<slug> link points at, if still bookable."""
        staff_id = self.env['ir.http']._unslug(staff_slug)[1]
        if not staff_id:
            return self.browse()
        return self.search([
            ('id', '=', staff_id),
            ('active', '=', True),
            ('is_bookable', '=', True),
        ], limit=1)

    def action_open_booking_page(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.booking_url,
            'target': 'new',
        }
    
    def action_link_user_by_email(self):
        """Action to find and link the user account matching the staff member's email"""
        for staff in self:
            if staff.email:
                # First try to match by login (email as username)
                user = self.env['res.users'].sudo().search(
                    [('login', '=', staff.email)], limit=1
                )
                # If not found, try to match by email field
                if not user:
                    user = self.env['res.users'].sudo().search(
                        [('email', '=', staff.email)], limit=1
                    )
                if user:
                    staff.user_id = user.id
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'User Linked',
                            'message': f'Successfully linked to user: {user.name}',
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'User Not Found',
                            'message': f'No user found with email: {staff.email}',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'No Email',
                        'message': 'Please set an email address first.',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
    
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-link user on create if email matches"""
        records = super().create(vals_list)
        for record in records:
            if record.email and not record.user_id:
                user = self.env['res.users'].sudo().search(
                    ['|', ('login', '=', record.email), ('email', '=', record.email)], limit=1
                )
                if user:
                    record.user_id = user.id
        return records
    
    def _compute_appointment_stats(self):
        """Compute appointment statistics for each staff member"""
        from datetime import datetime, date
        
        for staff in self:
            appointments = self.env['custom.appointment'].search([('staff_member_id', '=', staff.id)])
            
            staff.appointment_count = len(appointments)
            staff.confirmed_appointment_count = len(appointments.filtered(lambda a: a.state == 'confirmed'))
            staff.completed_appointment_count = len(appointments.filtered(lambda a: a.state == 'completed'))
            
            today = date.today()
            first_day_month = today.replace(day=1)
            this_month_appts = appointments.filtered(
                lambda a: a.start and a.start.date() >= first_day_month and a.start.date() <= today
            )
            staff.this_month_appointments = len(this_month_appts)
    
    def action_view_appointments(self):
        """Action to view all appointments for this staff member"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Appointments - {self.name}',
            'res_model': 'custom.appointment',
            'view_mode': 'list,form,calendar',
            'domain': [('staff_member_id', '=', self.id)],
            'context': {'default_staff_member_id': self.id},
        }
    
    def action_view_calendar(self):
        """Action to view calendar for this staff member"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Calendar - {self.name}',
            'res_model': 'custom.appointment',
            'view_mode': 'calendar,list,form',
            'domain': [('staff_member_id', '=', self.id)],
            'context': {'default_staff_member_id': self.id},
        }
    
    @api.model
    def sync_from_employees(self):
        """Sync staff members from HR employees"""
        employees = self.env['hr.employee'].search([])
        created_count = 0
        updated_count = 0
        
        for employee in employees:
            existing_staff = self.search([('employee_id', '=', employee.id)], limit=1)
            
            default_branch = self.env['custom.branch'].search([], limit=1)
            if not default_branch:
                continue
                
            staff_vals = {
                'name': employee.name,
                'email': employee.work_email or employee.private_email or '',
                'phone': employee.work_phone or employee.mobile_phone or '',
                'employee_id': employee.id,
                'branch_id': default_branch.id,
                'specialization': employee.job_title or '',
                'image': employee.image_1920 if employee.image_1920 else False,
                'is_bookable': True,  # Default to bookable, can be changed manually
            }
            
            if existing_staff:
                existing_staff.write(staff_vals)
                updated_count += 1
            else:
                self.create(staff_vals)
                created_count += 1
                
        return {
            'created': created_count,
            'updated': updated_count,
            'total_employees': len(employees)
        }
    
    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Auto-populate fields when employee is selected"""
        if self.employee_id:
            self.name = self.employee_id.name
            self.email = self.employee_id.work_email or self.employee_id.private_email or ''
            self.phone = self.employee_id.work_phone or self.employee_id.mobile_phone or ''
            self.specialization = self.employee_id.job_title or ''
            self.image = self.employee_id.image_1920 if self.employee_id.image_1920 else False
    
    def action_sync_from_employee(self):
        """Action to sync individual staff member from linked employee"""
        if self.employee_id:
            self.write({
                'name': self.employee_id.name,
                'email': self.employee_id.work_email or self.employee_id.private_email or '',
                'phone': self.employee_id.work_phone or self.employee_id.mobile_phone or '',
                'specialization': self.employee_id.job_title or '',
                'image': self.employee_id.image_1920 if self.employee_id.image_1920 else False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'Staff member {self.name} synced from employee data.',
                    'type': 'success',
                }
            }
    
    def unlink(self):
        """Override unlink to delete related appointments first (cascade delete)"""
        appointments = self.env['custom.appointment'].search([('staff_member_id', 'in', self.ids)])
        appointments.unlink()
        return super(StaffMember, self).unlink()
