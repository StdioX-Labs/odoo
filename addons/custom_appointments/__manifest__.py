{
    'name': 'Custom Appointments',
    'version': '1.2.0',
    'category': 'Services',
    'summary': 'Complete appointment booking system with staff, branches, and services',
    'description': '''
        Custom Appointments Module
        
        Features:
        - Staff member management with booking capabilities
        - Branch management for multi-location businesses
        - Service catalog with pricing and categories
        - Staff availability and booking system
        - Appointment booking with calendar integration
        - Email notifications with calendar invites (.ics files)
        - Integration with company structure
        - Automatic conflict detection for manual and website bookings
        - Prevents double booking of staff members
        - Customer management with appointment history
        - Payment tracking and transaction management
        - Invoice generation and management
        - Dashboard integration for appointment analytics
    ''',
    'author': 'Custom Development',
    'depends': ['base', 'hr', 'calendar', 'website', 'mail', 'sms', 'account', 'payment'],
    'data': [
        'data/assets.xml',
        'security/appointment_security.xml',
        'security/ir.model.access.csv',
        'wizard/employee_import_wizard_views.xml',
        'wizard/company_import_wizard_views.xml',
        'views/staff_member_views.xml',
        'views/staff_profile_views.xml',
        'views/staff_dashboard_views.xml',
        'views/branch_views.xml',
        'views/service_views.xml',
        'views/service_category_views.xml',
        'views/appointment_views.xml',
        'views/appointment_settings_views.xml',
        'views/promo_code_views.xml',
        'views/customer_views.xml',
        'views/homepage.xml',
        'views/website_templates.xml',
        'views/terms_page.xml',
        'data/mail_templates.xml',
        'data/cron_jobs.xml',
        'data/default_settings.xml',
    ],
    'demo': [
        'data/demo_data.xml',
        'data/services_demo_data.xml',
        'data/appointment_demo_data.xml',
    ],
    'external_dependencies': {
        'python': ['icalendar'],
    },
    'assets': {
        'web.assets_frontend': [
            'custom_appointments/static/src/css/dark_theme.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': '_post_init_hook',
}
